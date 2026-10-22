import os
import sys
import unittest
from pathlib import Path

if __name__ == "__main__":
    program = unittest.main(module=None, argv=[sys.argv[0], "discover", "-s", str(Path(__file__).resolve().parent), *sys.argv[1:]], exit=False)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if program.result.wasSuccessful() else 1)
