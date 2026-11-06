"""Fila do consumidor: o quanto a demanda de datacenter está na frente do varejo.

Modelo explicitamente heurístico e exposto em `/api/methodology`:

    diversão  = z(crescimento do capex TTM) + z(crescimento da receita de chips)
    estoque   = −z(variação a/a do estoque/receita da Micron)
    fila      = 50 + 50·tanh(a·diversão + b·estoque)

O sinal de estoque é invertido de propósito: estoque caindo significa oferta
mais apertada para o consumidor, ou seja, fila maior. `a` e `b` ficam no topo
do módulo para poderem ser auditados e ajustados sem caçar número no código.

Os três termos estão na mesma unidade (desvios-padrão contra a própria
história). Até 04/11/2026 o estoque entrava como variação % bruta ÷ 10: uma
queda de 65% valia 6,5 unidades, somava ~2,3 ao argumento e prendia a fila em
100 (tanh ≈ 0,9997). Em z-score, a mesma queda vale ~1,25.

O que é observado: capex, receita, estoque e volume importado. O que é
modelado: `diversion_index` e `queue_pressure`. Lacuna nunca vira zero: o
campo fica `None` e a `coverage` cai.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..cache import Fetched
from ..schemas import SeriesPoint, SupplyContext
from ..series_utils import Point, clamp, to_points
from .supply_fronts import FRONTS_ENABLED, demand_queue

# Parâmetros da fila — expostos em /api/methodology.
# Peso de 0,25 por z-score: com os três componentes em +1 desvio a fila fica
# em ~82; em +2, ~95. O extremo de 2026 (capex +93% a/a, estoque −65% a/a)
# dá ~89 e ainda deixa espaço para subir ou cair.
QUEUE_A = 0.25
QUEUE_B = 0.25
INVENTORY_YOY_LAG = 4  # trimestres: compara com o mesmo trimestre do ano anterior

QUEUE_METHODOLOGY = {
    "a": QUEUE_A,
    "b": QUEUE_B,
    "inventory_yoy_lag_quarters": INVENTORY_YOY_LAG,
    "formula": (
        "50 + 50*tanh(a*diversion); "
        "diversion = z(capex_ttm_growth) + z(chip_revenue_growth). "
        "Estoque fora da fila desde 05/11/2026: vai para a frente memória "
        "(dias de estoque da Micron, supply_fronts)"
    ),
    "note": (
        "Fila 0-100; >50 significa que o consumidor doméstico espera mais. "
        "Os três termos são z-scores contra a própria história. Capex, receita, "
        "estoque e volume são observados; a fila é modelada. Valores gravados "
        "antes de 04/11/2026 usavam o estoque em % bruto, e os de antes de "
        "05/11/2026 somavam o estoque; nenhum dos dois é comparável."
    ),
}


def _points(payload: dict, key: str) -> list[Point]:
    out: list[Point] = []
    for item in (payload or {}).get(key) or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                out.append((str(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
    return out


def _values(points: list[Point]) -> list[float]:
    return [v for _, v in points if math.isfinite(v)]


def zscore(points: list[Point]) -> float | None:
    """Z-score do último valor contra a própria história.

    Com menos de 3 pontos ou desvio zero, devolve `None` em vez de inventar
    um extremo. O chamador decide se ainda dá para calcular a fila.
    """
    values = _values(points)
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(var)
    if std <= 1e-9:
        return None
    return (values[-1] - mean) / std


def inventory_yoy_changes(ratio_points: list[Point]) -> list[Point]:
    """Variação % a/a do estoque/receita, trimestre contra o mesmo do ano anterior."""
    out: list[Point] = []
    for i in range(INVENTORY_YOY_LAG, len(ratio_points)):
        before = ratio_points[i - INVENTORY_YOY_LAG][1]
        now = ratio_points[i][1]
        if before and math.isfinite(before) and math.isfinite(now):
            out.append((ratio_points[i][0], (now / before - 1.0) * 100.0))
    return out


def _queue_label(pressure: float) -> str:
    if pressure >= 75:
        return "Fila crítica para o consumidor"
    if pressure >= 62:
        return "Fila longa"
    if pressure >= 53:
        return "Fila apertando"
    if pressure >= 47:
        return "Fila equilibrada"
    if pressure >= 38:
        return "Fila folgada"
    return "Fila curta"


def _queue_note(
    capex_usd: float | None,
    capex_growth: float | None,
    inventory_ratio: float | None,
    inventory_change: float | None,
    diversion: float | None,
) -> str:
    parts: list[str] = []
    if capex_usd is not None:
        parts.append(f"Capex TTM de US$ {capex_usd / 1e9:.1f} bi")
        if capex_growth is not None:
            parts[-1] += f" ({capex_growth:+.1f}% a/a)"
    if inventory_ratio is not None:
        parts.append(f"estoque/receita da Micron em {inventory_ratio:.2f}")
        if inventory_change is not None:
            parts[-1] += f" ({inventory_change:+.1f}% a/a)"
    if diversion is not None:
        parts.append(f"índice de desvio {diversion:+.2f}")
    if not parts:
        return (
            "Sem capex, receita ou estoque da SEC nesta rodada. A fila fica "
            "indisponível — o modelo não preenche lacuna com estimativa."
        )
    text = "; ".join(parts) + "."
    text += (
        " Quanto mais o capex acelera e mais o estoque de memória cai, mais "
        "capacidade é desviada para IA e mais longe o consumidor doméstico "
        "fica do fim da fila."
    )
    return text


def build_supply(collected: dict[str, Fetched]) -> SupplyContext:
    capex_f = collected.get("sec.capex_hyperscaler")
    revenue_f = collected.get("sec.chip_revenue")
    inventory_f = collected.get("sec.memory_inventory")
    comtrade_f = collected.get("comtrade.memory")

    capex_payload = capex_f.payload if capex_f and capex_f.ok and isinstance(capex_f.payload, dict) else {}
    revenue_payload = revenue_f.payload if revenue_f and revenue_f.ok and isinstance(revenue_f.payload, dict) else {}
    inventory_payload = inventory_f.payload if inventory_f and inventory_f.ok and isinstance(inventory_f.payload, dict) else {}
    comtrade_payload = comtrade_f.payload if comtrade_f and comtrade_f.ok and isinstance(comtrade_f.payload, dict) else {}

    capex_growth_points = _points(capex_payload, "growth_points")
    revenue_growth_points = _points(revenue_payload, "growth_points")

    z_capex = zscore(capex_growth_points)
    z_revenue = zscore(revenue_growth_points)
    components = [z for z in (z_capex, z_revenue) if z is not None]
    diversion = sum(components) if components else None

    inventory_ratio = inventory_payload.get("ratio")
    inventory_change = inventory_payload.get("ratio_change_pct")
    # Estoque caindo (z negativo) aumenta a pressão. Sem história suficiente
    # para o z-score, o termo fica de fora em vez de virar zero inventado.
    z_inventory = zscore(inventory_yoy_changes(_points(inventory_payload, "ratio_points")))
    inventory_pressure = -z_inventory if z_inventory is not None else None

    queue: float | None = None
    if FRONTS_ENABLED:
        # §T24c: o estoque da Micron foi para a frente memória (cards de
        # `supply_fronts.build_fronts`); a fila fica só com a demanda.
        queue = demand_queue(z_capex, z_revenue, QUEUE_A)
        queue = round(clamp(queue), 1) if queue is not None else None
    elif diversion is not None:
        queue = 50.0 + 50.0 * math.tanh(
            QUEUE_A * diversion + QUEUE_B * (inventory_pressure or 0.0)
        )
        queue = round(clamp(queue), 1)

    comtrade_totals = _points(comtrade_payload, "totals")
    comtrade_units = _points(comtrade_payload, "unit_values")
    comtrade_change = None
    if len(comtrade_totals) >= 2 and comtrade_totals[-2][1]:
        comtrade_change = (
            comtrade_totals[-1][1] / comtrade_totals[-2][1] - 1.0
        ) * 100.0

    available = sum(
        1 for ok, payload in (
            (capex_f is not None and capex_f.ok, capex_payload),
            (revenue_f is not None and revenue_f.ok, revenue_payload),
            (inventory_f is not None and inventory_f.ok, inventory_payload),
            (comtrade_f is not None and comtrade_f.ok, comtrade_payload),
        ) if ok and payload
    )
    coverage = round(available / 4.0, 3)

    as_of: datetime | None = None
    for fetched in (capex_f, revenue_f, inventory_f):
        if fetched is not None and fetched.ok and fetched.as_of is not None:
            as_of = fetched.as_of if as_of is None else max(as_of, fetched.as_of)
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    return SupplyContext(
        as_of=as_of,
        capex_ttm_usd=capex_payload.get("ttm_usd"),
        capex_growth_pct=capex_payload.get("ttm_growth_pct"),
        chip_revenue_ttm_usd=revenue_payload.get("ttm_usd"),
        chip_revenue_growth_pct=revenue_payload.get("ttm_growth_pct"),
        inventory_usd=inventory_payload.get("inventory_usd"),
        inventory_ratio=inventory_ratio,
        inventory_ratio_change_pct=inventory_change,
        diversion_index=round(diversion, 3) if diversion is not None else None,
        queue_pressure=queue,
        queue_label=_queue_label(queue) if queue is not None else "sem dados",
        queue_note=_queue_note(
            capex_payload.get("ttm_usd"),
            capex_payload.get("ttm_growth_pct"),
            inventory_ratio,
            inventory_change,
            diversion,
        ),
        comtrade_volume_usd=comtrade_totals[-1][1] if comtrade_totals else None,
        comtrade_volume_change_pct=(
            round(comtrade_change, 2) if comtrade_change is not None else None
        ),
        comtrade_unit_value_usd_kg=comtrade_units[-1][1] if comtrade_units else None,
        comtrade_year=comtrade_totals[-1][0] if comtrade_totals else None,
        capex_series=to_points(_points(capex_payload, "ttm_points"), limit=12),
        inventory_series=to_points(_points(inventory_payload, "ratio_points"), limit=12),
        comtrade_series=to_points(comtrade_totals, limit=12),
        kind="modeled",
        coverage=coverage,
    )
