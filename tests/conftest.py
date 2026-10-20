import sys
from pathlib import Path

# Permite `from fixtures.excel_sintetico import ...` en las pruebas.
sys.path.insert(0, str(Path(__file__).parent))
