"""Testes offline da fase 2: fila do consumidor, fallback e parser XBRL.

Nada aqui toca a rede: os payloads são dicionários com o mesmo formato que
`app/providers/sec.py` devolve. O objetivo é travar três invariantes:

1. lacuna não vira zero nem 50;
2. o mesmo choque nunca entra duas vezes (fallback não soma);
3. o consumidor fica no fim da fila quando capex sobe e estoque cai.
"""

from __future__ import annotations

import math

import pytest

from app.cache import Fetched
from app.domain.catalog import CATEGORIES
from app.domain.drivers import DRIVERS, DRIVERS_BY_KEY
from app.domain.supply import QUEUE_A, QUEUE_B, build_supply, zscore
from app.providers.sec import _aggregate_quarters, _flow_rows, _growth_points, _rolling_ttm
from app.services.collector import build_snapshot


def _fetched(key: str, payload: dict | None = None, status: str = "ok") -> Fetched:
    return Fetched(
        key=key,
        label=key,
        provider="teste",
        url="",
        status=status,  # type: ignore[arg-type]
        payload=payload,
    )


def _growth(values: list[float]) -> list[list[object]]:
    return [[f"2025-{i + 1:02d}-28", v] for i, v in enumerate(values)]


# ---------------- fila ----------------


def test_zscore_devolve_none_com_pouca_historia_ou_serie_plana():
    assert zscore([]) is None
    assert zscore([["2025-01", 10.0], ["2025-02", 11.0]]) is None
    assert zscore([["2025-01", 10.0], ["2025-02", 10.0], ["2025-03", 10.0]]) is None
    assert zscore([["2025-01", 10.0], ["2025-02", 12.0], ["2025-03", 14.0]]) > 0


def test_fila_sobe_quando_capex_acelera_e_estoque_cai():
    acelerando = build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler", {"growth_points": _growth([10, 12, 14])}
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth([8, 10, 12])}
            ),
            "sec.memory_inventory": _fetched(
                "sec.memory_inventory", {"ratio": 0.2, "ratio_change_pct": -20.0}
            ),
        }
    )
    desacelerando = build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler", {"growth_points": _growth([20, 15, 10])}
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth([20, 15, 10])}
            ),
            "sec.memory_inventory": _fetched(
                "sec.memory_inventory", {"ratio": 0.3, "ratio_change_pct": 20.0}
            ),
        }
    )
    assert acelerando.queue_pressure is not None
    assert desacelerando.queue_pressure is not None
    assert acelerando.queue_pressure > 50 > desacelerando.queue_pressure
    assert acelerando.queue_label.startswith("Fila")
    assert "estoque/receita" in acelerando.queue_note


def test_fila_sem_dados_nao_inventa_neutro():
    supply = build_supply({})
    assert supply.queue_pressure is None
    assert supply.queue_label == "sem dados"
    assert supply.coverage == 0.0
    assert "não preenche lacuna" in supply.queue_note


def test_queue_respeita_parametros_expostos():
    supply = build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler", {"growth_points": _growth([10, 12, 14])}
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth([8, 10, 12])}
            ),
        }
    )
    diversion = supply.diversion_index
    assert diversion is not None and supply.queue_pressure is not None
    esperado = 50 + 50 * math.tanh(QUEUE_A * diversion)
    assert abs(supply.queue_pressure - esperado) < 0.11  # arredondamento de 1 casa
    assert QUEUE_B > 0


def test_coverage_conta_as_quatro_fontes_da_fila():
    supply = build_supply(
        {
            "sec.capex_hyperscaler": _fetched(
                "sec.capex_hyperscaler", {"growth_points": _growth([10, 12, 14])}
            ),
            "sec.chip_revenue": _fetched(
                "sec.chip_revenue", {"growth_points": _growth([8, 10, 12])}
            ),
            "sec.memory_inventory": _fetched(
                "sec.memory_inventory", {"ratio": 0.2, "ratio_change_pct": -2.0}
            ),
            "comtrade.memory": _fetched("comtrade.memory", {"totals": [["2024", 1.0], ["2025", 1.2]]}),
        }
    )
    assert supply.coverage == 1.0
    assert supply.comtrade_volume_change_pct is not None
    assert supply.comtrade_volume_change_pct > 19


# ---------------- drivers e fallback ----------------


def test_alocacao_de_chips_tem_nove_sinais_e_pesos_somando_um():
    driver = DRIVERS_BY_KEY["alocacao_chips"]
    assert len(driver.signals) == 9
    assert abs(sum(s.weight for s in driver.signals) - 1.0) < 1e-9
    assert "chip_datacenter" not in DRIVERS_BY_KEY


def test_catalogo_so_referencia_drivers_existentes():
    for cat in CATEGORIES:
        assert set(cat.betas) <= set(DRIVERS_BY_KEY), cat.key
        assert abs(sum(cat.betas.values()) - 1.0) < 1e-9, cat.key


