"""Expose the repository's shared test support to this standalone suite.

These tests run from inside ``libs/workbench`` and are not part of the root
``tests`` package, so pytest never puts the repository root on ``sys.path``.
Adding it lets them reuse ``tests.support.uploads`` instead of keeping a second
copy of the confirmed-upload seeding helper.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
