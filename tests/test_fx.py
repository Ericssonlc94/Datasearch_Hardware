"""Explicação do dólar — testes offline, sem rede."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain import fx  # noqa: E402

TODAY = date(2026, 11, 4)


def _series(start_value: float, end_value: float, days: int = 40) -> list[tuple[str, float]]:
    """Degrau: valor inicial até 30 dias atrás (inclusive), valor final depois."""
    start = TODAY - timedelta(days=days)
    return [
        ((start + timedelta(days=i)).isoformat(), start_value if i <= days - 30 else end_value)
        for i in range(days + 1)
    ]


def _fetched(key: str, points) -> Fetched:
    return Fetched(key=key, label=key, provider="teste", url="", status="ok",
                   payload={"points": [list(p) for p in points]})


def _peers(change_pct: float) -> dict[str, Fetched]:
    return {
        key: _fetched(key, _series(100.0, 100.0 * (1 + change_pct / 100)))
        for key in fx.PEERS
    }


def test_alta_brasileira_quando_pares_ficam_parados():
    usd_brl = _series(5.0, 5.5)  # +10%
    collected = _peers(0.5)
    out = fx.explain_fx(collected, usd_brl, 0.85)
    assert out.brl_change_30d_pct == pytest.approx(10.0)
    assert out.peers_change_30d_pct == pytest.approx(0.5)
    assert out.domestic_share == pytest.approx(0.95, abs=0.001)
    assert out.reasons[0].text.startswith("A alta é sobretudo brasileira")
    assert out.price_effect_pct == pytest.approx(8.5)


def test_alta_global_quando_pares_caem_junto():
    out = fx.explain_fx(_peers(9.0), _series(5.0, 5.5), 0.85)
    assert out.domestic_share == pytest.approx(0.1, abs=0.001)
    assert out.reasons[0].text.startswith("A alta acompanha o mundo")


def test_dolar_estavel_e_sem_pares():
    stable = fx.explain_fx(_peers(0.0), _series(5.0, 5.01), 0.85)
    assert stable.domestic_share is None
    assert "praticamente estável" in stable.reasons[0].text
    alone = fx.explain_fx({}, _series(5.0, 5.5), 0.85)
    assert alone.peers_change_30d_pct is None
    assert "não dá para separar" in alone.reasons[0].text


def test_sem_serie_do_dolar_nao_ha_explicacao():
    assert fx.explain_fx(_peers(1.0), [], 0.85) is None


def test_diferencial_de_juros_encolhendo():
    collected = _peers(0.0)
    collected["bcb.selic_meta"] = _fetched("bcb.selic_meta", _series(15.0, 14.25))
    collected["fred.fed_funds"] = _fetched("fred.fed_funds", _series(3.88, 3.88))
    out = fx.explain_fx(collected, _series(5.0, 5.5), 0.85)
    assert out.rate_diff_pp == pytest.approx(10.37)
    assert out.rate_diff_change_pp == pytest.approx(-0.75)
    juros = next(r for r in out.reasons if r.key == "juros")
    assert "encolheu" in juros.text


def test_impacto_no_custo_de_desembarque():
    out = fx.explain_fx(_peers(0.0), _series(5.0, 5.5), 0.85)
    m = out.tax_multiplier
    assert out.landed_per_100usd == pytest.approx(100 * 5.5 * m)
    assert out.landed_per_100usd_30d_ago == pytest.approx(100 * 5.0 * m)
    assert "+R$" in out.impact_market
    assert "85%" in out.impact_hardware
