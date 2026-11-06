"""T30 — frentes de oferta ligadas, TSMC pelo MOPS e catálogo `price.*`.

Sem rede. Substitui, quando a QA adotar, as asserções do modelo antigo em:
- test_supply.py::test_alocacao_de_chips_tem_nove_sinais_e_pesos_somando_um
  (agora 11 sinais com os pesos de `FRONT_SIGNALS`);
- test_queue_model.py (4 testes do estoque na fila: a fila é só demanda);
- test_backfill.py::test_sinais_diarios_olham_30_dias_e_mensais_continuam_longos
  (sinais `mode="front"` não têm janela; excluir da regra dos 180 dias);
- test_api_security.py (3 testes de `model_since`/`model_version`, que
  supunham `MODEL_VERSIONS` vazio).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from app.cache import Fetched
from app.domain import supply_fronts as sf
from app.domain.analyzer import build_drivers
from app.domain.catalog import CATEGORIES_BY_KEY
from app.domain.backfill import collected_as_of
from app.domain.drivers import DRIVERS
from app.domain.ranking import _category_scores
from app.domain.series import MODEL_VERSIONS, SERIES_BY_KEY
from app.domain.supply import build_supply
from app.providers import tsmc


def _fetched(key, payload, fetched_at=None):
    return Fetched(key=key, label=key, provider="t", url="", status="ok",
                   payload=payload, fetched_at=fetched_at)


# --- TSMC pelo MOPS ------------------------------------------------------------

MOPS_BODY = {
    "code": 200,
    "result": {
        "yymm": "11409",
        "data": [["本月", "330,980,920"], ["去年同期", "251,872,717"], ["增減百分比", "31.41"]],
    },
}


def test_mops_le_o_mes_e_o_mesmo_mes_do_ano_anterior_em_milhoes():
    assert tsmc.parse_mops(MOPS_BODY) == {"2025-09": 330980.92, "2024-09": 251872.717}


@pytest.mark.parametrize("body", [
    None, [], {"code": 500}, {"code": 200, "result": {"yymm": "abc", "data": []}},
    {"code": 200, "result": {"yymm": "11409", "data": [["本月", "NaN"], ["去年同期", "-1"]]}},
    {"code": 200, "result": {"yymm": "11413", "data": [["本月", "1"]]}},
])
def test_mops_ignora_resposta_estranha(body):
    assert tsmc.parse_mops(body) == {}


def test_consultas_cobrem_o_fim_do_ano_anterior_sem_buraco():
    queries = tsmc._mops_queries("2026-09")
    assert len(queries) == 12 * tsmc.HISTORY_PAIRS
    assert (2025, 12) in queries and (2026, 10) not in queries
    covered = {f"{y:04d}-{m:02d}" for y, m in queries} | {f"{y - 1:04d}-{m:02d}" for y, m in queries}
    months = [f"{y:04d}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13)]
    assert all(m in covered for m in months if m <= "2026-09")


def test_mops_para_no_primeiro_desafio(monkeypatch):
    calls = []

    async def fake_post(url, payload, **kw):
        calls.append(payload)
        raise tsmc.ChallengeDetected("desafio")

    monkeypatch.setattr(tsmc, "post_json", fake_post)
    monkeypatch.setattr(tsmc, "_SPACING_S", 0)
    errors: list[str] = []
    assert asyncio.run(tsmc._fetch_mops("2026-09", errors)) == {}
    assert len(calls) == 1 and "desafio" in errors[0]


# --- frentes -------------------------------------------------------------------


def test_trimestre_civil_mais_proximo():
    assert sf.calendar_quarter(date(2026, 7, 26)) == date(2026, 6, 30)
    assert sf.calendar_quarter(date(2026, 9, 27)) == date(2026, 9, 30)
    assert sf.calendar_quarter(date(2026, 1, 2)) == date(2025, 12, 31)


def _rows(ends, inventory=100.0, cogs=91.0, wobble=0.0):
    """Trimestres com DIO = inventory ± wobble (alternado), para ter desvio."""
    return [{"end": e, "days": 91, "inventory": inventory + (wobble if i % 2 else -wobble),
             "cogs": cogs, "filed": e} for i, e in enumerate(ends)]


def test_dio_de_grupo_alinha_anos_fiscais_diferentes():
    nvda = _rows(["2026-01-25", "2026-04-26", "2026-07-26"])
    amd = _rows(["2025-12-27", "2026-03-28", "2026-06-27", "2026-09-26"])
    series = sf.dio_series(sf.quarters_from(_fetched("sec.logic_quarters",
                                                     {"by_company": {"NVDA": nvda, "AMD": amd}})))
    assert [p for p, _ in series] == ["2025-12-31", "2026-03-31", "2026-06-30"]
    assert series[-1][1] == pytest.approx(100.0)


def test_frente_vencida_fica_no_card_sem_nota():
    rows = _rows([f"{y}-{m:02d}-28" for y in range(2020, 2026) for m in (3, 6, 9, 12)], wobble=5.0)
    rows[-1]["inventory"] = 60.0
    col = {"sec.memory_quarters": _fetched("sec.memory_quarters", {"by_company": {"MU": rows}})}
    fresh = sf.read_front("dio_memory", col, date(2026, 1, 15))
    old = sf.read_front("dio_memory", col, date(2026, 11, 5))
    assert fresh.pressure is not None and fresh.pressure > 50  # estoque caiu
    assert old.value == fresh.value and old.pressure is None and not old.fresh
    cards = sf.build_fronts(col, date(2026, 11, 5))
    assert [c["key"] for c in cards] == ["memoria", "logica", "demanda"]
    assert cards[0]["status"] == "stale" and cards[1]["status"] == "unavailable"


def test_reconstrucao_corta_pela_publicacao():
    tsmc_f = _fetched("tsmc.monthly_revenue", {
        "points": [["2026-04", 1.0], ["2026-05", 2.0]],
        "released": {"2026-04": "2026-05-10", "2026-05": "2026-06-10"},
    })
    sec_f = _fetched("sec.memory_quarters", {"by_company": {"MU": [
        {"end": "2026-02-26", "days": 91, "inventory": 1, "cogs": 1, "filed": "2026-03-25"},
        {"end": "2026-05-28", "days": 91, "inventory": 1, "cogs": 1, "filed": "2026-06-25"},
    ]}})
    cut = collected_as_of({"tsmc.monthly_revenue": tsmc_f, "sec.memory_quarters": sec_f}, date(2026, 6, 1))
    assert cut["tsmc.monthly_revenue"].payload["points"] == [["2026-04", 1.0]]
    assert len(cut["sec.memory_quarters"].payload["by_company"]["MU"]) == 1
    assert cut["sec.memory_quarters"].fetched_at.date() == date(2026, 6, 1)


# --- ligação ---------------------------------------------------------------------


def test_alocacao_de_chips_usa_os_pesos_das_frentes():
    chips = next(d for d in DRIVERS if d.key == "alocacao_chips")
    assert {s.key: s.weight for s in chips.signals} == {k: w for k, (_, w) in sf.FRONT_SIGNALS.items()}
    assert "memory_inventory" not in {s.key for s in chips.signals}


def test_ranking_pesa_alocacao_pela_exposicao():
    rows = _rows([f"{y}-{m:02d}-28" for y in range(2020, 2027) for m in (3, 6, 9)], wobble=5.0)
    rows[-1]["inventory"] = 40.0  # estoque de memória despencou
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    col = {"sec.memory_quarters": _fetched("sec.memory_quarters", {"by_company": {"MU": rows}}, now)}
    by_key = {d.key: d for d in build_drivers(col)}
    ram = _category_scores(CATEGORIES_BY_KEY["ram"], by_key)
    psu = _category_scores(CATEGORIES_BY_KEY["psu"], by_key)
    assert ram["alocacao_chips"] > 80
    # Fonte não tem exposição à memória: sem outro sinal, fica a nota do vetor.
    assert psu["alocacao_chips"] == by_key["alocacao_chips"].score


def test_fila_e_so_demanda():
    growth = [[f"{y}-Q{q}", v] for (y, q), v in zip(
        [(y, q) for y in range(2019, 2027) for q in (1, 2, 3, 4)], [5, 6, 4, 5] * 8)]
    capex = _fetched("sec.capex_hyperscaler", {"growth_points": growth})
    inv_down = _fetched("sec.memory_inventory", {"ratio_points": [[f"p{i}", 1 - i / 20] for i in range(12)]})
    inv_up = replace(inv_down, payload={"ratio_points": [[f"p{i}", 1 + i / 20] for i in range(12)]})
    a = build_supply({"sec.capex_hyperscaler": capex, "sec.memory_inventory": inv_down})
    b = build_supply({"sec.capex_hyperscaler": capex, "sec.memory_inventory": inv_up})
    assert a.queue_pressure is not None and a.queue_pressure == b.queue_pressure


def test_catalogo_tem_precos_e_versoes_da_t30():
    assert {"price.gpu.alto", "price.gpu.medio.amd", "price.gpu.baixo.diff_amd_pct",
            "price.ram.medio"} <= set(SERIES_BY_KEY)
    # T33: celular e notebook voltaram, e monitor/fonte/console têm o alto.
    assert {"price.notebook.alto", "price.smartphone.baixo", "price.monitor.alto"} <= set(SERIES_BY_KEY)
    assert set(MODEL_VERSIONS) == {"supply.queue", "driver.alocacao_chips", "iph", "iph_br", "cat."}


# --- T33: marketplace ------------------------------------------------------------


def test_marketplace_vale_so_com_o_vendedor_fixado():
    from app.domain import prices as P

    day = date(2026, 11, 5)
    ok = P.Listing("1", day, 2000.0, seller="Magalu")
    assert P.screen_listing(ok, "smartphone", seller="Magalu") is None
    assert P.screen_listing(ok, "smartphone") == "seller"  # sem fixar, só KaBuM!
    outro = P.Listing("1", day, 2000.0, seller="Loja X")
    assert P.screen_listing(outro, "smartphone", seller="Magalu") == "seller"


def test_historico_grava_preco_do_vendedor_fixado(tmp_path):
    from app.services import history

    db = history.init_db(tmp_path / "h.db")
    base = {"day": "2026-11-05", "available": True, "price_full": 2110.0, "price_cash": 2000.0}
    history.record_listings([
        {**base, "code": "1", "seller": "Magalu", "seller_expected": "Magalu"},
        {**base, "code": "2", "seller": "Loja X", "seller_expected": "Magalu"},
        {**base, "code": "3", "seller": "KaBuM!"},
    ], path=db)
    out = history.listing_history(["1", "2", "3"], days=3650, path=db)
    assert out["1"][0]["full"] == 2110.0 and out["1"][0]["avail"] == 1
    assert out["2"][0]["full"] is None and out["2"][0]["avail"] == 0
    assert out["3"][0]["avail"] == 1


def test_faixa_fixa_da_curadoria_contigua():
    """T35d: a faixa fixa só serve à curadoria e ao filtro; a exibida é a observada."""
    from app.domain import prices as P
    from app.domain.catalog import CATEGORIES_BY_KEY

    assert P.curation_range("gpu", "baixo") == (1500, 2500)
    for key in CATEGORIES_BY_KEY:
        bands = P.expected_bands(key)
        for low, high in zip(bands, bands[1:]):
            assert P.curation_range(key, low)[1] <= P.curation_range(key, high)[0], key
    assert P.observed_range({"a": 1000.0, "b": None, "c": 3000.0}) == (1000.0, 3000.0)
