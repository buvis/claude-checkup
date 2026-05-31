"""Root pytest config: put lib/ on sys.path so tests and scripts share helpers.

Mirrors the runtime bootstrap each script performs (resolve lib/ relative to the
repo root and import the shared modules as top-level names).
"""

import sys
from pathlib import Path

_LIB = Path(__file__).parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
