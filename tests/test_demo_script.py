import json
import subprocess
import sys
import unittest


class DemoScriptTests(unittest.TestCase):
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
