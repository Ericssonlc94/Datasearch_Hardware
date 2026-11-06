"""Cotações de mercado quase em tempo real (Yahoo Finance chart v8).

Nenhuma chave de API. O Yahoo entrega histórico diário e o preço spot; é fonte
única desde que o Stooq foi removido — ele passou a devolver uma página de
desafio JavaScript (*"This site requires JavaScript to verify your browser"*),
o que viola a política de fontes do projeto. Em falha, o cache serve `stale`.

Estes tickers são *proxies* dos vetores geopolíticos:
  SOXX/NVDA  -> demanda de datacenter por microchips
  MU         -> ciclo de memória DRAM/NAND
  REMX       -> terras raras e ímãs permanentes
  BZ=F       -> energia / risco no Estreito de Ormuz
  HG=F       -> metais industriais em placas e dissipadores
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..cache import Fetched
from ..http import get_json
from ..series_utils import Point

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# chave -> (ticker yahoo, rótulo, unidade)
TICKERS: dict[str, tuple[str, str, str]] = {
    "soxx": ("SOXX", "iShares Semiconductor ETF (SOXX)", "US$"),
    "nvda": ("NVDA", "NVIDIA (NVDA) — demanda de GPU/datacenter", "US$"),
    "micron": ("MU", "Micron (MU) — ciclo de memória DRAM/NAND", "US$"),
    "tsmc": ("TSM", "TSMC (TSM) — capacidade de fundição", "US$"),
    "rare_earth": ("REMX", "VanEck Rare Earth & Strategic Metals (REMX)", "US$"),
    "brent": ("BZ=F", "Petróleo Brent futuro (BZ=F)", "US$/bbl"),
    "copper": ("HG=F", "Cobre futuro (HG=F)", "US$/lb"),
    "usd_brl": ("BRL=X", "Dólar/Real spot (BRL=X)", "R$/US$"),
    # Risco Taiwan medido no mercado: bolsa local e moeda. Fuga de capital
    # aparece aqui antes de qualquer interrupção física.
    "taiwan_index": ("^TWII", "Bolsa de Taiwan (TAIEX, ^TWII)", "pontos"),
    "usd_twd": ("TWD=X", "Dólar/novo dólar taiwanês (TWD=X)", "TWD/US$"),
    # Só para explicar o dólar (não entram no índice): dólar no mundo, pares
    # emergentes do real e medo global.
    "dxy": ("DX-Y.NYB", "Índice do dólar contra moedas fortes (DXY)", "pontos"),
    "usd_mxn": ("MXN=X", "Dólar/peso mexicano (MXN=X)", "MXN/US$"),
    "usd_clp": ("CLP=X", "Dólar/peso chileno (CLP=X)", "CLP/US$"),
    "usd_zar": ("ZAR=X", "Dólar/rand sul-africano (ZAR=X)", "ZAR/US$"),
    "usd_cop": ("COP=X", "Dólar/peso colombiano (COP=X)", "COP/US$"),
    "vix": ("^VIX", "Índice de volatilidade (VIX) — medo global", "pontos"),
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


async def fetch_quote(key: str, range_: str = "1y") -> Fetched:
    y_sym, label, unit = TICKERS[key]
    raw = await get_json(
        YAHOO.format(symbol=y_sym),
        params={"range": range_, "interval": "1d"},
    )
    points, spot = _parse_yahoo(raw)
    if not points:
        raise ValueError(f"{key}: série de cotação vazia")

    as_of = datetime.fromisoformat(points[-1][0]).replace(tzinfo=timezone.utc)
    return Fetched(
        key=f"market.{key}",
        label=label,
        provider="Yahoo Finance (chart v8)",
        url=f"https://finance.yahoo.com/quote/{y_sym}",
        status="ok",
        payload={"points": points, "spot": spot, "unit": unit, "symbol": y_sym},
        as_of=as_of,
    )
