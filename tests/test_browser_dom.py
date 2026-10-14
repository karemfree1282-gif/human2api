import unittest
from human2api.recorder import build_resilient_selectors

class TestBrowserDOMSelectors(unittest.TestCase):
    def test_selector_priority_testid_over_id_and_css(self) -> None:
        primary, fallbacks = build_resilient_selectors({
            "data_testid": "invoice-btn",
            "id": "btn-1",
            "aria_label": "Submit Invoice",
            "role": "button",
            "accessible_name": "Submit Invoice",
            "selector": "button.primary",
        })
        self.assertEqual(primary, '[data-testid="invoice-btn"]')
        self.assertTrue(any(f.value == "#btn-1" for f in fallbacks))