def test_fallback_entra_quando_primaria_falha_e_nao_duplica_o_choque():
    collected = {
        "market.soxx": _fetched("market.soxx", status="unavailable"),
        "market.tsmc": _fetched("market.tsmc", {"points": [["2025-01-01", 100.0], ["2025-04-01", 120.0]]}),
        "market.brent": _fetched("market.brent", {"points": [["2025-01-01", 70.0], ["2025-04-01", 84.0]]}),
        "fred.brent": _fetched("fred.brent", {"points": [["2025-01-01", 70.0], ["2025-04-01", 84.0]]}),
        "market.copper": _fetched("market.copper", {"points": [["2025-01-01", 4.0], ["2025-04-01", 4.4]]}),
        "fred.copper": _fetched("fred.copper", {"points": [["2025-01-01", 4.0], ["2025-04-01", 4.4]]}),
    }
    snap = build_snapshot(collected)
    drivers = {d.key: d for d in snap.drivers}

    # TSMC é sinal próprio: sem SOXX, o SOXX fica sem score em vez de copiar
    # a TSMC — senão o mesmo choque entraria duas vezes no driver.
    signals = {s.key: s for s in drivers["alocacao_chips"].signals}
    assert signals["soxx"].score is None
    assert signals["soxx"].used_source == "market.soxx"
    assert signals["tsmc"].used_source == "market.tsmc"
    assert signals["tsmc"].score is not None

    brent_signals = [s for s in drivers["ormuz_helio"].signals if "brent" in s.key]
    assert len(brent_signals) == 1
    assert brent_signals[0].used_source == "market.brent"

    copper_signals = [s for s in drivers["commodities"].signals if "copper" in s.key]
    assert len(copper_signals) == 1


def test_fallback_nao_e_usado_quando_primaria_tem_serie():
    collected = {
        "market.soxx": _fetched("market.soxx", {"points": [["2025-01-01", 100.0], ["2025-04-01", 130.0]]}),
        "market.tsmc": _fetched("market.tsmc", {"points": [["2025-01-01", 100.0], ["2025-04-01", 170.0]]}),
    }
    snap = build_snapshot(collected)
    soxx = next(
        s for s in next(d for d in snap.drivers if d.key == "alocacao_chips").signals if s.key == "soxx"
    )
    assert soxx.used_source == "market.soxx"


def test_snapshot_sempre_traz_bloco_de_fila():
    snap = build_snapshot({})
    assert snap.supply is not None
    assert snap.supply.queue_pressure is None
    assert snap.supply.kind == "modeled"


# ---------------- parser XBRL ----------------


def _xbrl(rows: list[tuple[str, str, float, str]]) -> dict:
    return {
        "units": {
            "USD": [
                {"start": s, "end": e, "val": v, "filed": f}
                for s, e, v, f in rows
            ]
        }
    }


def test_flow_rows_deriva_trimestres_dos_acumulados():
    data = _xbrl(
        [
            ("2025-01-01", "2025-03-31", 10.0, "2025-05-01"),
            ("2025-01-01", "2025-06-30", 30.0, "2025-08-01"),
            ("2025-01-01", "2025-09-30", 60.0, "2025-11-01"),
            ("2025-01-01", "2025-12-31", 100.0, "2026-02-01"),
        ]
    )
    rows = _flow_rows(data)
    assert [r["val"] for r in rows] == [10.0, 20.0, 30.0, 40.0]
    assert [r["end"] for r in rows] == [
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
    ]


def test_flow_rows_prefere_trimestre_direto_ao_derivado():
    data = _xbrl(
        [
            ("2025-01-01", "2025-03-31", 10.0, "2025-05-01"),
            ("2025-01-01", "2025-06-30", 30.0, "2025-08-01"),
            ("2025-04-01", "2025-06-30", 21.0, "2025-08-02"),
        ]
    )
    rows = _flow_rows(data)
    q2 = next(r for r in rows if r["end"] == "2025-06-30")
    assert q2["val"] == 21.0
    assert q2["direct"] is True


def test_flow_rows_ignora_periodo_anual_isolado():
    # Comparativo de 12 meses (10-K) não é início de exercício; não dá para
    # derivar trimestre dele.
    data = _xbrl([("2024-04-01", "2025-03-31", 100.0, "2025-05-01")])
    assert _flow_rows(data) == []


def test_rolling_ttm_exige_quatro_trimestres_consecutivos_e_cobertura():
    quarters = [
        {"key": (2025, 1), "end": "2025-03-31", "value": 10.0, "count": 5},
        {"key": (2025, 2), "end": "2025-06-30", "value": 20.0, "count": 5},
        {"key": (2025, 3), "end": "2025-09-30", "value": 30.0, "count": 5},
        {"key": (2025, 4), "end": "2025-12-31", "value": 40.0, "count": 5},
        {"key": (2026, 1), "end": "2026-03-31", "value": 50.0, "count": 1},
    ]
    ttm = _rolling_ttm(quarters, min_companies=3)
    assert ttm == [("2025-12-31", 100.0)]


def test_aggregate_quarters_soma_empresas_no_mesmo_trimestre():
    q1 = [{"end": "2025-03-31", "val": 10.0}]
    q2 = [{"end": "2025-03-31", "val": 20.0}]
    agg = _aggregate_quarters([q1, q2])
    assert agg[0]["value"] == 30.0
    assert agg[0]["count"] == 2


def test_growth_points_precisa_de_um_ano():
    ttm = [
        ("2024-03-31", 100.0),
        ("2024-06-30", 100.0),
        ("2024-09-30", 100.0),
        ("2024-12-31", 100.0),
        ("2025-03-31", 120.0),
    ]
    growth = _growth_points(ttm)
    assert len(growth) == 1
    assert growth[0][0] == "2025-03-31"
    assert growth[0][1] == pytest.approx(20.0)
