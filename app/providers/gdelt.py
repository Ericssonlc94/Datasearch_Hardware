"""GDELT DOC 2.0 API — intensidade de cobertura noticiosa geopolítica.

API pública sem chave, monitorando notícias globais em ~100 idiomas.
Usamos `timelinevolraw` (contagem bruta + total monitorado) para medir se um
tema geopolítico está esquentando em relação à sua própria linha de base.

    https://api.gdeltproject.org/api/v2/doc/doc
        ?query=...&mode=timelinevolraw&format=json&timespan=3m

Isso não é "preço" — é medida de atenção/tensão, que usamos como sinal
antecedente dos choques de oferta que depois aparecem nos preços.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..cache import Fetched
from ..http import breaker_guard, breaker_record, get_json, limiter
from ..series_utils import Point

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# O GDELT limita por taxa, não por concorrência: as 7 consultas precisam sair
# uma de cada vez e bem espaçadas, senão parte delas volta 429.
_CONCURRENCY = 1
_SPACING_S = 2.5

# chave -> (query booleana GDELT, rótulo)
QUERIES: dict[str, tuple[str, str]] = {
    "hormuz": (
        '("Strait of Hormuz" OR "Estreito de Ormuz") (shipping OR tanker OR blockade OR closure OR military)',
        "Tensão no Estreito de Ormuz",
    ),
    "helium": (
        '("helium shortage" OR "helium supply" OR "escassez de helio") (semiconductor OR chip OR fab OR industrial)',
        "Escassez de hélio para fabricação de chips",
    ),
    "rare_earth": (
        '("rare earth" OR "rare earths" OR "terras raras") (export OR controls OR restriction OR quota OR ban)',
        "Controles de exportação de terras raras",
    ),
    "chip_demand": (
        '(semiconductor OR chip OR GPU OR "memory chip" OR DRAM) ("data center" OR datacenter OR "AI demand" OR shortage)',
        "Demanda de datacenter e IA por microchips",
    ),
    "trade_tariff": (
        '(tariff OR "export control" OR "trade restriction") (semiconductor OR electronics OR chip OR computer)',
        "Tarifas e controles no comércio de eletrônicos",
    ),
    "shipping": (
        '(shipping OR freight OR "container rates" OR "Red Sea") (disruption OR surge OR delay OR crisis)',
        "Ruptura em frete e logística marítima",
    ),
}


def _parse_timeline(data: dict) -> tuple[list[Point], list[Point]]:
    """Devolve (série de contagem bruta, série normalizada por 10k artigos)."""
    timeline = (data or {}).get("timeline") or []
    if not timeline:
        raise ValueError("GDELT: timeline vazia")
    entries = timeline[0].get("data") or []
    raw: list[Point] = []
    norm: list[Point] = []
    for item in entries:
        date_s = item.get("date")
        value = item.get("value")
        if date_s is None or value is None:
            continue
        # Formatos vistos: "20260801T000000Z" e "2026-08-01T00:00:00Z".
        try:
            clean = date_s.replace("-", "").replace(":", "")
            d = datetime.strptime(clean[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        raw.append((d, float(value)))
        total = item.get("norm") or 0
        if total:
            norm.append((d, float(value) / float(total) * 10_000.0))
    raw.sort(key=lambda p: p[0])
    norm.sort(key=lambda p: p[0])
    return raw, norm


async def fetch_tension(key: str, timespan: str = "6m") -> Fetched:
    query, label = QUERIES[key]
    params = {
        "query": query,
        "mode": "timelinevolraw",
        "format": "json",
        "timespan": timespan,
    }
    async with limiter("gdelt", _CONCURRENCY):
        breaker_guard("gdelt")
        try:
            data = await get_json(BASE, params=params)
        except Exception:
            breaker_record("gdelt", ok=False, threshold=4, cooldown=600.0)
            raise
        breaker_record("gdelt", ok=True)
        await asyncio.sleep(_SPACING_S)
    raw, norm = _parse_timeline(data)
    points = norm or raw
    if not points:
        raise ValueError(f"GDELT {key}: série vazia")

    as_of = datetime.fromisoformat(points[-1][0]).replace(tzinfo=timezone.utc)
    return Fetched(
        key=f"gdelt.{key}",
        label=f"GDELT — {label}",
        provider="The GDELT Project (DOC 2.0 API)",
        url=f"{BASE}?query={query}&mode=timelinevolraw&format=json&timespan={timespan}",
        status="ok",
        payload={"points": points, "raw": raw, "query": query, "label": label},
        as_of=as_of,
        note="Volume de cobertura noticiosa normalizado por 10 mil artigos monitorados.",
    )


async def fetch_headlines(limit: int = 12) -> Fetched:
    """Manchetes recentes que sustentam a leitura dos drivers."""
    query = (
        '("Strait of Hormuz" OR "rare earth" OR "helium shortage" OR '
        '"chip shortage" OR "memory prices" OR "GPU prices") '
        "(price OR supply OR shortage OR export OR tariff)"
    )
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": "7d",
        "maxrecords": str(limit),
        "sort": "datedesc",
    }
    async with limiter("gdelt", _CONCURRENCY):
        breaker_guard("gdelt")
        try:
            data = await get_json(BASE, params=params)
        except Exception:
            breaker_record("gdelt", ok=False, threshold=4, cooldown=600.0)
            raise
        breaker_record("gdelt", ok=True)
        await asyncio.sleep(_SPACING_S)
    articles = (data or {}).get("articles") or []
    out = []
    for art in articles[:limit]:
        seen = art.get("seendate") or ""
        try:
            when = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            when = None
        out.append(
            {
                "title": art.get("title"),
                "url": art.get("url"),
                "domain": art.get("domain"),
                "country": art.get("sourcecountry"),
                "language": art.get("language"),
                "seen_at": when.isoformat() if when else None,
            }
        )
    if not out:
        raise ValueError("GDELT: nenhuma manchete retornada")

    return Fetched(
        key="gdelt.headlines",
        label="Manchetes globais sobre oferta e preço de hardware",
        provider="The GDELT Project (DOC 2.0 API)",
        url=f"{BASE}?query={query}&mode=artlist&format=json&timespan=7d",
        status="ok",
        payload=out,
        as_of=datetime.now(timezone.utc),
    )
