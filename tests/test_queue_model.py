"""Fila do consumidor com o estoque em z-score (T15) — testes offline, sem rede.

Trava a conta nova da fila (`app/domain/supply.py`):

    fila = 50 + 50·tanh(a·[z(capex) + z(receita)] + b·(−z(Δ estoque a/a)))

Os payloads imitam o formato de `app/providers/sec.py`. As séries são
montadas para que o último ponto tenha exatamente o z-score desejado, então
as faixas esperadas (≈82 em +1σ, ≈95 em +2σ) podem ser conferidas à mão.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain.supply import (  # noqa: E402
    INVENTORY_YOY_LAG,
    QUEUE_A,
    QUEUE_B,
    build_supply,
    inventory_yoy_changes,
    zscore,
)


def _fetched(key: str, payload: dict) -> Fetched:
    return Fetched(key=key, label=key, provider="teste", url="", status="ok", payload=payload)


def _datas(n: int) -> list[str]:
    return [f"{2019 + i // 4}-Q{i % 4 + 1}" for i in range(n)]


def _serie_com_z(alvo: float, n: int = 12) -> list[float]:
    """História alternando ±1 e um último valor cujo z-score é exatamente `alvo`.

    O z do último valor cresce com ele, então a bisseção converge.
    """
    historia = [1.0 if i % 2 else -1.0 for i in range(n - 1)]
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        z = zscore([(str(i), v) for i, v in enumerate(historia + [mid])])
        if z < alvo:
            lo = mid
        else:
            hi = mid
    return historia + [(lo + hi) / 2]


def _growth(valores: list[float]) -> list[list[object]]:
    return [[d, v] for d, v in zip(_datas(len(valores)), valores)]


def _ratio_points(variacoes_pct: list[float], base: float = 0.5) -> list[list[object]]:
    """Estoque/receita trimestral cujas variações a/a (lag 4) são `variacoes_pct`."""
    ratios = [base] * INVENTORY_YOY_LAG
    for change in variacoes_pct:
        ratios.append(ratios[-INVENTORY_YOY_LAG] * (1 + change / 100.0))
    return [[d, r] for d, r in zip(_datas(len(ratios)), ratios)]


def _supply(z_capex: float, z_receita: float, z_estoque: float | None):
    """Fila com os três componentes no z pedido (`z_estoque` é o z da variação a/a)."""
    collected = {
        "sec.capex_hyperscaler": _fetched(
            "sec.capex_hyperscaler", {"growth_points": _growth(_serie_com_z(z_capex))}
        ),
        "sec.chip_revenue": _fetched(
            "sec.chip_revenue", {"growth_points": _growth(_serie_com_z(z_receita))}
        ),
    }
    if z_estoque is not None:
        collected["sec.memory_inventory"] = _fetched(
            "sec.memory_inventory",
            {"ratio": 0.2, "ratio_change_pct": -10.0,
             "ratio_points": _ratio_points(_serie_com_z(z_estoque))},
        )
    return build_supply(collected)


def _esperado(desvio: float, estoque: float = 0.0) -> float:
    return 50 + 50 * math.tanh(QUEUE_A * desvio + QUEUE_B * estoque)


# ---------------- caso 1: faixa e monotonicidade ----------------


def test_tres_componentes_em_mais_um_sigma_nao_saturam_a_fila():
    # "+1σ" no estoque é pressão +1: a variação a/a do estoque está em −1σ.
    um = _supply(1.0, 1.0, -1.0)
    assert um.diversion_index == pytest.approx(2.0, abs=1e-3)
    assert 75 < um.queue_pressure < 90
    assert um.queue_pressure == pytest.approx(_esperado(2.0, 1.0), abs=0.06)
    assert um.queue_label == "Fila crítica para o consumidor"


def test_fila_em_mais_dois_sigma_sobe_mais_que_em_mais_um():
    um = _supply(1.0, 1.0, -1.0).queue_pressure
    dois = _supply(2.0, 2.0, -2.0).queue_pressure
    assert dois > um
    assert dois == pytest.approx(_esperado(4.0, 2.0), abs=0.06)
    assert dois < 100, "+2σ ainda não pode prender a fila no teto"


# ---------------- caso 2: estoque ----------------


def test_estoque_caindo_mais_aumenta_a_fila_com_o_resto_igual():
    filas = [_supply(1.0, 1.0, z).queue_pressure for z in (1.0, 0.0, -1.0, -2.0)]
    assert filas == sorted(filas), filas
    assert len(set(filas)) == len(filas), "cada queda adicional precisa mover a fila"


# ---------------- caso 3: caso real ----------------

# Estoque/receita da Micron em 29 trimestres, de 0,511 até 0,078 (−65% a/a no
# último ponto), com o ciclo de 2019–2024 no meio. Capex em +93% a/a no fim.
RATIO_REAL = [
    0.511, 0.470, 0.430, 0.402, 0.380, 0.365, 0.350, 0.330,
    0.300, 0.285, 0.290, 0.320, 0.360, 0.420, 0.480, 0.500,
    0.495, 0.450, 0.380, 0.300, 0.260, 0.240, 0.235, 0.230,
    0.223, 0.180, 0.130, 0.100, 0.078,
]
CAPEX_REAL = [12, 8, 5, 3, 10, 18, 25, 20, 15, 9, 6, 4, 12, 30, 45, 55, 62, 70, 78, 85, 93]
RECEITA_REAL = [20, 15, 10, -5, -20, -35, -40, -25, 5, 40, 80, 110, 125, 120, 115, 130]


def test_caso_real_nao_prende_a_fila_no_teto():
    pontos = [[d, r] for d, r in zip(_datas(len(RATIO_REAL)), RATIO_REAL)]
    supply = build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler",
                {"ttm_growth_pct": 93.0, "growth_points": _growth(CAPEX_REAL)},
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth(RECEITA_REAL)}
            ),
            "sec.memory_inventory": _fetched(
                "sec.memory_inventory",
                {"ratio": RATIO_REAL[-1], "ratio_change_pct": -65.0, "ratio_points": pontos},
            ),
        }
    )
    variacoes = inventory_yoy_changes([(d, r) for d, r in pontos])
    assert variacoes[-1][1] == pytest.approx(-65.0, abs=0.1)
    assert supply.queue_pressure is not None
    assert supply.queue_pressure < 99
    assert supply.queue_pressure >= 75, "o extremo de 2026 continua sendo fila crítica"


# ---------------- caso 4: sem história de estoque ----------------


def test_estoque_sem_sete_pontos_fica_fora_da_conta_mas_nao_vira_zero():
    seis = [[d, r] for d, r in zip(_datas(6), [0.5, 0.45, 0.4, 0.35, 0.3, 0.2])]
    assert zscore(inventory_yoy_changes([(d, r) for d, r in seis])) is None
    base = {
        "sec.capex_hyperscaler": _fetched(
            "sec.capex_hyperscaler", {"growth_points": _growth([10, 12, 14])}
        ),
        "sec.chip_revenue": _fetched(
            "sec.chip_revenue", {"growth_points": _growth([8, 10, 12])}
        ),
    }
    supply = build_supply(
        dict(base, **{"sec.memory_inventory": _fetched(
            "sec.memory_inventory",
            {"ratio": 0.2, "ratio_change_pct": -65.0, "ratio_points": seis},
        )})
    )
    desvio = supply.diversion_index
    assert desvio is not None
    assert supply.queue_pressure == pytest.approx(
        round(50 + 50 * math.tanh(QUEUE_A * desvio), 1), abs=1e-9
    )
    # A queda bruta de 65% não entra na fila, mas o dado observado continua lá.
    assert supply.inventory_ratio == 0.2
    assert supply.inventory_ratio_change_pct == -65.0
    assert [p.v for p in supply.inventory_series] == [0.5, 0.45, 0.4, 0.35, 0.3, 0.2]
    assert supply.coverage == 0.75


def test_estoque_com_sete_pontos_ja_entra_na_fila():
    sete = [[d, r] for d, r in zip(_datas(7), [0.5, 0.5, 0.5, 0.5, 0.45, 0.4, 0.2])]
    assert zscore(inventory_yoy_changes([(d, r) for d, r in sete])) is not None
    supply = _supply_com_estoque(sete)
    sem = _supply_com_estoque(sete[:6])
    assert supply.queue_pressure > sem.queue_pressure, "estoque caindo deve somar pressão"


def _supply_com_estoque(pontos):
    return build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler", {"growth_points": _growth([10, 12, 14])}
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth([8, 10, 12])}
            ),
            "sec.memory_inventory": _fetched(
                "sec.memory_inventory", {"ratio": pontos[-1][1], "ratio_points": pontos}
            ),
        }
    )


# ---------------- caso 5: variação a/a ----------------


def test_variacao_anual_compara_com_quatro_trimestres_antes():
    pontos = list(zip(_datas(6), [1.0, 2.0, 4.0, 5.0, 1.5, 3.0]))
    assert INVENTORY_YOY_LAG == 4
    out = inventory_yoy_changes(pontos)
    assert [d for d, _ in out] == [pontos[4][0], pontos[5][0]]
    assert out[0][1] == pytest.approx(50.0)   # 1,5 contra 1,0
    assert out[1][1] == pytest.approx(50.0)   # 3,0 contra 2,0 (não contra 1,5)


def test_variacao_anual_ignora_base_zero_e_nao_finita():
    pontos = list(zip(_datas(7), [0.0, 1.0, 2.0, 1.0, 0.3, 1.5, float("nan")]))
    out = dict(inventory_yoy_changes(pontos))
    assert pontos[4][0] not in out, "base zero não gera variação infinita"
    assert out[pontos[5][0]] == pytest.approx(50.0)
    assert pontos[6][0] not in out, "ponto não finito fica de fora"
    assert inventory_yoy_changes(pontos[:4]) == []
