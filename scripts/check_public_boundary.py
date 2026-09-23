from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.public_boundary import assert_public_boundary

assert_public_boundary(ROOT)
print("Public/private data boundary check passed.")
