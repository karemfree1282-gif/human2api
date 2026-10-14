"""Self-Healing 4-Tier Engine Tests & Security Regression Test Suite (`tests/test_healing_and_security.py`).
Every security vulnerability and edge case has a dedicated regression test.
"""

from __future__ import annotations

import http.client
import json
import pathlib
import tempfile
import time
import unittest
import zipfile
import io

from human2api.contracts import redact_secrets, safe_resolve_user_path, validate_url_against_policy
from human2api.healing import SelfHealingEngine, UIElementCandidate
from human2api.http_server import Human2APIServer
from human2api.models import HealingConfig, SelectorCandidate, Workflow, WorkflowStep
from human2api.trust import UnsafePackageArchiveError, unpack_and_verify_package_zip
from human2api.vault import SecretVault, VaultAuthenticationError, VaultLockedError
from human2api.workspace import Workspace


class TestSelfHealingAndSecurityRegressions(unittest.TestCase):
    def test_healing_tiers_1_to_4_and_safety_guards(self) -> None:
        candidates = [
            UIElementCandidate(
                candidate_id="c_save",
                selector="#new-save-btn",
                role="button",
                name="حفظ الفاتورة Save Invoice",
                automation_id="save_invoice_v2",
                host_or_package="127.0.0.2",
            ),
            UIElementCandidate(
                candidate_id="c_cancel",
                selector="#cancel-btn",
                role="button",
                name="إلغاء Cancel",
                automation_id="cancel_v2",
                host_or_package="127.0.0.2",
            ),
        ]

        # Tier 1: Primary match
        engine = SelfHealingEngine(HealingConfig(enabled=True, maxTier=3))
        step_t1 = WorkflowStep(action="click", selector="#new-save-btn", role="button")
        res1 = engine.resolve(step_t1, candidates, allowed_scopes=["127.0.0.2"])
        self.assertTrue(res1.resolved)
        self.assertEqual(res1.tier, 1)

        # Tier 2: Fallback selector match
        step_t2 = WorkflowStep(
            action="click",
            selector="#missing-id",
            fallbackSelectors=[SelectorCandidate(strategy="css", value="#new-save-btn")],
            role="button",
        )
        res2 = engine.resolve(step_t2, candidates, allowed_scopes=["127.0.0.2"])
        self.assertTrue(res2.resolved)
        self.assertEqual(res2.tier, 2)

        # Tier 3: Semantic role + name match
        step_t3 = WorkflowStep(
            action="click",
            selector="#missing-id",
            role="button",
            name="حفظ الفاتورة",
        )
        res3 = engine.resolve(step_t3, candidates, allowed_scopes=["127.0.0.2"])
        self.assertTrue(res3.resolved)
        self.assertEqual(res3.tier, 3)

        # Safety Guard 1: Refuse healing/re-executing a write action that already dispatched
        step_write = WorkflowStep(
            action="click",
            selector="#missing-id",
            role="button",
            name="حفظ الفاتورة",
            isWriteAction=True,
            idempotent=False,
        )
        res_write_guard = engine.resolve(
            step_write,
            candidates,
            allowed_scopes=["127.0.0.2"],
            already_executed_write=True,
        )
        self.assertFalse(res_write_guard.resolved)
        self.assertIn("prevent duplicate write", res_write_guard.reason)

        # Safety Guard 2: Refuse ambiguous candidates with identical similarity
        ambiguous_cands = [
            UIElementCandidate(candidate_id="dup1", selector="#b1", role="button", name="تأكيد", host_or_package="127.0.0.2"),
            UIElementCandidate(candidate_id="dup2", selector="#b2", role="button", name="تأكيد", host_or_package="127.0.0.2"),
        ]
        res_amb = engine.resolve(
            WorkflowStep(action="click", selector="#missing", role="button", name="تأكيد"),
            ambiguous_cands,
            allowed_scopes=["127.0.0.2"],
        )
        self.assertFalse(res_amb.resolved)
        self.assertIn("Ambiguous", res_amb.reason)

        # Safety Guard 3: Block privilege escalation candidate
        priv_cands = [
            UIElementCandidate(
                candidate_id="evil",
                selector="#grant_admin",
                role="button",
                name="حفظ الفاتورة grant_admin",
                host_or_package="127.0.0.2",
            )
        ]
        res_priv = engine.resolve(step_t3, priv_cands, allowed_scopes=["127.0.0.2"])
        self.assertFalse(res_priv.resolved)

        # Tier 4: Consent-gated AI Advisor (rejects code payloads, accepts valid candidate_id)
        engine_t4_unsafe = SelfHealingEngine(
            HealingConfig(enabled=True, maxTier=4, aiConsent=True, aiProvider="local"),
            ai_advisor=lambda _step, _cands: "eval('alert(1)')",
        )
        res_t4_bad = engine_t4_unsafe.resolve(
            WorkflowStep(action="click", selector="#none", role="button", name="UnmatchedLabelXYZ"),
            candidates,
            allowed_scopes=["127.0.0.2"],
        )
        self.assertFalse(res_t4_bad.resolved)

        engine_t4_good = SelfHealingEngine(
            HealingConfig(enabled=True, maxTier=4, aiConsent=True, aiProvider="local"),
            ai_advisor=lambda _step, _cands: "c_save",
        )
        res_t4_ok = engine_t4_good.resolve(
            WorkflowStep(action="click", selector="#none", role="button", name="UnmatchedLabelXYZ"),
            candidates,
            allowed_scopes=["127.0.0.2"],
        )
        self.assertTrue(res_t4_ok.resolved)
        self.assertEqual(res_t4_ok.tier, 4)
        self.assertEqual(res_t4_ok.selector, "#new-save-btn")

    def test_vault_aes256_gcm_scrypt_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vpath = pathlib.Path(tmp) / "vault.json"
            vault = SecretVault(vpath, unlock_timeout_seconds=0.05)
            vault.initialize("StrongPass#2026", {"stripe_key": "sk_live_999888777"})
            self.assertEqual(vault.get_secret("stripe_key"), "sk_live_999888777")

            # Raw file on disk must not contain plaintext secret
            disk_text = vpath.read_text(encoding="utf-8")
            self.assertNotIn("sk_live_999888777", disk_text)

            # Wait for quiet timeout auto-lock
            time.sleep(0.08)
            self.assertFalse(vault.is_unlocked())
            with self.assertRaises(VaultLockedError):
                vault.get_secret("stripe_key")

            # Wrong passphrase must raise VaultAuthenticationError
            with self.assertRaises(VaultAuthenticationError):
                vault.unlock("WrongPassphrase")

            # Correct passphrase unlocks
            vault.unlock("StrongPass#2026")
            self.assertEqual(vault.get_secret("stripe_key"), "sk_live_999888777")

    def test_zip_slip_and_path_traversal_regressions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            with self.assertRaises(PermissionError):
                safe_resolve_user_path(base, "../../etc/passwd")
            with self.assertRaises(PermissionError):
                safe_resolve_user_path(base, "/etc/shadow")

        # Craft malicious ZIP with path traversal entry
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.sh", "echo hacked")
            zf.writestr("manifest.json", "{}")
            zf.writestr("workflow.json", "{}")
        with self.assertRaises(UnsafePackageArchiveError):
            unpack_and_verify_package_zip(buf.getvalue())

        # Craft ZIP with unexpected executable file
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as zf:
            zf.writestr("payload.exe", b"MZ...")
            zf.writestr("manifest.json", "{}")
            zf.writestr("workflow.json", "{}")
        with self.assertRaises(UnsafePackageArchiveError):
            unpack_and_verify_package_zip(buf2.getvalue())

    def test_http_security_headers_csrf_dns_rebinding_and_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(pathlib.Path(tmp))
            srv = Human2APIServer(workspace=ws, host="127.0.0.1", port=0)
            srv.start()
            try:
                # 1. Missing token -> 401
                conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                conn.request("GET", "/api/v1/health")
                r1 = conn.getresponse()
                self.assertEqual(r1.status, 401)
                conn.close()

                # 2. DNS Rebinding Host header -> 403
                conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                conn.putrequest("GET", "/api/v1/health", skip_host=True)
                conn.putheader("Host", "attacker-rebind.evil.com")
                conn.putheader("X-H2A-Token", srv.auth_token)
                conn.endheaders()
                r2 = conn.getresponse()
                self.assertEqual(r2.status, 403)
                conn.close()

                # 3. Cross-Origin CSRF header -> 403
                conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                conn.request(
                    "POST",
                    "/api/v1/settings",
                    body=b"{}",
                    headers={
                        "Host": f"127.0.0.1:{srv.port}",
                        "Origin": "https://csrf-attacker.example.com",
                        "X-H2A-Token": srv.auth_token,
                        "Content-Type": "application/json",
                    },
                )
                r3 = conn.getresponse()
                self.assertEqual(r3.status, 403)
                conn.close()

                # 4. Duplicate sensitive header (Authorization / X-H2A-Token) -> 400
                conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                conn.putrequest("GET", "/api/v1/health")
                conn.putheader("X-H2A-Token", srv.auth_token)
                conn.putheader("X-H2A-Token", "second_token_attempt")
                conn.endheaders()
                r4 = conn.getresponse()
                self.assertEqual(r4.status, 400)
                conn.close()

                # 5. Valid authenticated request -> 200
                conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                conn.request("GET", "/api/v1/health", headers={"X-H2A-Token": srv.auth_token})
                r5 = conn.getresponse()
                self.assertEqual(r5.status, 200)
                conn.close()
            finally:
                srv.stop()


if __name__ == "__main__":
    unittest.main()
