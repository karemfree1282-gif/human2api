import pathlib, tempfile, unittest
from human2api.vault import SecretVault, VaultAuthenticationError, VaultLockedError

class TestVaultStandalone(unittest.TestCase):
    def test_vault_crud_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            v = SecretVault(pathlib.Path(tmp) / "v.json")
            v.initialize("pass1234", {"k1": "v1"})
            v.set_secret("k2", "v2")
            self.assertEqual(v.list_secret_names(), ["k1", "k2"])
            self.assertTrue(v.delete_secret("k1"))
            self.assertFalse(v.delete_secret("nonexistent"))
            self.assertEqual(v.list_secret_names(), ["k2"])
