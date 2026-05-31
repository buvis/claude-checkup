"""pytest config: put this scripts/ dir on sys.path so tests can import the modules."""

import sys
from pathlib import Path

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
