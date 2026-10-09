"""Point d'entrée de l'API SIGED (FastAPI)."""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import admin, auth, classification, cron, documents, search
from app.core.config import get_settings
from app.core.database import get_engine, init_engine, initialize
from app.services.documents import BusinessError
from app.services.storage import get_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
logger = logging.getLogger("siged")
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    problems = get_settings().production_problems()
    if problems:
        raise RuntimeError("Configuration de production incomplète : " + " ; ".join(problems))
    init_engine()
    initialize()
    logger.info("SIGED démarré (base : %s, stockage : %s)", get_engine().dialect.name, get_settings().storage_backend)
    yield


app = FastAPI(
    title="SIGED API",
    description="Système Intégré de Gestion Électronique des Documents et d'archivage "
                "(ISO 15489 / ISO 14721 OAIS). Authentification : JWT (Bearer) ou clé d'API (X-API-Key).",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def perf_and_security(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Process-Time-ms"] = f"{ms:.1f}"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if ms > get_settings().slow_request_ms and request.url.path.startswith("/api"):
        logger.warning("Requête lente (%.0f ms > %s ms) : %s %s", ms, get_settings().slow_request_ms,
                       request.method, request.url.path)
    return response


@app.exception_handler(BusinessError)
async def business_error(_: Request, exc: BusinessError):
    return JSONResponse({"detail": exc.message, **exc.extra}, status_code=exc.status_code)


for r in (auth.router, documents.router, search.router, classification.router, admin.router, admin.integrations,
          cron.router):
    app.include_router(r)


@app.get("/health", tags=["Supervision"], summary="Sonde de disponibilité (base + stockage)")
def health():
    db_ok = storage_ok = False
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        pass
    try:
        storage_ok = get_storage().ping()
    except Exception:  # noqa: BLE001
        pass
    ok = db_ok and storage_ok
    return JSONResponse({"status": "ok" if ok else "degraded", "database": db_ok, "storage": storage_ok},
                        status_code=200 if ok else 503)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
