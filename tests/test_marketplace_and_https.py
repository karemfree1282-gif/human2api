"""Full Marketplace Lifecycle, Ed25519 Signatures, SQLite Backup/Restore, Audit Logs, and Local HTTPS/TLS E2E Tests."""

from __future__ import annotations

import base64
import datetime
import ipaddress
import pathlib
import ssl
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from human2api.http_server import Human2APIServer
from human2api.marketplace import MarketplaceManager
from human2api.models import Workflow, WorkflowStep
from human2api.registry import ToolRegistry
from human2api.registry_backup import backup_registry_db, restore_registry_db
from human2api.registry_client import RemoteRegistryClient
from human2api.trust import (
    UntrustedPackageError,
    build_package_zip_bytes,
    generate_ed25519_keypair,
)
from human2api.workspace import Workspace


def _generate_self_signed_tls_files(tmp_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.2")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_dir / "server.crt"
    key_path = tmp_dir / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class TestMarketplaceAndHTTPS(unittest.TestCase):
    def test_full_marketplace_lifecycle_and_untrusted_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            reg = ToolRegistry(root / "registry.sqlite3")
            mp = MarketplaceManager(root / "installed", registry=reg)

            # 1. Create publisher account & Ed25519 keypair
            priv_key, pub_key = generate_ed25519_keypair()
            pub_token = reg.register_publisher("acme_labs", "Acme Automation Labs", pub_key)

            # 2. Build & sign package v1.0.0
            wf_v1 = Workflow(
                name="Invoice Exporter",
                target="browser",
                mode="read",
                allowedHosts=["127.0.0.2"],
                steps=[WorkflowStep(action="goto", url="http://127.0.0.2:8000/demo")],
            )
            pkg_v1_bytes = build_package_zip_bytes(
                workflow=wf_v1,
                private_key_b64=priv_key,
                tool_id="invoice-exporter",
                version="1.0.0",
                publisher_id="acme_labs",
            )
            pub_info = reg.publish_package("acme_labs", pub_token, pkg_v1_bytes, category="finance")
            self.assertEqual(pub_info["version"], "1.0.0")

            # 3. Search, inspect details, and install v1.0.0
            found = reg.search_packages(query="invoice", category="finance")
            self.assertEqual(len(found), 1)
            installed_v1 = mp.install_from_registry("invoice-exporter", "1.0.0")
            self.assertEqual(installed_v1["version"], "1.0.0")

            # 4. Publish v1.1.0 with expanded host permission & test version diff
            wf_v2 = Workflow(
                name="Invoice Exporter",
                target="browser",
                mode="write",
                allowedHosts=["127.0.0.2", "billing.example.org"],
                steps=[
                    WorkflowStep(action="goto", url="http://127.0.0.2:8000/demo"),
                    WorkflowStep(action="click", selector="#submit-invoice-btn", isWriteAction=True),
                ],
            )
            pkg_v2_bytes = build_package_zip_bytes(
                workflow=wf_v2,
                private_key_b64=priv_key,
                tool_id="invoice-exporter",
                version="1.1.0",
                publisher_id="acme_labs",
            )
            reg.publish_package("acme_labs", pub_token, pkg_v2_bytes, category="finance")

            diff = reg.diff_versions("invoice-exporter", "1.0.0", "1.1.0")
            self.assertTrue(diff["privilege_expanded"])
            self.assertIn("billing.example.org", diff["hosts_added"])

            # Upgrade without explicit privilege expansion consent must fail
            with self.assertRaises(PermissionError):
                mp.install_from_registry("invoice-exporter", "1.1.0", allow_privilege_expansion=False)

            # Upgrade with explicit approval succeeds
            installed_v2 = mp.install_from_registry("invoice-exporter", "1.1.0", allow_privilege_expansion=True)
            self.assertEqual(installed_v2["version"], "1.1.0")

            # 5. Reject package signed by an untrusted/impersonating key
            rogue_priv, _ = generate_ed25519_keypair()
            rogue_zip = build_package_zip_bytes(
                workflow=wf_v1,
                private_key_b64=rogue_priv,
                tool_id="invoice-exporter",
                version="1.2.0",
                publisher_id="acme_labs",
            )
            with self.assertRaises(UntrustedPackageError):
                reg.publish_package("acme_labs", pub_token, rogue_zip)
            with self.assertRaises(UntrustedPackageError):
                mp.install_from_bytes(rogue_zip)

            # 6. Verified reviews, suspicious tool reporting, yanking, and revoked publisher review block
            rev_priv, rev_pub = generate_ed25519_keypair()
            rev_token = reg.register_publisher("auditor_1", "Security Auditor", rev_pub)
            reg.add_review("auditor_1", rev_token, "invoice-exporter", "1.1.0", rating=5, comment="Verified clean.")
            reg.report_suspicious_tool("invoice-exporter", "1.0.0", reporter="auditor_1", reason="Outdated selectors")

            reg.yank_package("acme_labs", pub_token, "invoice-exporter", "1.0.0", reason="superseded")
            with self.assertRaises(PermissionError):
                mp.install_from_registry("invoice-exporter", "1.0.0")

            reg.revoke_publisher("auditor_1", reason="compromised_token")
            with self.assertRaises(PermissionError):
                reg.add_review("auditor_1", rev_token, "invoice-exporter", "1.1.0", rating=1, comment="Should fail")

            # 7. Verify tamper-evident audit chain & hot SQLite backup/restore
            self.assertTrue(reg.verify_audit_chain())
            bmeta = backup_registry_db(reg.db_path, root / "backup")
            self.assertEqual(len(bmeta["sha256"]), 64)
            restored_path = root / "restored.sqlite3"
            restore_registry_db(root / "backup", restored_path)
            reg_restored = ToolRegistry(restored_path)
            self.assertTrue(reg_restored.verify_audit_chain())

    def test_https_tls_marketplace_server_and_remote_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cert_path, key_path = _generate_self_signed_tls_files(root)

            server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

            client_ctx = ssl.create_default_context(cafile=str(cert_path))

            ws = Workspace(root / "ws")
            priv, pub = generate_ed25519_keypair()
            tok = ws.registry.register_publisher("tls_pub", "TLS Publisher", pub)
            wf = Workflow(
                name="HTTPS Verified Tool",
                target="browser",
                steps=[WorkflowStep(action="goto", url="http://127.0.0.2:8000/demo")],
            )
            zbytes = build_package_zip_bytes(wf, priv, "https-tool", "1.0.0", "tls_pub")
            pub_res = ws.registry.publish_package("tls_pub", tok, zbytes)

            srv = Human2APIServer(workspace=ws, host="127.0.0.1", port=0, ssl_context=server_ctx)
            base_url = srv.start()
            try:
                self.assertTrue(base_url.startswith("https://127.0.0.1:"))
                client = RemoteRegistryClient(base_url, ssl_context=client_ctx)
                catalog = client.fetch_catalog()
                self.assertEqual(len(catalog), 1)
                self.assertEqual(catalog[0]["tool_id"], "https-tool")

                dl_bytes, manifest, dl_wf = client.download_and_verify(
                    "https-tool",
                    "1.0.0",
                    expected_sha256=pub_res["sha256"],
                    trusted_public_key_b64=pub,
                )
                self.assertEqual(dl_wf.name, "HTTPS Verified Tool")
                self.assertEqual(manifest["publisher_id"], "tls_pub")
            finally:
                srv.stop()


if __name__ == "__main__":
    unittest.main()
