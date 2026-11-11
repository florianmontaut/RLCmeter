import os
import pathlib
import sys

# tests lancés sans écran, depuis n'importe quel dossier
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
