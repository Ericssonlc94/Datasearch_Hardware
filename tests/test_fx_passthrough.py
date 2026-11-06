"""Repasse cambial com prazo (T15/T07) — testes offline, sem rede.

O repasse de 85% do dólar leva um trimestre (90 dias). No horizonte exibido
(30 dias) entra só a fração linear 30/90. O cartão do dólar continua
mostrando o repasse completo e cita o primeiro mês.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain import fx  # noqa: E402
from app.domain.analyzer import (  # noqa: E402
    FX_HORIZON_DAYS,
    FX_PASSTHROUGH,
    FX_PASSTHROUGH_DAYS,
    build_brazil,
    build_drivers,
    fx_price_effect,
)
from app.domain.ranking import build_ranking  # noqa: E402

TODAY = date(2026, 11, 4)


def _degrau(antes: float, depois: float, dias: int = 40) -> list[tuple[str, float]]:
    """`antes` até 30 dias atrás (inclusive) e `depois` em seguida: +x% exatos em 30 dias."""
    inicio = TODAY - timedelta(days=dias)
    return [
        ((inicio + timedelta(days=i)).isoformat(), antes if i <= dias - 30 else depois)
        for i in range(dias + 1)
    ]


def _fetched(key: str, points) -> Fetched:
    return Fetched(key=key, label=key, provider="teste", url="", status="ok",
                   payload={"points": [list(p) for p in points]})


def test_parametros_do_repasse():
    assert FX_PASSTHROUGH == 0.85
    assert FX_PASSTHROUGH_DAYS == 90
    assert FX_HORIZON_DAYS == 30


# ---------------- caso 6 ----------------


def test_dolar_mais_dez_por_cento_com_global_neutro_projeta_um_terco_do_repasse():
    collected = {"bcb.ptax_usd": _fetched("bcb.ptax_usd", _degrau(5.0, 5.5))}
    brazil = build_brazil(collected)
    assert brazil.usd_brl_change_30d_pct == pytest.approx(10.0)
    assert brazil.fx_price_effect_30d_pct == pytest.approx(10 * 0.85 * 30 / 90, abs=0.01)

    ranking = build_ranking(build_drivers(collected), brazil, collected)
    assert ranking
    for item in ranking:
        assert item.projected_global_30d_pct == 0.0, item.key
        assert item.projected_brazil_30d_pct == pytest.approx(2.83, abs=0.01), item.key
        assert item.projected_brazil_30d_pct != pytest.approx(8.5, abs=0.5)


# ---------------- caso 7 ----------------


@pytest.mark.parametrize("variacao", [10.0, -4.0, 0.0, 3.7])
def test_horizonte_de_noventa_dias_aplica_o_repasse_inteiro(variacao):
    assert fx_price_effect(variacao, horizon_days=90) == pytest.approx(variacao * 0.85)


def test_horizonte_maior_que_o_trimestre_nao_passa_de_85_por_cento():
    assert fx_price_effect(10.0, horizon_days=180) == pytest.approx(8.5)
    assert fx_price_effect(10.0, horizon_days=365) == pytest.approx(8.5)


def test_horizonte_padrao_e_fracao_linear_e_lacuna_continua_lacuna():
    assert fx_price_effect(10.0) == pytest.approx(10 * 0.85 / 3)
    assert fx_price_effect(10.0, horizon_days=45) == pytest.approx(10 * 0.85 / 2)
    assert fx_price_effect(None) is None


# ---------------- caso 8 ----------------


def test_cartao_do_dolar_mostra_repasse_completo_e_o_primeiro_mes():
    peers = {k: _fetched(k, _degrau(100.0, 100.0)) for k in fx.PEERS}
    out = fx.explain_fx(peers, _degrau(5.0, 5.5), 0.85)
    assert out.price_effect_pct == pytest.approx(8.5)
    assert "85%" in out.impact_hardware
    assert "primeiro mês" in out.impact_hardware
    # 8,5% × 30/90 ≈ 2,8% no primeiro mês, a mesma conta do ranking.
    assert "2,8%" in out.impact_hardware or "2.8%" in out.impact_hardware
