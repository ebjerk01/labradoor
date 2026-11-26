"""Runs the Ctrl-K item check (tests/palette.test.mjs) so deploy.sh's unittest pass covers it."""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Palette(unittest.TestCase):
    def test_item_actions(self):
        r = subprocess.run(["node", os.path.join(HERE, "palette.test.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
