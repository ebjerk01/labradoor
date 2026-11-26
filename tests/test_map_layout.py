"""Runs the map layout check (tests/map_layout.test.mjs) so deploy.sh's unittest pass covers it."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class MapLayout(unittest.TestCase):
    def test_no_crossings(self):
        r = subprocess.run(["node", os.path.join(HERE, "map_layout.test.mjs")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
