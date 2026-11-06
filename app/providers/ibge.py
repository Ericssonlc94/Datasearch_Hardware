"""IBGE / SIDRA — IPCA por subitem (agregado 7060).

É aqui que mora o dado real de preço ao consumidor brasileiro para hardware:
o agregado 7060 abre o IPCA até subitem, incluindo "Computador pessoal",
"Aparelho telefônico", "Videogame (console)" e "Televisor".

Verificado em 2026-08-04:
  GET /api/v3/agregados/7060/periodos/-N/variaveis/63|2265
      ?localidades=N1[all]&classificacao=315[47641,7794,...]
  Variáveis: 63 = variação mensal, 2265 = acumulada 12 meses, 66 = peso.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..cache import Fetched
from ..http import get_json

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados/7060"

VAR_MENSAL = "63"
VAR_12M = "2265"

# Códigos da classificação 315 confirmados contra /metadados.
SUBITENS: dict[str, str] = {
    "47641": "Computador pessoal",
    "7794": "Aparelho telefônico",
    "47640": "Videogame (console)",
    "7542": "Televisor",
    "7541": "Tv, som e informática (grupo)",
    "7521": "Aparelhos eletroeletrônicos (grupo)",
}


def _period_to_iso(period: str) -> str:
    """202606 -> 2026-06"""
    return f"{period[:4]}-{period[4:6]}" if len(period) == 6 else period


def _extract(raw: list[dict]) -> dict[str, dict]:
    """Reorganiza a resposta do SIDRA em {codigo_subitem: {...}}."""
    out: dict[str, dict] = {}
    for var_block in raw:
        var_id = str(var_block.get("id"))
        for res in var_block.get("resultados", []):
            classif = res.get("classificacoes") or []
            if not classif:
                continue
            categoria = classif[0].get("categoria") or {}
            for code, nome in categoria.items():
                for serie_block in res.get("series", []):
                    serie = serie_block.get("serie") or {}
                    points: list[tuple[str, float]] = []
                    for period, val in serie.items():
                        if val in (None, "", "...", "-", ".."):
                            continue
                        try:
                            points.append((_period_to_iso(period), float(val)))
                        except (TypeError, ValueError):
                            continue
                    points.sort(key=lambda p: p[0])
                    if not points:
                        continue
                    slot = out.setdefault(
                        code, {"label": nome.split(".", 1)[-1].strip()}
                    )
                    if var_id == VAR_MENSAL:
                        slot["monthly"] = points
                    elif var_id == VAR_12M:
                        slot["yoy"] = points
    return out


async def fetch_ipca_hardware(periods: int = 24) -> Fetched:
    codes = ",".join(SUBITENS)
    url = (
        f"{BASE}/periodos/-{periods}/variaveis/{VAR_MENSAL}|{VAR_12M}"
        f"?localidades=N1[all]&classificacao=315[{codes}]"
    )
    raw = await get_json(url)
    if not isinstance(raw, list) or not raw:
        raise ValueError("SIDRA 7060 devolveu payload vazio")

    data = _extract(raw)
    if not data:
        raise ValueError("SIDRA 7060: nenhum subitem parseável")

    # Data de referência = último período disponível em qualquer subitem.
    last_period = max(
        (pts[-1][0] for slot in data.values() for pts in (slot.get("monthly") or [],) if pts),
        default=None,
    )
    as_of = (
        datetime.strptime(last_period + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if last_period
        else None
    )

    return Fetched(
        key="ibge.ipca_hardware",
        label="IPCA por subitem — eletrônicos e informática (IBGE/SIDRA 7060)",
        provider="IBGE — Sistema IBGE de Recuperação Automática (SIDRA)",
        url=url,
        status="ok",
        payload=data,
        as_of=as_of,
        note="Preço ao consumidor brasileiro, dado oficial mensal.",
    )
