"""The analytics URL filter (web/js/app/analytics.js), run in Node when Node is installed."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ANALYTICS = Path(__file__).resolve().parents[1] / "web" / "js" / "app" / "analytics.js"

SCRIPT = """
const m = await import(process.argv[1]);
const event = {
  event: "$pageview",
  properties: {
    $current_url: "https://softonsofa.com/pol-civ/?email=a@b.c&utm_source=x#city=1261011",
    $referrer: "https://example.com/search?q=private",
    $referring_domain: "example.com",
    $pathname: "/pol-civ/",
    lens: "density",
    ms: 120,
  },
  $set_once: { $initial_current_url: "https://softonsofa.com/pol-civ/?email=a@b.c" },
};
console.log(JSON.stringify({
  url: m.sanitizeUrl("https://softonsofa.com/pol-civ/?email=a@b.c&utm_source=x"),
  plain: m.sanitizeUrl("https://softonsofa.com/pol-civ/atlas/krakow/"),
  direct: m.sanitizeUrl("$direct"),
  event: m.sanitizeEvent(event),
  top: m.embedHost({ top: 1, self: 1 }),
  framed: m.embedHost({ top: 1, self: 2, location: { ancestorOrigins: ["https://earthciv.org"] } }),
  byReferrer: m.embedHost({ top: 1, self: 2, location: {}, document: { referrer: "https://maps.example.org/x?y=1" } }),
  hidden: m.embedHost({ top: 1, self: 2, location: {}, document: { referrer: "" } }),
  notFramedEvent: "embedded_in" in m.sanitizeEvent({ properties: {} }).properties,
}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AnalyticsUrlFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = subprocess.run(
            ["node", "--input-type=module", "-e", SCRIPT, ANALYTICS.as_uri()],
            capture_output=True, text=True, timeout=30, check=True,
        )
        cls.out = json.loads(run.stdout)

    def test_keeps_only_utm_parameters(self):
        self.assertEqual(self.out["url"], "https://softonsofa.com/pol-civ/?utm_source=x")

    def test_leaves_a_clean_url_and_non_urls_alone(self):
        self.assertEqual(self.out["plain"], "https://softonsofa.com/pol-civ/atlas/krakow/")
        self.assertEqual(self.out["direct"], "$direct")

    def test_before_send_rewrites_every_url_property(self):
        props = self.out["event"]["properties"]
        self.assertEqual(props["$current_url"], "https://softonsofa.com/pol-civ/?utm_source=x#city=1261011")
        self.assertEqual(props["$referrer"], "https://example.com/search")
        self.assertEqual(props["$referring_domain"], "example.com")
        self.assertEqual(props["lens"], "density")
        self.assertEqual(props["ms"], 120)
        self.assertEqual(self.out["event"]["$set_once"]["$initial_current_url"], "https://softonsofa.com/pol-civ/")
        self.assertNotIn("email", json.dumps(self.out["event"]))

    def test_embedding_site_host_or_unknown(self):
        self.assertIsNone(self.out["top"])
        self.assertEqual(self.out["framed"], "earthciv.org")
        self.assertEqual(self.out["byReferrer"], "maps.example.org")
        self.assertEqual(self.out["hidden"], "unknown")
        self.assertFalse(self.out["notFramedEvent"])


if __name__ == "__main__":
    unittest.main()
