"""Testes offline da T29 (supply_fronts.py): dados de exemplo, sem rede."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.domain import supply_fronts as F
from app.domain.catalog import CATEGORIES_BY_KEY


def Q(i: int, inv: float, cogs: float, days: int = 91) -> F.Quarter:
    return F.Quarter(end=date(2020, 3, 31) + timedelta(days=91 * i), days=days, inventory=inv, cogs=cogs)


def test_pesos_e_exposicao_validos_e_desligado():
    assert F.validate_fronts() == []
    assert F.FRONTS_ENABLED is True  # ligado na T30
    assert set(F.EXPOSURE) == set(CATEGORIES_BY_KEY)


def test_dio_normaliza_pela_duracao_do_trimestre():
    curto = F.Quarter(end=date(2026, 6, 30), days=91, inventory=91.0, cogs=91.0)
    longo = F.Quarter(end=date(2026, 9, 30), days=98, inventory=91.0, cogs=98.0)
    assert F.dio(curto) == pytest.approx(91.0)
    assert F.dio(longo) == pytest.approx(91.0)  # mesmo giro diário, mesmo DIO
    assert F.dio(F.Quarter(end=date(2026, 9, 30), days=91, inventory=1.0, cogs=0.0)) is None


def test_dio_baixo_e_pressao_alta_e_normal_p25_p75():
    hist = [Q(i, 100.0 + (i % 5) * 5, 91.0) for i in range(20)]  # DIO 100–120
    reading = F.company_dio(hist + [Q(20, 60.0, 91.0)])
    assert reading.days == pytest.approx(60.0)
    assert reading.z is not None and reading.z < 0
    assert reading.pressure > 85
    lo, hi = reading.normal
    assert 100.0 <= lo < hi <= 120.0


def test_dio_usa_so_os_20_trimestres_anteriores():
    velho = [Q(i, 500.0, 91.0) for i in range(10)]
    recente = [Q(10 + i, 100.0 + (i % 4), 91.0) for i in range(20)]
    reading = F.company_dio(velho + recente + [Q(30, 101.0, 91.0)])
    assert reading.normal[1] < 110  # os 500 dias antigos não entram no normal


def test_frente_logica_z_por_empresa_e_card_agregado():
    nvda = [Q(i, 100.0 + (i % 3), 91.0) for i in range(21)]
    amd = [Q(i, 170.0 + (i % 3), 91.0) for i in range(21)]
    group = F.group_dio({"NVIDIA": nvda, "AMD": amd})
    assert group.days == pytest.approx((nvda[-1].inventory + amd[-1].inventory) / 2.0)
    zs = [F.company_dio(nvda).z, F.company_dio(amd).z]
    assert group.z == pytest.approx(sum(zs) / 2)


def test_tsmc_yoy_de_3_meses_exige_meses_presentes():
    pts = [(f"{y}-{m:02d}", 100.0 * (1.1 ** (y - 2024))) for y in (2024, 2025) for m in range(1, 13)]
    yoy = F.rolling_3m_yoy(pts)
    assert yoy and all(v == pytest.approx(10.0) for _, v in yoy)
    sem_mes = [p for p in pts if p[0] != "2024-11"]
    periods = {p for p, _ in F.rolling_3m_yoy(sem_mes)}
    assert "2025-11" not in periods and "2025-12" not in periods and "2026-01" not in periods


def test_tsmc_crescimento_acima_do_normal_e_pressao_alta():
    pts = []
    v = 100.0
    for i in range(84):
        y, m = 2019 + i // 12, i % 12 + 1
        v *= (1.01 + 0.005 * ((i * i) % 7)) if i < 83 else 1.6
        pts.append((f"{y}-{m:02d}", v))
    g = F.tsmc_growth(pts)
    assert g.period == "2025-12" and g.pressure > 88 and g.normal is not None
    # Mesmo crescimento todo mês: sem variação na história, não há z.
    plano = [(f"{2019 + i // 12}-{i % 12 + 1:02d}", 100.0 * 1.01 ** i) for i in range(84)]
    assert F.tsmc_growth(plano).z is None


def test_nota_por_categoria_pesa_a_exposicao_e_renormaliza():
    scores = {"dio_memory": 90.0, "dio_logic": 50.0, "capex_hyperscaler": 50.0}
    ram = F.front_score(scores, "ram")
    psu = F.front_score(scores, "psu")
    assert ram > psu  # memória apertada pesa na RAM, não na fonte
    assert F.front_score({"dio_memory": 90.0}, "psu") is None  # exposição 0, nada mais
    assert F.front_score({}, "ram") is None


def test_exposicao_1_devolve_a_nota_global():
    scores = {k: 40.0 + i * 5 for i, k in enumerate(F.FRONT_SIGNALS)}
    num = sum(w * scores[k] for k, (_, w) in F.FRONT_SIGNALS.items())
    assert F.front_score(scores) == pytest.approx(num)


def test_sinal_geral_vale_para_todas_as_categorias():
    for cat in F.EXPOSURE:
        assert F.front_score({"ppi_semis": 70.0}, cat) == pytest.approx(70.0)


def test_validade_mensal_75_e_trimestral_150():
    hoje = date(2026, 11, 5)
    assert F.is_fresh("2026-09", "monthly", hoje)  # fim 30/09, 36 dias
    assert not F.is_fresh("2026-07", "monthly", hoje)  # fim 31/07, 97 dias
    assert F.is_fresh(date(2026, 6, 30), "quarterly", hoje)  # 128 dias
    assert not F.is_fresh(date(2026, 3, 31), "quarterly", hoje)
    assert not F.is_fresh("lixo", "monthly", hoje)


def test_z_sem_historia_nao_inventa():
    assert F.z_against([1.0, 2.0], 3.0) is None
    assert F.z_against([5.0, 5.0, 5.0], 9.0) is None
    assert F.z_pressure(None) is None
    assert F.normal_range([1.0, 2.0]) is None


def test_fila_so_de_demanda():
    assert F.demand_queue(None, None) is None
    assert F.demand_queue(1.0, 1.0) == pytest.approx(50 + 50 * math.tanh(0.5))
