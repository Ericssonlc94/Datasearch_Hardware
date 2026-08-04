"""Aplicação FastAPI: API JSON + painel estático."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .cache import cache
from .config import settings
from .domain.catalog import CATEGORIES, validate_catalog
from .domain.drivers import DRIVERS
from .http import close_client
from .schemas import Snapshot
from .services import collector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("datasearch")

STATIC_DIR = Path(__file__).parent / "static"

_snapshot: Snapshot | None = None
_snapshot_lock = asyncio.Lock()
_last_error: str | None = None


async def _refresh(force: bool = False) -> Snapshot:
    global _snapshot, _last_error
    async with _snapshot_lock:
        try:
            snap = await collector.get_snapshot(force=force)
            _snapshot, _last_error = snap, None
            log.info(
                "snapshot atualizado — IPH %.1f (BR %.1f), cobertura %.0f%%, %d fonte(s) degradada(s)",
                snap.summary.iph,
                snap.summary.iph_brazil,
                snap.summary.coverage * 100,
                len(snap.degraded),
            )
            return snap
        except Exception as exc:  # noqa: BLE001
            _last_error = f"{type(exc).__name__}: {exc}"
            log.exception("falha ao montar snapshot")
            if _snapshot is not None:
                return _snapshot
            raise


async def _refresh_loop() -> None:
    """Mantém o snapshot quente no ritmo exigido de 15 minutos."""
    while True:
        try:
            await asyncio.sleep(settings.refresh_seconds)
            await _refresh()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("erro no loop de refresh; seguindo")


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = validate_catalog()
    if problems:
        log.warning("catálogo com inconsistências: %s", "; ".join(problems))

    task: asyncio.Task | None = None
    if settings.autorefresh:
        # Aquece em background para não travar o boot se a rede estiver lenta.
        asyncio.create_task(_refresh())
        task = asyncio.create_task(_refresh_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await close_client()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Coletor e analisador de pressão geopolítica sobre o preço de hardware "
        "para o consumidor doméstico brasileiro."
    ),
    lifespan=lifespan,
)


@app.get("/api/snapshot", response_model=Snapshot, tags=["dados"])
async def snapshot(force: bool = False) -> Snapshot:
    """Payload completo do painel. `?force=true` ignora o cache."""
    if force or _snapshot is None:
        return await _refresh(force=force)
    return _snapshot


@app.post("/api/refresh", response_model=Snapshot, tags=["dados"])
async def refresh_now() -> Snapshot:
    return await _refresh(force=True)


@app.get("/api/health", tags=["operacao"])
async def health() -> JSONResponse:
    snap = _snapshot
    ok_sources = sum(1 for s in snap.sources if s.status == "ok") if snap else 0
    total = len(snap.sources) if snap else 0
    body = {
        "status": "ok" if snap is not None else "warming",
        "version": __version__,
        "generated_at": snap.generated_at.isoformat() if snap else None,
        "coverage": snap.summary.coverage if snap else None,
        "sources_ok": ok_sources,
        "sources_total": total,
        "degraded": snap.degraded if snap else [],
        "last_error": _last_error,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(body, status_code=200 if snap is not None else 503)


@app.get("/api/sources", tags=["operacao"])
async def sources() -> list[dict]:
    """Proveniência de cada fonte na última coleta."""
    if _snapshot is None:
        raise HTTPException(status_code=503, detail="snapshot ainda não disponível")
    return [s.model_dump(mode="json") for s in _snapshot.sources]


@app.get("/api/methodology", tags=["operacao"])
async def methodology() -> dict:
    """Expõe pesos e betas para que o modelo possa ser auditado."""
    return {
        "fx_passthrough": 0.85,
        "drivers": [
            {
                "key": d.key,
                "label": d.label,
                "weight": d.weight,
                "thesis": d.thesis,
                "signals": [
                    {
                        "key": s.key,
                        "label": s.label,
                        "source": s.source,
                        "window_days": s.window_days,
                        "scale_pct": s.scale,
                        "weight": s.weight,
                    }
                    for s in d.signals
                ],
            }
            for d in DRIVERS
        ],
        "categories": [
            {
                "key": c.key,
                "label": c.label,
                "sh6": c.sh6,
                "ncms": c.ncms,
                "ipca_subitem": c.ipca_subitem,
                "ipca_is_proxy": c.ipca_is_proxy,
                "betas": c.betas,
                "sensitivity_pct": c.sensitivity_pct,
                "tax_multiplier": c.tax_multiplier,
                "tax_note": c.tax_note,
            }
            for c in CATEGORIES
        ],
        "catalog_problems": validate_catalog(),
        "note": (
            "Pesos e betas são heurísticos e editáveis em app/domain/. "
            "Alterá-los muda o índice — essa é a intenção."
        ),
    }


@app.get("/api/cache", tags=["operacao"])
async def cache_state() -> dict:
    return {
        key: {
            "status": entry.value.status,
            "as_of": entry.value.as_of.isoformat() if entry.value.as_of else None,
            "error": entry.value.error,
        }
        for key, entry in sorted(cache._data.items())  # noqa: SLF001 — endpoint de diagnóstico
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
