"""Cotações de mercado quase em tempo real (Yahoo Finance, com Stooq de reserva).

Nenhuma das duas exige chave. Yahoo entrega intradiário; Stooq entrega
fechamento diário e serve de rede de segurança quando o Yahoo bloqueia.

Estes tickers são *proxies* dos vetores geopolíticos:
  SOXX/NVDA  -> demanda de datacenter por microchips
  MU         -> ciclo de memória DRAM/NAND
  REMX       -> terras raras e ímãs permanentes
  BZ=F       -> energia / risco no Estreito de Ormuz
  HG=F, ALI=F-> metais industriais em placas e dissipadores
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from ..cache import Fetched
from ..http import get_json, get_text
from ..series_utils import Point

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
STOOQ = "https://stooq.com/q/d/l/"

# chave -> (ticker yahoo, ticker stooq, rótulo, unidade)
TICKERS: dict[str, tuple[str, str, str, str]] = {
    "soxx": ("SOXX", "soxx.us", "iShares Semiconductor ETF (SOXX)", "US$"),
    "nvda": ("NVDA", "nvda.us", "NVIDIA (NVDA) — demanda de GPU/datacenter", "US$"),
    "micron": ("MU", "mu.us", "Micron (MU) — ciclo de memória DRAM/NAND", "US$"),
    "tsmc": ("TSM", "tsm.us", "TSMC (TSM) — capacidade de fundição", "US$"),
    "rare_earth": ("REMX", "remx.us", "VanEck Rare Earth & Strategic Metals (REMX)", "US$"),
    "brent": ("BZ=F", "cb.f", "Petróleo Brent futuro (BZ=F)", "US$/bbl"),
    "copper": ("HG=F", "hg.f", "Cobre futuro (HG=F)", "US$/lb"),
    "usd_brl": ("BRL=X", "usdbrl", "Dólar/Real spot (BRL=X)", "R$/US$"),
}


def _parse_yahoo(data: dict) -> tuple[list[Point], float | None]:
    chart = (data or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"Yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo: result vazio")
    res = results[0]
    stamps = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    points: list[Point] = []
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        points.append((d.isoformat(), float(close)))
    points.sort(key=lambda p: p[0])
    spot = (res.get("meta") or {}).get("regularMarketPrice")
    return points, float(spot) if spot is not None else None


def _parse_stooq(text: str) -> list[Point]:
    if text.lstrip().startswith("<"):
        raise ValueError("Stooq: resposta HTML (desafio anti-bot)")
    reader = csv.DictReader(io.StringIO(text))
    points: list[Point] = []
    for row in reader:
        raw_d, raw_c = row.get("Date"), row.get("Close")
        if not raw_d or not raw_c or raw_c in ("N/D", ""):
            continue
        try:
            points.append((datetime.strptime(raw_d, "%Y-%m-%d").date().isoformat(), float(raw_c)))
        except ValueError:
            continue
    points.sort(key=lambda p: p[0])
    return points


async def fetch_quote(key: str, range_: str = "1y") -> Fetched:
    y_sym, s_sym, label, unit = TICKERS[key]
    yahoo_url = YAHOO.format(symbol=y_sym)
    source_url = f"https://finance.yahoo.com/quote/{y_sym}"
    provider = "Yahoo Finance (chart v8)"
    note: str | None = None

    try:
        raw = await get_json(yahoo_url, params={"range": range_, "interval": "1d"})
        points, spot = _parse_yahoo(raw)
    except Exception as yahoo_exc:  # noqa: BLE001 — cai para o Stooq
        try:
            text = await get_text(STOOQ, params={"s": s_sym, "i": "d"})
            points, spot = _parse_stooq(text), None
            provider = "Stooq (CSV diário)"
            source_url = f"https://stooq.com/q/?s={s_sym}"
            note = f"fallback Stooq; Yahoo indisponível ({type(yahoo_exc).__name__})"
        except Exception as stooq_exc:  # noqa: BLE001
            raise ValueError(
                f"Yahoo e Stooq falharam para {key}: {yahoo_exc} | {stooq_exc}"
            ) from stooq_exc

    if not points:
        raise ValueError(f"{key}: série de cotação vazia")

    as_of = datetime.fromisoformat(points[-1][0]).replace(tzinfo=timezone.utc)
    return Fetched(
        key=f"market.{key}",
        label=label,
        provider=provider,
        url=source_url,
        status="ok",
        payload={"points": points, "spot": spot, "unit": unit, "symbol": y_sym},
        as_of=as_of,
        note=note,
    )
