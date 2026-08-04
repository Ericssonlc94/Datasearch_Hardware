"""Orquestra a coleta paralela de todas as fontes e monta o Snapshot.

Nada aqui levanta exceção para o chamador: cada fonte é isolada pelo cache,
que converte falha em `stale` (último valor bom) ou `unavailable`. O painel
sempre renderiza — o que muda é a `coverage` e a lista `degraded`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..cache import Fetched, cache
from ..config import settings
from ..domain.analyzer import build_brazil, build_drivers, build_summary
from ..domain.catalog import CATEGORIES
from ..domain.ranking import build_ranking
from ..providers import bcb, comexstat, comtrade, fred, gdelt, ibge, markets
from ..schemas import Snapshot

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Índices e projeções deste painel são resultado de um modelo heurístico "
    "próprio, calibrado sobre dados públicos — não são previsão validada nem "
    "recomendação de compra. Os campos marcados como observados (IPCA/IBGE, "
    "PTAX/BCB, Comex Stat/MDIC) são medições oficiais; os marcados como "
    "modelados são estimativa. Confira sempre a aba de fontes."
)

# Frequências mensais não mudam a cada 15 minutos; bater nelas nesse ritmo é
# desperdício e convite a bloqueio.
_FRED_MONTHLY = {
    "ppi_semiconductors",
    "import_px_semis",
    "copper",
    "aluminum",
    "natgas_eu",
    "cpi_computers_us",
    "global_metals",
    "global_energy",
    "global_all",
}


def _tasks() -> list[tuple[str, int, callable]]:
    """Monta a lista (chave, ttl, fetcher) de tudo que precisa ser coletado."""
    jobs: list[tuple[str, int, callable]] = []

    for key in bcb.SERIES:
        jobs.append((f"bcb.{key}", settings.ttl_daily, lambda k=key: bcb.fetch_series(k)))

    jobs.append(
        ("ibge.ipca_hardware", settings.ttl_monthly, lambda: ibge.fetch_ipca_hardware())
    )

    if settings.enable_fred:
        for key in fred.SERIES:
            ttl = settings.ttl_monthly if key in _FRED_MONTHLY else settings.ttl_daily
            jobs.append((f"fred.{key}", ttl, lambda k=key: fred.fetch_series(k)))

    if settings.enable_markets:
        for key in markets.TICKERS:
            jobs.append(
                (f"market.{key}", settings.ttl_realtime, lambda k=key: markets.fetch_quote(k))
            )

    if settings.enable_gdelt:
        for key in gdelt.QUERIES:
            jobs.append(
                (f"gdelt.{key}", settings.ttl_realtime, lambda k=key: gdelt.fetch_tension(k))
            )
        jobs.append(
            ("gdelt.headlines", settings.ttl_realtime, lambda: gdelt.fetch_headlines())
        )

    if settings.enable_comtrade:
        for key in comtrade.COMMODITIES:
            jobs.append(
                (f"comtrade.{key}", settings.ttl_monthly, lambda k=key: comtrade.fetch_flow(k))
            )

    if settings.enable_comexstat:
        # Categorias podem compartilhar o mesmo SH6 (placa de vídeo e placa-mãe).
        seen: dict[str, str] = {}
        for cat in CATEGORIES:
            if cat.sh6 in seen:
                continue
            seen[cat.sh6] = cat.key
            jobs.append(
                (
                    f"comexstat.{cat.key}",
                    settings.ttl_monthly,
                    lambda c=cat: comexstat.fetch_imports(c.key, c.sh6, c.ncms, c.label),
                )
            )

    return jobs


async def collect(force: bool = False) -> dict[str, Fetched]:
    jobs = _tasks()
    results = await asyncio.gather(
        *(cache.get_or_fetch(key, ttl, fetcher, force=force) for key, ttl, fetcher in jobs),
        return_exceptions=True,
    )

    collected: dict[str, Fetched] = {}
    for (key, _, _), res in zip(jobs, results):
        if isinstance(res, BaseException):
            log.error("coleta '%s' levantou inesperadamente: %s", key, res)
            collected[key] = Fetched(
                key=key,
                label=key,
                provider="?",
                url="",
                status="unavailable",
                error=f"{type(res).__name__}: {res}",
            )
        else:
            collected[key] = res

    # Categorias que dividem SH6 herdam a mesma coleta do Comex Stat.
    if settings.enable_comexstat:
        by_sh6: dict[str, Fetched] = {}
        for cat in CATEGORIES:
            got = collected.get(f"comexstat.{cat.key}")
            if got is not None and got.ok:
                by_sh6.setdefault(cat.sh6, got)
        for cat in CATEGORIES:
            slot = f"comexstat.{cat.key}"
            if slot not in collected or not collected[slot].ok:
                shared = by_sh6.get(cat.sh6)
                if shared is not None:
                    collected[slot] = shared

    return collected


def build_snapshot(collected: dict[str, Fetched]) -> Snapshot:
    drivers = build_drivers(collected)
    brazil = build_brazil(collected)
    summary = build_summary(drivers, brazil)
    ranking = build_ranking(drivers, brazil, collected)

    sources = sorted(
        (f.to_source_info() for f in collected.values()),
        key=lambda s: (s.status != "ok", s.provider, s.label),
    )
    degraded = [
        f"{f.label or key} ({f.status})"
        for key, f in sorted(collected.items())
        if f.status in ("stale", "unavailable")
    ]

    headlines_f = collected.get("gdelt.headlines")
    headlines = headlines_f.payload if headlines_f and headlines_f.ok else []

    now = datetime.now(timezone.utc)
    return Snapshot(
        generated_at=now,
        next_refresh_at=now + timedelta(seconds=settings.refresh_seconds),
        refresh_seconds=settings.refresh_seconds,
        summary=summary,
        drivers=drivers,
        brazil=brazil,
        ranking=ranking,
        sources=sources,
        degraded=degraded,
        headlines=headlines or [],
        disclaimer=DISCLAIMER,
    )


async def get_snapshot(force: bool = False) -> Snapshot:
    collected = await collect(force=force)
    return build_snapshot(collected)
