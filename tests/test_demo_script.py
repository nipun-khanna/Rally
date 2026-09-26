import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


class DemoScriptTests(unittest.TestCase):
    def test_offline_replay_exports_source_backed_labeled_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, "-m", "scripts.demo_smoke",
                                     "--output-dir", tmp],
                                    capture_output=True, text=True, check=True)
            output = json.loads(result.stdout)
            self.assertEqual(output["state"], "DONE")
            self.assertEqual(output["proposal_venue_id"], "demo-italian")
            self.assertGreater(date.fromisoformat(output["plan_date"]), date.today())
            for stage in ("blocked", "ready", "done"):
                page = (Path(tmp) / f"{stage}.html").read_text()
                self.assertIn("Offline replay", page)
                self.assertIn("Fixed extraction", page)
                self.assertIn(stage.upper(), page)
                self.assertIn("Anything except sushi.", page)
                self.assertIn("after 7", page)
            ready = (Path(tmp) / "ready.html").read_text()
            self.assertIn("An Italian Table", ready)
            self.assertIn("20:00", ready)
            self.assertIn("No reservation result yet", ready)
            self.assertNotIn("Demo Sushi Bar", ready)
            done = (Path(tmp) / "done.html").read_text()
            self.assertIn("RLY-", done)
            self.assertIn("no table is reserved", done)

    def test_offline_demo_completes_under_two_minutes(self):
        result = subprocess.run([sys.executable, "-m", "scripts.demo_smoke"],
                                capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        self.assertEqual(output["state"], "DONE")
        self.assertEqual(output["reservation_count"], 1)
        self.assertEqual(output["sent_messages"], 2)
        self.assertLess(output["elapsed_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
