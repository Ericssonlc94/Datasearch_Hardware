"""Banco Central do Brasil — Sistema Gerenciador de Séries Temporais (SGS).

API pública, sem chave. Verificada em 2026-08-04.
    https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json
Resposta: [{"data": "30/07/2026", "valor": "5.0739"}, ...]
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..cache import Fetched
from ..http import get_json
from ..series_utils import Point

BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"

# codigo SGS -> (chave interna, rotulo, frequencia)
SERIES: dict[str, tuple[int, str, str]] = {
    "ptax_usd": (1, "Dólar PTAX venda (R$/US$)", "diaria"),
    "ipca": (433, "IPCA — variação mensal (%)", "mensal"),
    "selic_meta": (432, "Selic meta (% a.a.)", "diaria"),
    "igpm": (189, "IGP-M — variação mensal (%)", "mensal"),
}


def _parse(rows: list[dict]) -> list[Point]:
    out: list[Point] = []
    for row in rows:
        raw_d, raw_v = row.get("data"), row.get("valor")
        if not raw_d or raw_v in (None, ""):
            continue
        try:
            d = datetime.strptime(raw_d, "%d/%m/%Y").date()
            out.append((d.isoformat(), float(str(raw_v).replace(",", "."))))
        except (ValueError, TypeError):
            continue
    out.sort(key=lambda p: p[0])
    return out


async def fetch_series(key: str, years_back: int = 3) -> Fetched:
    code, label, freq = SERIES[key]
    start = (date.today() - timedelta(days=365 * years_back)).strftime("%d/%m/%Y")
    url = BASE.format(code=code)
    params = {"formato": "json", "dataInicial": start}
    rows = await get_json(url, params=params)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"SGS {code} devolveu payload vazio")
    points = _parse(rows)
    if not points:
        raise ValueError(f"SGS {code}: nenhuma observação parseável")

    as_of = datetime.fromisoformat(points[-1][0]).replace(tzinfo=timezone.utc)
    return Fetched(
        key=f"bcb.{key}",
        label=f"BCB/SGS {code} — {label}",
        provider="Banco Central do Brasil (SGS)",
        url=f"{url}?formato=json",
        status="ok",
        payload={"points": points, "frequency": freq, "sgs_code": code},
        as_of=as_of,
    )
