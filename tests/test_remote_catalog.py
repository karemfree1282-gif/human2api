import pathlib, unittest, json

class TestRemoteCatalogFormat(unittest.TestCase):
    def test_catalog_index_json_valid(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        cat = json.loads((root / "catalog" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(cat["schema"], "h2a-community-catalog-v1")
        self.assertGreaterEqual(len(cat["packages"]), 1)
