"""Aplicação FastAPI: API JSON + painel estático."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .cache import cache
from .config import settings
from .domain import backfill
from .domain.catalog import CATEGORIES, validate_catalog
from .domain.drivers import DRIVERS
from .domain.ranking import CALIBRATION_DAYS, HORIZON_DAYS
from .domain.series import SERIES_BY_KEY, catalog_groups
from .domain.analyzer import FX_HORIZON_DAYS, FX_PASSTHROUGH, FX_PASSTHROUGH_DAYS
from .domain.supply import QUEUE_METHODOLOGY
from .http import close_client
from .schemas import Snapshot, public_error
from .services import collector, history
from .services.progress import progress

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("datasearch")

STATIC_DIR = Path(__file__).parent / "static"

_snapshot: Snapshot | None = None
# Coleta em andamento. Quem chega durante ela espera a mesma (single-flight)
# em vez de enfileirar outra coleta completa.
_inflight: asyncio.Task | None = None
# `time.monotonic()` do início da última coleta forçada por /api/refresh.
_last_forced_at: float | None = None
_last_error: str | None = None
_purge_day: date | None = None


async def _maybe_purge() -> None:
    """Aplica a retenção no máximo uma vez por dia."""
    global _purge_day
    today = datetime.now(timezone.utc).date()
    if _purge_day == today:
        return
    _purge_day = today
    try:
        await asyncio.to_thread(history.purge)
    except Exception:  # noqa: BLE001 — retenção não pode derrubar o painel
        log.exception("falha ao aplicar retenção do histórico")


# Dias de IPH recalculados a partir das séries coletadas (ver domain/backfill).
# Abaixo da cobertura mínima o ciclo não reconstrói: o ponto gravado não é
# refeito depois, e uma rodada com fontes caídas congelaria uma série capenga.
RECONSTRUCT_DAYS = 30
RECONSTRUCT_MIN_COVERAGE = 0.9


def _reconstruct_history(collected: dict) -> int:
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=n) for n in range(RECONSTRUCT_DAYS, 0, -1)]
    return history.record_reconstruction(
        backfill.reconstruct(collected, days), backfill.MODEL_VERSION
    )


async def _collect(force: bool) -> Snapshot:
    global _snapshot, _last_error
    try:
        snap, collected = await collector.collect_and_build(force=force)
        _snapshot, _last_error = snap, None
        # Histórico é acessório: se o disco falhar, o snapshot continua.
        try:
            await asyncio.to_thread(history.record_snapshot, snap)
            if snap.summary.coverage >= RECONSTRUCT_MIN_COVERAGE:
                written = await asyncio.to_thread(_reconstruct_history, collected)
                if written:
                    log.info("histórico: %d ponto(s) reconstruído(s)", written)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gravar histórico; seguindo sem ele")
        # Cache persistido também é acessório: sem ele, o próximo start só
        # coleta tudo de novo.
        try:
            saved = await asyncio.to_thread(cache.save, settings.cache_file)
            log.info("cache: %d entrada(s) gravada(s) em disco", saved)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gravar o cache em disco; seguindo sem ele")
        await _maybe_purge()
        log.info(
            "snapshot atualizado — IPH %.1f (BR %.1f), cobertura %.0f%%, %d fonte(s) degradada(s)",
            snap.summary.iph,
            snap.summary.iph_brazil,
            snap.summary.coverage * 100,
            len(snap.degraded),
        )
        progress.ready()
        return snap
    except Exception as exc:  # noqa: BLE001
        # O texto da exceção fica no log; a API mostra só o tipo do erro.
        _last_error = f"{type(exc).__name__}: falha ao montar o snapshot"
        progress.fail(_last_error)
        log.exception("falha ao montar snapshot")
        if _snapshot is not None:
            return _snapshot
        raise


async def _refresh(force: bool = False) -> Snapshot:
    """Junta-se à coleta em andamento ou inicia uma.

    O `shield` impede que um cliente que desconecta cancele a coleta que os
    outros pedidos (e o loop de 15 min) estão esperando.
    """
    global _inflight
    if _inflight is None or _inflight.done():
        _inflight = asyncio.create_task(_collect(force))
    return await asyncio.shield(_inflight)


def _collecting() -> bool:
    return _inflight is not None and not _inflight.done()


async def _snapshot_or_503(force: bool = False) -> Snapshot:
    try:
        return await _refresh(force=force)
    except Exception:  # noqa: BLE001 — o detalhe já foi para o log em _collect
        raise HTTPException(
            status_code=503, detail="coleta falhou e ainda não há snapshot anterior"
        ) from None


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
    try:
        await asyncio.to_thread(history.init_db)
        await asyncio.to_thread(history.purge)
    except Exception:  # noqa: BLE001 — histórico indisponível não impede o painel
        log.exception("histórico indisponível; a aba Tendência ficará vazia")

    problems = validate_catalog()
    if problems:
        log.warning("catálogo com inconsistências: %s", "; ".join(problems))

    try:
        loaded = await asyncio.to_thread(cache.load, settings.cache_file)
        log.info("cache: %d entrada(s) carregada(s) de %s", loaded, settings.cache_file)
    except Exception:  # noqa: BLE001 — sem cache em disco, a coleta só demora mais
        log.exception("cache em disco indisponível; começando vazio")

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
        # Fechar o app logo após a 1ª coleta (antes do save em _collect) não
        # pode jogar fora as fontes que já chegaram.
        try:
            saved = await asyncio.to_thread(cache.save, settings.cache_file)
            log.info("cache: %d entrada(s) gravada(s) ao desligar", saved)
        except Exception:  # noqa: BLE001
            log.exception("falha ao gravar o cache ao desligar")
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

# O snapshot e o histórico são JSON grande e repetitivo; gzip corta ~80%.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# O painel só carrega arquivos locais (Plotly vendorizado em static/vendor/).
# `style-src 'unsafe-inline'` cobre os `style=` gerados e o estilo que o Plotly
# injeta; `img-src data:` cobre o favicon SVG e `blob:` o download em PNG pelo
# menu do Plotly. Sem 'unsafe-eval': a QA confirmou que o Plotly 2.35.2 roda
# sem ele (os `new Function` são fallbacks dentro de try/catch).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'"
)
# O Swagger em /docs e /redoc carrega JS de CDN; a CSP acima o quebraria.
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    return response


# Por último = mais externo: Host fora da lista é recusado (400) antes de tudo,
# o que barra DNS rebinding contra o servidor local.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

# Janelas aceitas por /api/history, em segundos.
_RANGES: dict[str, int] = {
    "24h": 24 * 3600,
    "7d": 7 * 86_400,
    "30d": 30 * 86_400,
    "90d": 90 * 86_400,
    "1y": 365 * 86_400,
}

# Bucket automático: denso no curto prazo, diário no longo. O objetivo é ficar
# abaixo de ~400 pontos por série sem perder a forma da curva.
_AUTO_BUCKET: dict[str, int] = {
    "24h": 900,
    "7d": 3600,
    # 30 dias em bucket diário: casa com os pontos reconstruídos (um por dia)
    # e evita que buckets de 6 h vazios entre eles quebrem a linha.
    "30d": 86_400,
    "90d": 86_400,
    "1y": 86_400,
}

_BUCKETS: dict[str, int | None] = {
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "6h": 6 * 3600,
    "12h": 12 * 3600,
    "1d": 86_400,
    "raw": None,
}

_MAX_SERIES_PER_CALL = 12


@app.get("/api/snapshot", response_model=Snapshot, tags=["dados"])
async def snapshot() -> Snapshot:
    """Payload completo do painel, sem efeito colateral.

    Só coleta se ainda não houver snapshot; forçar coleta é `POST /api/refresh`.
    """
    if _snapshot is None:
        return await _snapshot_or_503()
    return _snapshot


@app.get("/api/progress", tags=["operacao"])
async def collection_progress() -> dict:
    """Percentual do ciclo de coleta em andamento.

    A tela de carregamento consulta esta rota enquanto `/api/snapshot` ainda
    está bloqueado montando o primeiro payload.
    """
    return progress.snapshot()


# Header próprio exigido no POST /api/refresh. Um site de terceiros não consegue
# mandá-lo sem preflight CORS, e o servidor não libera CORS: isso barra CSRF.
REFRESH_HEADER = "X-DSH-Refresh"


@app.post("/api/refresh", response_model=Snapshot, tags=["dados"])
async def refresh_now(
    x_dsh_refresh: str | None = Header(None, alias=REFRESH_HEADER),
) -> Snapshot:
    """Força uma coleta que ignora o cache.

    Exige `X-DSH-Refresh: 1`. Com coleta em andamento, espera a mesma; fora
    dela, aceita no máximo uma coleta forçada a cada
    `refresh_min_interval_seconds` e responde 429 com `Retry-After` antes disso.
    """
    global _last_forced_at
    if x_dsh_refresh != "1":
        raise HTTPException(status_code=403, detail=f"header {REFRESH_HEADER}: 1 obrigatório")
    if _collecting():
        return await _snapshot_or_503()

    now = time.monotonic()
    if _last_forced_at is not None:
        wait = settings.refresh_min_interval_seconds - (now - _last_forced_at)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail="coleta forçada recente; use GET /api/snapshot",
                headers={"Retry-After": str(math.ceil(wait))},
            )
    _last_forced_at = now
    return await _snapshot_or_503(force=True)


@app.get("/api/series", tags=["dados"])
async def series_catalog() -> dict:
    """Catálogo de séries do histórico, com pontos e extremos de cada uma."""
    bounds = await asyncio.to_thread(history.available_bounds)
    breaks = await asyncio.to_thread(history.model_breaks)
    groups = catalog_groups()
    for group in groups:
        for item in group["series"]:
            item["model_since"] = history.model_since_for(item["key"], breaks)
            info = bounds.get(item["key"], {})
            item["points"] = int(info.get("points", 0) or 0)
            item["first_observation"] = info.get("first")
            item["last_observation"] = info.get("last")
    firsts = [info["first"] for info in bounds.values() if info.get("first")]
    return {
        "groups": groups,
        "first_observation": min(firsts) if firsts else None,
        "last_observation": await asyncio.to_thread(history.last_ts),
        "note": (
            "Séries de fonte guardam a data real da observação; séries de índice "
            "e projeção são recalculadas a cada ciclo de 15 min."
        ),
    }


@app.get("/api/history", tags=["dados"])
async def api_history(
    range_: str = Query(
        "30d",
        alias="range",
        description="all | 24h | 7d | 30d | 90d | 1y",
    ),
    series: str = Query("iph,iph_br", description="chaves separadas por vírgula"),
    bucket: str = Query("auto", description="auto | 15m | 30m | 1h | 6h | 12h | 1d | raw"),
) -> dict:
    """Séries históricas. Bucket vazio vira `v: null` — o cliente quebra a linha.

    Nada é interpolado: um bucket sem observação é uma lacuna explícita.
    `range=all` usa o primeiro ponto disponível das séries pedidas.
    """
    is_all = range_ == "all"
    if not is_all and range_ not in _RANGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"range inválido: {range_!r} "
                f"(aceitos: all, {', '.join(_RANGES)})"
            ),
        )

    keys = [k.strip() for k in series.split(",") if k.strip()]
    if not keys:
        raise HTTPException(status_code=400, detail="informe ao menos uma série")
    if len(keys) > _MAX_SERIES_PER_CALL:
        raise HTTPException(
            status_code=400,
            detail=f"máximo de {_MAX_SERIES_PER_CALL} séries por chamada",
        )
    unknown = [k for k in keys if k not in SERIES_BY_KEY]
    if unknown:
        raise HTTPException(
            status_code=400, detail=f"série(s) desconhecida(s): {', '.join(unknown)}"
        )

    if bucket == "auto":
        bucket_seconds = 86_400 if is_all else _AUTO_BUCKET[range_]
    elif bucket in _BUCKETS:
        bucket_seconds = _BUCKETS[bucket]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"bucket inválido: {bucket!r} (aceitos: auto, {', '.join(_BUCKETS)})",
        )

    if is_all and bucket_seconds is not None and bucket_seconds < 86_400:
        raise HTTPException(
            status_code=400,
            detail="range=all aceita bucket=auto, 1d ou raw",
        )

    end = datetime.now(timezone.utc)
    if is_all:
        first = await asyncio.to_thread(history.first_ts, keys)
        if first:
            start = datetime.fromisoformat(first.replace("Z", "+00:00"))
        else:
            start = end - timedelta(days=settings.history_daily_retention_days)
    else:
        start = end - timedelta(seconds=_RANGES[range_])
    window = (end - start).total_seconds()

    # `raw` em 1 ano de dados de 15 min devolveria dezenas de milhares de
    # pontos e travaria o navegador. O contrato limita a janela.
    if bucket_seconds is None and window > _RANGES["7d"]:
        raise HTTPException(
            status_code=400,
            detail="bucket=raw só é aceito em janelas de até 7 dias",
        )

    data = await asyncio.to_thread(
        history.query,
        keys,
        start,
        end,
        bucket_seconds=bucket_seconds,
    )
    rebuilt = await asyncio.to_thread(history.reconstructed_until, keys)
    breaks = await asyncio.to_thread(history.model_breaks)

    return {
        "range": range_,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "bucket": bucket,
        "bucket_seconds": bucket_seconds,
        # `bucket_seconds` é o pedido; `raw` diz se a resposta veio sem
        # agregação porque havia poucos pontos. O frontend usa isso no rótulo.
        "raw": bucket_seconds is None
        or all(len(points) <= history.MAX_RAW_POINTS for points in data.values()),
        "interpolated": False,
        "series": [
            {
                "key": key,
                "label": SERIES_BY_KEY[key].label,
                "kind": SERIES_BY_KEY[key].kind,
                "unit": SERIES_BY_KEY[key].unit,
                # Até este instante, a série é recálculo diário com as séries
                # coletadas, não medição ao vivo. `None` = só medição ao vivo.
                "reconstructed_until": rebuilt.get(key),
                # Pontos antes deste instante usam uma versão antiga da conta e
                # não são comparáveis com os seguintes. `None` = sem marco.
                "model_since": history.model_since_for(key, breaks),
                "points": [{"t": t, "v": v} for t, v in data.get(key, [])],
            }
            for key in keys
        ],
    }


@app.get("/api/health", tags=["operacao"])
async def health() -> JSONResponse:
    snap = _snapshot
    ok_sources = sum(1 for s in snap.sources if s.status == "ok") if snap else 0
    total = len(snap.sources) if snap else 0
    try:
        history_last = await asyncio.to_thread(history.last_ts)
    except Exception:  # noqa: BLE001 — saúde não pode falhar por causa do histórico
        history_last = None

    body = {
        "status": "ok" if snap is not None else "warming",
        "version": __version__,
        "generated_at": snap.generated_at.isoformat() if snap else None,
        "coverage": snap.summary.coverage if snap else None,
        "sources_ok": ok_sources,
        "sources_total": total,
        "degraded": snap.degraded if snap else [],
        "last_error": _last_error,
        "history_last_observation": history_last,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(body, status_code=200 if snap is not None else 503)


@app.get("/api/sources", tags=["operacao"])
async def sources() -> list[dict]:
    """Proveniência de cada fonte na última coleta."""
    if _snapshot is None:
        raise HTTPException(status_code=503, detail="snapshot ainda não disponível")
    return [s.model_dump(mode="json") for s in _snapshot.sources]


@app.get("/api/supply", tags=["dados"])
async def supply_context() -> dict:
    """Fila do consumidor da última coleta (capex, estoque, Comtrade)."""
    if _snapshot is None:
        raise HTTPException(status_code=503, detail="snapshot ainda não disponível")
    return _snapshot.supply.model_dump(mode="json")


@app.get("/api/prices", tags=["dados"])
async def store_prices() -> dict:
    """Preço na KaBuM por categoria e faixa e a visão AMD × NVIDIA (§T28c).

    Fonte desligada ou contas ainda não ligadas: 200 com `source.status =
    "disabled"` e o motivo, para o painel explicar em vez de quebrar.
    """
    if _snapshot is None:
        raise HTTPException(status_code=503, detail="snapshot ainda não disponível")
    return _snapshot.prices or collector._disabled_prices("Sem preços nesta rodada.")


@app.get("/api/methodology", tags=["operacao"])
async def methodology() -> dict:
    """Expõe pesos e betas para que o modelo possa ser auditado."""
    return {
        "fx_passthrough": FX_PASSTHROUGH,
        "fx_passthrough_days": FX_PASSTHROUGH_DAYS,
        "fx_horizon_days": FX_HORIZON_DAYS,
        "horizon_days": HORIZON_DAYS,
        "sensitivity_calibration_days": CALIBRATION_DAYS,
        "reconstruction": {
            "days": RECONSTRUCT_DAYS,
            "min_coverage": RECONSTRUCT_MIN_COVERAGE,
            "model_version": backfill.MODEL_VERSION,
            "note": (
                "Dias anteriores ao primeiro ciclo ao vivo são recalculados com as "
                "séries cortadas em cada data. Séries mensais entram pela data de "
                "referência, não pela de publicação."
            ),
        },
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
                        "smooth_days": s.smooth_days,
                        "scale_pct": s.scale,
                        "weight": s.weight,
                        "invert": s.invert,
                        "fallback_source": s.fallback_source,
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
        "queue": {**QUEUE_METHODOLOGY, "model_version": history.model_versions()["supply.queue"]},
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
            "error": public_error(entry.value.error),
        }
        for key, entry in sorted(cache._data.items())  # noqa: SLF001 — endpoint de diagnóstico
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
