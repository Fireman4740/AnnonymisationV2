"""Rend le paquet importable sans installation préalable (`pip install -e .`).

Confort de développement uniquement : la CI installe le paquet normalement.
"""

import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
