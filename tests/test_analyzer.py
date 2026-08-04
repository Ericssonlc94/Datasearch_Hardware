"""Testes do núcleo analítico — rodam sem rede."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain.analyzer import build_brazil, build_drivers, build_summary  # noqa: E402
from app.domain.catalog import CATEGORIES, validate_catalog  # noqa: E402
from app.domain.ranking import build_ranking  # noqa: E402
from app.series_utils import compound, pct_change, pressure_score  # noqa: E402


def _fetched(key: str, points: list[tuple[str, float]], path: str = "points") -> Fetched:
    return Fetched(
        key=key,
        label=key,
        provider="teste",
        url="",
        status="ok",
        payload={path: points},
        as_of=datetime.now(timezone.utc),
    )


def _ramp(start: float, end: float, days: int = 400) -> list[tuple[str, float]]:
    """Série diária linear de `start` a `end`, terminando hoje."""
    base = datetime(2025, 6, 1).toordinal()
    return [
        (
            datetime.fromordinal(base + i).date().isoformat(),
            start + (end - start) * i / (days - 1),
        )
        for i in range(days)
    ]


# ---------------- utilidades de série ----------------


def test_pressure_score_neutro_e_monotonico():
    assert pressure_score(0.0, 10.0) == 50.0
    assert pressure_score(None, 10.0) is None
    assert pressure_score(10.0, 10.0) > 70.0
    assert pressure_score(-10.0, 10.0) < 30.0
    # Saturação: dobrar a variação não dobra o score.
    assert pressure_score(100.0, 10.0) < 100.0
    assert pressure_score(50.0, 10.0) < pressure_score(100.0, 10.0)


def test_pct_change_usa_janela_em_dias():
    series = _ramp(100.0, 200.0, days=400)
    change = pct_change(series, 90)
    assert change is not None and change > 0
    # Série plana não gera variação.
    flat = [(d, 42.0) for d, _ in series]
    assert abs(pct_change(flat, 90)) < 1e-9


def test_compound_acumula_variacoes_mensais():
    monthly = [(f"2026-{m:02d}", 1.0) for m in range(1, 13)]
    acc = compound(monthly, 12)
    assert acc is not None
    assert abs(acc - 12.6825) < 0.01  # 1.01^12 - 1


# ---------------- catálogo ----------------


def test_catalogo_consistente():
    assert validate_catalog() == [], "betas devem somar 1.0 e referenciar drivers válidos"
    assert len(CATEGORIES) >= 10
    assert {c.key for c in CATEGORIES} >= {"gpu", "ram", "storage", "cpu", "smartphone"}


# ---------------- drivers e índice ----------------


def test_drivers_sem_dados_ficam_neutros_com_cobertura_zero():
    drivers = build_drivers({})
    assert drivers, "deve produzir um driver por spec mesmo sem dados"
    for d in drivers:
        assert d.score == 50.0
        assert d.coverage == 0.0
        assert d.trend == "estavel"


def test_indice_sobe_quando_sinais_sobem():
    alta = {
        "market.brent": _fetched("market.brent", _ramp(70, 110)),
        "market.soxx": _fetched("market.soxx", _ramp(200, 300)),
        "market.micron": _fetched("market.micron", _ramp(80, 150)),
        "market.nvda": _fetched("market.nvda", _ramp(100, 190)),
        "market.copper": _fetched("market.copper", _ramp(3.5, 4.6)),
        "market.rare_earth": _fetched("market.rare_earth", _ramp(50, 78)),
        "bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 6.1)),
    }
    baixa = {k: _fetched(k, _ramp(v.payload["points"][-1][1], v.payload["points"][0][1]))
             for k, v in alta.items()}

    d_alta = build_drivers(alta)
    d_baixa = build_drivers(baixa)
    br = build_brazil(alta)

    s_alta = build_summary(d_alta, br)
    s_baixa = build_summary(d_baixa, build_brazil(baixa))

    assert s_alta.iph > 50.0
    assert s_baixa.iph < 50.0
    assert s_alta.iph > s_baixa.iph
    assert 0.0 < s_alta.coverage <= 1.0


def test_cobertura_parcial_nao_quebra_o_indice():
    parcial = {"market.brent": _fetched("market.brent", _ramp(70, 110))}
    drivers = build_drivers(parcial)
    ormuz = next(d for d in drivers if d.key == "ormuz_helio")
    assert 0.0 < ormuz.coverage < 1.0
    assert ormuz.score > 50.0
    summary = build_summary(drivers, build_brazil(parcial))
    assert 0.0 <= summary.iph <= 100.0


# ---------------- Brasil e ranking ----------------


def test_contexto_brasil_le_ptax_e_ipca():
    collected = {
        "bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 5.5)),
        "bcb.ipca": _fetched("bcb.ipca", [(f"2026-{m:02d}", 0.5) for m in range(1, 13)]),
    }
    br = build_brazil(collected)
    assert br.usd_brl is not None and 5.4 < br.usd_brl <= 5.5
    assert br.usd_brl_change_90d_pct is not None and br.usd_brl_change_90d_pct > 0
    assert br.ipca_12m is not None and abs(br.ipca_12m - 6.17) < 0.1


def test_ranking_ordenado_e_completo():
    collected = {
        "bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 5.6)),
        "market.micron": _fetched("market.micron", _ramp(80, 150)),
        "market.soxx": _fetched("market.soxx", _ramp(200, 280)),
    }
    drivers = build_drivers(collected)
    br = build_brazil(collected)
    ranking = build_ranking(drivers, br, collected)

    assert len(ranking) == len(CATEGORIES)
    assert [i.rank for i in ranking] == list(range(1, len(ranking) + 1))
    valores = [i.projected_brazil_90d_pct for i in ranking]
    assert valores == sorted(valores, reverse=True), "ranking deve estar em ordem decrescente"

    for item in ranking:
        assert 0.0 <= item.pressure_score <= 100.0
        assert item.top_drivers, "cada item precisa expor a decomposição por driver"
        assert item.narrative


def test_cambio_nao_entra_na_projecao_global():
    """A projeção global é em dólar: mexer só no câmbio não pode alterá-la."""
    sem_fx = {"market.soxx": _fetched("market.soxx", _ramp(200, 280))}
    com_fx = dict(sem_fx, **{"bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 6.2))})

    r1 = build_ranking(build_drivers(sem_fx), build_brazil(sem_fx), sem_fx)
    r2 = build_ranking(build_drivers(com_fx), build_brazil(com_fx), com_fx)

    g1 = {i.key: i.projected_global_90d_pct for i in r1}
    g2 = {i.key: i.projected_global_90d_pct for i in r2}
    assert g1 == g2, "câmbio não pode contaminar a projeção global"

    # Já a projeção Brasil precisa subir com o dólar.
    b1 = {i.key: i.projected_brazil_90d_pct for i in r1}
    b2 = {i.key: i.projected_brazil_90d_pct for i in r2}
    assert all(b2[k] > b1[k] for k in b1), "alta do dólar deve elevar a projeção Brasil"


def test_projecao_brasil_compoe_e_nao_multiplica_por_imposto():
    """Imposto ad valorem escala nível, não variação percentual."""
    collected = {"bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 5.5))}
    ranking = build_ranking(build_drivers(collected), build_brazil(collected), collected)
    for item in ranking:
        # Sem pressão global, a projeção Brasil é só o efeito cambial repassado.
        assert abs(item.projected_brazil_90d_pct) < 20.0
        # E a carga tributária aparece no impacto absoluto, não no percentual.
        assert item.brl_impact_per_100usd is not None
        assert item.brl_impact_per_100usd > 100.0
