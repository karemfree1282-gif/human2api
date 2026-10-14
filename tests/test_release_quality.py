import pathlib, unittest

class TestReleaseQualityMetadata(unittest.TestCase):
    def test_android_companion_sources_and_manifest_exist(self) -> None:
        root = pathlib.Path(__file__).resolve().parents[1]
        manifest = root / "android-companion" / "app" / "src" / "main" / "AndroidManifest.xml"
        svc = root / "android-companion" / "app" / "src" / "main" / "java" / "dev" / "human2api" / "companion" / "CompanionService.java"
        self.assertTrue(manifest.exists())
        self.assertTrue(svc.exists())
        self.assertIn("BIND_ACCESSIBILITY_SERVICE", manifest.read_text(encoding="utf-8"))
        self.assertIn("isPassword()", svc.read_text(encoding="utf-8"))
