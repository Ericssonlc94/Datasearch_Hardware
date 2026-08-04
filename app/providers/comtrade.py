"""UN Comtrade — endpoint público de preview (sem chave).

    https://comtradeapi.un.org/public/v1/preview/C/A/HS
        ?reporterCode=76&period=2024&partnerCode=0&cmdCode=854232&flowCode=M

Restrição confirmada ao vivo: o preview aceita **um único período por
chamada** ("Maximum number of periods for preview is 1") e devolve 429 para
rajadas paralelas. Por isso montamos a série ano a ano, em fila.

Serve para ancorar as teses em fluxo físico de comércio, não só em preço:
  280429 -> outros gases raros (inclui hélio) — a tese do Estreito de Ormuz
  280530 -> compostos de terras raras
  854232 -> memórias (DRAM/NAND)
  854231 -> processadores e controladores
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..cache import Fetched
from ..http import get_json, limiter
from ..series_utils import Point

BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

BRAZIL = "76"
WORLD_PARTNER = "0"

# O preview é rigoroso com taxa: uma requisição por vez, com respiro entre elas.
_CONCURRENCY = 1
_SPACING_S = 0.35

# chave -> (código HS, rótulo)
COMMODITIES: dict[str, tuple[str, str]] = {
    "helium": ("280429", "Gases raros, inclui hélio — HS 280429"),
    "rare_earth": ("280530", "Metais de terras raras — HS 280530"),
    "memory": ("854232", "Memórias eletrônicas — HS 854232"),
    "processors": ("854231", "Processadores e controladores — HS 854231"),
}


async def _fetch_year(hs_code: str, reporter: str, year: int) -> list[dict]:
    params = {
        "reporterCode": reporter,
        "period": str(year),
        "partnerCode": WORLD_PARTNER,
        "cmdCode": hs_code,
        "flowCode": "M",  # M = importações
    }
    async with limiter("comtrade", _CONCURRENCY):
        data = await get_json(BASE, params=params)
        await asyncio.sleep(_SPACING_S)
    return (data or {}).get("data") or []


def _aggregate(rows: list[dict]) -> tuple[float, float]:
    """Soma valor e peso do ano (o preview pode devolver várias linhas)."""
    value = weight = 0.0
    for row in rows:
        try:
            value += float(row.get("primaryValue") or 0)
            weight += float(row.get("netWgt") or 0)
        except (TypeError, ValueError):
            continue
    return value, weight


async def fetch_flow(key: str, reporter: str = BRAZIL, years: int = 4) -> Fetched:
    hs_code, label = COMMODITIES[key]
    # O ano corrente ainda não fechou; começamos pelo último ano completo.
    last_full = datetime.now(timezone.utc).year - 1
    wanted = list(range(last_full - years + 1, last_full + 1))

    unit_values: list[Point] = []
    totals: list[Point] = []
    errors: list[str] = []

    for year in wanted:
        try:
            rows = await _fetch_year(hs_code, reporter, year)
        except Exception as exc:  # noqa: BLE001 — um ano faltando não invalida a série
            errors.append(f"{year}: {type(exc).__name__}")
            continue
        if not rows:
            continue
        value, weight = _aggregate(rows)
        if value > 0:
            totals.append((str(year), value))
        if value > 0 and weight > 0:
            unit_values.append((str(year), value / weight))

    if not totals and not unit_values:
        raise ValueError(
            f"Comtrade HS {hs_code}: nenhum ano retornou dados"
            + (f" ({'; '.join(errors)})" if errors else "")
        )

    as_of = datetime(int(totals[-1][0]), 12, 31, tzinfo=timezone.utc) if totals else None
    note = "Endpoint preview: 1 período por chamada, dado anual."
    if errors:
        note += f" Anos sem retorno: {', '.join(errors)}."

    return Fetched(
        key=f"comtrade.{key}",
        label=f"UN Comtrade — {label} (importações, reporter {reporter})",
        provider="United Nations Comtrade (preview público)",
        url=f"{BASE}?reporterCode={reporter}&cmdCode={hs_code}&flowCode=M&partnerCode=0",
        status="ok",
        payload={"unit_values": unit_values, "totals": totals, "hs_code": hs_code},
        as_of=as_of,
        note=note,
    )
