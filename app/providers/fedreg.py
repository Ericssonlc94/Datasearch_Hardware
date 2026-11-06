"""Federal Register — regras de controle de exportação de chips (BIS).

API pública do diário oficial dos EUA, sem chave:

    https://www.federalregister.gov/api/v1/documents.json
        ?conditions[agencies][]=industry-and-security-bureau
        &conditions[type][]=RULE

O BIS (Bureau of Industry and Security) publica ali cada inclusão na Entity
List e cada regra sobre chips avançados e China. É o ato oficial, com data —
não a cobertura jornalística dele.

A série é diária: soma líquida das regras relevantes publicadas no dia, com
sentido lido no título — aperto +1 (adição, revogação, restrição), revisão
+0,5 (revisão da Entity List costuma acrescentar nomes), alívio −1 (remoção,
extensão, tratamento favorável). Dia sem regra vale 0.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from ..cache import Fetched
from ..http import get_json
from ..series_utils import Point

BASE = "https://www.federalregister.gov/api/v1/documents.json"
AGENCY = "industry-and-security-bureau"
HISTORY_DAYS = 450

# Regra entra só se o título falar de chips, China ou Entity List. Regras do
# BIS sobre outros temas (armas, aviação, Rússia sem chips) ficam de fora.
_RELEVANT = re.compile(
    r"entity list|semiconductor|advanced computing|integrated circuit|"
    r"supercomput|lithograph|foreign direct product|people's republic of china|"
    r"\bchina\b|\bprc\b|\bic\b",
    re.IGNORECASE,
)
_EASE = re.compile(
    r"\bremovals?\b|\bremoves?\b|\bextension\b|favorable|\bexclusions?\b|"
    r"\brescission\b|\brelief\b|\bsuspension\b",
    re.IGNORECASE,
)
_TIGHTEN = re.compile(
    r"\badditions?\b|\brevocation\b|\brestrictions?\b|\bimposition\b|"
    r"\bexpansion\b|\bcontrols on\b|\bnew controls\b",
    re.IGNORECASE,
)


def rule_direction(title: str) -> float | None:
    """+1 aperto, +0,5 revisão, −1 alívio; `None` quando a regra não é sobre chips."""
    if not _RELEVANT.search(title or ""):
        return None
    if _TIGHTEN.search(title):
        return 1.0
    if _EASE.search(title):
        return -1.0
    return 0.5


def daily_net_series(rules: list[dict], start: date, end: date) -> list[Point]:
    """Soma diária do sentido das regras relevantes (0 em dia sem regra)."""
    by_day: dict[str, float] = {}
    for rule in rules:
        by_day[rule["date"]] = by_day.get(rule["date"], 0.0) + rule["direction"]
    out: list[Point] = []
    day = start
    while day <= end:
        key = day.isoformat()
        out.append((key, by_day.get(key, 0.0)))
        day += timedelta(days=1)
    return out


async def fetch_bis_chip_rules() -> Fetched:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=HISTORY_DAYS)
    data = await get_json(
        BASE,
        params={
            "conditions[agencies][]": AGENCY,
            "conditions[type][]": "RULE",
            "conditions[publication_date][gte]": start.isoformat(),
            "per_page": "500",
            "order": "newest",
            "fields[]": ["title", "publication_date", "html_url"],
        },
    )
    results = (data or {}).get("results")
    if results is None:
        raise ValueError("Federal Register: resposta sem 'results'")

    rules: list[dict] = []
    for doc in results:
        direction = rule_direction(doc.get("title") or "")
        when = (doc.get("publication_date") or "")[:10]
        if direction is None or not when:
            continue
        rules.append(
            {
                "date": when,
                "title": doc.get("title"),
                "url": doc.get("html_url"),
                "direction": direction,
            }
        )

    points = daily_net_series(rules, start, end)
    tighten = sum(1 for r in rules if r["direction"] > 0)
    ease = sum(1 for r in rules if r["direction"] < 0)
    return Fetched(
        key="fedreg.bis_chip_rules",
        label="Federal Register — regras do BIS sobre chips, China e Entity List",
        provider="Federal Register (API pública do governo dos EUA)",
        url="https://www.federalregister.gov/agencies/industry-and-security-bureau",
        status="ok",
        payload={"points": points, "rules": rules[:20]},
        as_of=datetime.now(timezone.utc),
        note=(
            f"{len(rules)} regra(s) relevante(s) em {HISTORY_DAYS} dias "
            f"({tighten} de aperto ou revisão, {ease} de alívio), de "
            f"{len(results)} regra(s) do BIS no período."
        ),
    )
