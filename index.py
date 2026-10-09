"""Point d'entrée Vercel : expose l'application FastAPI définie dans backend/app/main.py.

Vercel détecte une variable `app` (FastAPI) dans index.py à la racine du dépôt.
Le déploiement Docker n'utilise pas ce fichier.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.main import app  # noqa: E402,F401
