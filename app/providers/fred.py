"""FRED (Federal Reserve Bank of St. Louis) via download CSV público.

O endpoint `fredgraph.csv` não exige chave de API — é o mesmo arquivo que o
botão "Download" do site entrega. Isso nos dá índices de preço ao produtor de
semicondutores, índices de preço de importação e commodities sem cadastro.

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID

CSV: `observation_date,SERIES_ID` (valores ausentes vêm como ".").
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from ..cache import Fetched
from ..http import get_text
from ..series_utils import Point

BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# chave interna -> (series_id, rótulo, unidade, frequência)
SERIES: dict[str, tuple[str, str, str, str]] = {
    "ppi_semiconductors": (
        "PCU334413334413",
        "PPI EUA — fabricação de semicondutores e dispositivos",
        "índice",
        "mensal",
    ),
    "import_px_semis": (
        "IZ3344",
        "Índice de preço de importação EUA — semicondutores e componentes",
        "índice",
        "mensal",
    ),
    "brent": (
        "DCOILBRENTEU",
        "Petróleo Brent (US$/barril)",
        "US$/bbl",
        "diaria",
    ),
    "copper": (
        "PCOPPUSDM",
        "Cobre — preço global (US$/tonelada)",
        "US$/t",
        "mensal",
    ),
    "aluminum": (
        "PALUMUSDM",
        "Alumínio — preço global (US$/tonelada)",
        "US$/t",
        "mensal",
    ),
    "natgas_eu": (
        "PNGASEUUSDM",
        "Gás natural Europa (US$/MMBtu) — proxy de hélio",
        "US$/MMBtu",
        "mensal",
    ),
    "usd_brl_fed": (
        "DEXBZUS",
        "Câmbio USD/BRL (Federal Reserve H.10)",
        "R$/US$",
        "diaria",
    ),
    "cpi_computers_us": (
        "CUSR0000SEEE01",
        "CPI EUA — computadores, periféricos e assistentes domésticos",
        "índice",
        "mensal",
    ),
    # Índices globais do FMI (PCPS) redistribuídos pelo FRED. O endpoint SDMX
    # próprio do FMI mudou de host e de estrutura de chaves em 2026 e passou a
    # devolver dataset vazio; o espelho do FRED entrega o mesmo dado sem chave.
    "global_metals": (
        "PMETAINDEXM",
        "Índice global de metais industriais (FMI/PCPS via FRED)",
        "índice",
        "mensal",
    ),
    "global_energy": (
        "PNRGINDEXM",
        "Índice global de energia (FMI/PCPS via FRED)",
        "índice",
        "mensal",
    ),
    "global_all": (
        "PALLFNFINDEXM",
        "Índice global de todas as commodities (FMI/PCPS via FRED)",
        "índice",
        "mensal",
    ),
}


def _parse_csv(text: str) -> list[Point]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    if len(header) < 2:
        return []
    out: list[Point] = []
    for row in reader:
        if len(row) < 2:
            continue
        raw_d, raw_v = row[0].strip(), row[1].strip()
        if raw_v in (".", "", "NA", "NaN"):
            continue
        try:
            d = datetime.strptime(raw_d, "%Y-%m-%d").date()
            out.append((d.isoformat(), float(raw_v)))
        except ValueError:
            continue
    out.sort(key=lambda p: p[0])
    return out


async def fetch_series(key: str) -> Fetched:
    series_id, label, unit, freq = SERIES[key]
    url = f"{BASE}?id={series_id}"
    text = await get_text(url)
    if text.lstrip().startswith("<"):
        raise ValueError(f"FRED {series_id}: resposta HTML (bloqueio ou série inválida)")
    points = _parse_csv(text)
    if not points:
        raise ValueError(f"FRED {series_id}: nenhuma observação parseável")

    as_of = datetime.fromisoformat(points[-1][0]).replace(tzinfo=timezone.utc)
    return Fetched(
        key=f"fred.{key}",
        label=f"FRED {series_id} — {label}",
        provider="Federal Reserve Bank of St. Louis (FRED)",
        url=f"https://fred.stlouisfed.org/series/{series_id}",
        status="ok",
        payload={"points": points, "unit": unit, "frequency": freq, "series_id": series_id},
        as_of=as_of,
    )
