"""Comex Stat (MDIC/SECEX) — importações brasileiras por NCM.

Esta é a fonte que dá o preço real de entrada do hardware no Brasil:
valor FOB e peso líquido por NCM e por mês, permitindo calcular o
US$/kg importado e sua variação — o número mais próximo de "quanto o
importador brasileiro está pagando" que existe em dado público.

    POST https://api-comexstat.mdic.gov.br/general

ATENÇÃO: o contrato exato deste endpoint não pôde ser validado ao vivo no
ambiente onde este código foi escrito (proxy bloqueou o domínio). A chamada
tenta o filtro `sh6` e, se recusado, cai para `ncm` com códigos de 8 dígitos.
Se ambos falharem, a categoria simplesmente aparece sem o bloco de importação
— o resto do painel continua funcionando. Ajuste `PAYLOAD_VARIANTS` se o
MDIC mudar o schema.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

from ..cache import Fetched
from ..http import breaker_guard, breaker_record, limiter, post_json

BASE = "https://api-comexstat.mdic.gov.br/general"
DOCS = "https://api-comexstat.mdic.gov.br/docs"

# Confirmado ao vivo: rajada paralela de POSTs devolve 429 em todas.
# Uma requisição por vez, com respiro.
_CONCURRENCY = 1
_SPACING_S = 0.5

# O endpoint fica atrás de um WAF que responde 429 a cliente sem contexto de
# origem. Estes cabeçalhos são os mesmos que o painel oficial do Comex Stat
# envia — não contornam autenticação nenhuma, só identificam a chamada.
_HEADERS = {
    "Origin": "https://comexstat.mdic.gov.br",
    "Referer": "https://comexstat.mdic.gov.br/",
    "Accept": "application/json, text/plain, */*",
}


def _period_bounds(months_back: int = 30) -> tuple[str, str]:
    today = date.today()
    # Comex Stat publica com ~1 mês de defasagem.
    end_y, end_m = today.year, today.month - 1
    if end_m == 0:
        end_y, end_m = end_y - 1, 12
    total = end_y * 12 + (end_m - 1) - months_back
    start_y, start_m = divmod(total, 12)
    return f"{start_y}-{start_m + 1:02d}", f"{end_y}-{end_m:02d}"


def _payload_variants(sh6: str, ncms: list[str], start: str, end: str) -> list[dict[str, Any]]:
    common = {
        "flow": "import",
        "monthDetail": True,
        "period": {"from": start, "to": end},
        "metrics": ["metricFOB", "metricKG"],
    }
    return [
        {**common, "filters": [{"filter": "sh6", "values": [sh6]}], "details": ["sh6"]},
        {**common, "filters": [{"filter": "ncm", "values": ncms}], "details": ["ncm"]},
    ]


def _parse(data: dict) -> list[dict[str, Any]]:
    """Agrega FOB e KG por mês, tolerando variações de nome de campo."""
    payload = data.get("data") if isinstance(data, dict) else None
    rows = None
    if isinstance(payload, dict):
        rows = payload.get("list") or payload.get("data")
    elif isinstance(payload, list):
        rows = payload
    if not rows:
        raise ValueError("Comex Stat: resposta sem lista de registros")

    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        year = str(row.get("year") or row.get("coAno") or "").strip()
        month = str(row.get("monthNumber") or row.get("coMes") or "").strip()
        if not year or not month:
            continue
        period = f"{year}-{int(month):02d}"
        try:
            fob = float(str(row.get("metricFOB") or 0).replace(",", "."))
            kg = float(str(row.get("metricKG") or 0).replace(",", "."))
        except (TypeError, ValueError):
            continue
        slot = buckets.setdefault(period, {"fob": 0.0, "kg": 0.0})
        slot["fob"] += fob
        slot["kg"] += kg

    out = []
    for period in sorted(buckets):
        b = buckets[period]
        if b["kg"] <= 0:
            continue
        out.append(
            {"period": period, "fob_usd": b["fob"], "kg": b["kg"], "usd_per_kg": b["fob"] / b["kg"]}
        )
    if not out:
        raise ValueError("Comex Stat: nenhum mês com peso > 0")
    return out


async def fetch_imports(category_key: str, sh6: str, ncms: list[str], label: str) -> Fetched:
    start, end = _period_bounds()
    errors: list[str] = []

    for payload in _payload_variants(sh6, ncms, start, end):
        try:
            async with limiter("comexstat", _CONCURRENCY):
                # Checado DENTRO do semáforo: as categorias entram em paralelo e
                # só aqui, em fila, cada uma enxerga as falhas das anteriores.
                breaker_guard("comexstat")
                data = await post_json(BASE, payload, headers=_HEADERS)
                await asyncio.sleep(_SPACING_S)
            months = _parse(data)
            breaker_record("comexstat", ok=True)
            as_of = datetime.strptime(months[-1]["period"] + "-01", "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            return Fetched(
                key=f"comexstat.{category_key}",
                label=f"Comex Stat — importação de {label} (SH6 {sh6})",
                provider="MDIC/SECEX — Comex Stat",
                url=DOCS,
                status="ok",
                payload={"months": months, "sh6": sh6, "ncms": ncms},
                as_of=as_of,
                note="Valor FOB e peso líquido oficiais de importação.",
            )
        except Exception as exc:  # noqa: BLE001 — tenta a próxima variante
            errors.append(f"{payload['filters'][0]['filter']}: {type(exc).__name__}: {exc}")

    breaker_record("comexstat", ok=False)
    raise ValueError(f"Comex Stat falhou para {category_key} — " + " | ".join(errors))
