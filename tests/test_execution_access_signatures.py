import unittest
from human2api.trust import generate_ed25519_keypair, sign_package_payload, verify_package_signature, UntrustedPackageError

class TestExecutionAccessSignatures(unittest.TestCase):
    def test_ed25519_version_bound_signature_tamper_detection(self) -> None:
        priv, pub = generate_ed25519_keypair()
        wf = {"name": "SignedFlow", "target": "browser", "steps": [{"action": "wait"}]}
        manifest = sign_package_payload(priv, "signed-flow", "1.0.0", "pub1", wf)
        self.assertTrue(verify_package_signature(manifest, wf, trusted_public_key_b64=pub))
        manifest_tampered = dict(manifest, version="2.0.0")
        with self.assertRaises(UntrustedPackageError):
            verify_package_signature(manifest_tampered, wf, trusted_public_key_b64=pub)
