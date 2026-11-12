"""Reconstrução do IPH, horizonte de 30 dias e fatores geopolíticos — offline."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain import backfill, ranking  # noqa: E402
from app.domain.analyzer import build_brazil, build_drivers  # noqa: E402
from app.domain.drivers import DRIVERS, DRIVERS_BY_KEY  # noqa: E402
from app.providers import fedreg, usgs  # noqa: E402
from app.series_utils import peak_score, ratio_series, trailing_mean, window_peak, window_sum  # noqa: E402
from app.services import history  # noqa: E402

TODAY = date(2026, 11, 4)


def _fetched(key: str, points: list[list], path: str = "points") -> Fetched:
    return Fetched(key=key, label=key, provider="teste", url="", status="ok",
                   payload={path: points})


def _daily(start: date, values: list[float]) -> list[list]:
    return [[(start + timedelta(days=i)).isoformat(), v] for i, v in enumerate(values)]


# ---------------- corte por data ----------------


def test_known_on_respeita_frequencia():
    day = date(2026, 10, 15)
    assert backfill._known_on("2026-10-15", day)
    assert not backfill._known_on("2026-10-16", day)
    assert backfill._known_on("2026-10", day)
    assert not backfill._known_on("2026-11", day)
    # Ano só conta depois de fechado.
    assert backfill._known_on("2025", day)
    assert not backfill._known_on("2026", day)


def test_collected_as_of_corta_sem_mexer_no_original():
    pts = _daily(date(2026, 10, 1), [1.0, 2.0, 3.0, 4.0])
    collected = {"market.brent": _fetched("market.brent", pts)}
    cut = backfill.collected_as_of(collected, date(2026, 10, 2))
    assert cut["market.brent"].payload["points"] == pts[:2]
    assert collected["market.brent"].payload["points"] == pts


def test_reconstrucao_nao_enxerga_o_futuro():
    start = TODAY - timedelta(days=120)
    calm = [80.0] * 110
    shock = [160.0] * 10  # disparo só nos últimos 10 dias
    collected = {
        "market.brent": _fetched("market.brent", _daily(start, calm + shock)),
    }
    before = dict(backfill.reconstruct_day(collected, TODAY - timedelta(days=15)))
    after = dict(backfill.reconstruct_day(collected, TODAY - timedelta(days=1)))
    assert before["driver.ormuz_helio"] == pytest.approx(50.0)
    assert after["driver.ormuz_helio"] > 60.0
    assert after["iph"] > before["iph"]


def test_reconstrucao_entrega_indice_fatores_e_produtos():
    rows = dict(backfill.reconstruct_day({}, TODAY))
    assert {"iph", "iph_br", "coverage"} <= set(rows)
    for driver in DRIVERS:
        assert f"driver.{driver.key}" in rows
    assert "cat.gpu.proj30_br" in rows and "cat.gpu.proj30_global" in rows


# ---------------- gravação ----------------


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return history.init_db(tmp_path / "historico.db")


def _days(n: int) -> dict:
    return {
        TODAY - timedelta(days=i): [("iph", 50.0 + i), ("driver.cambio_br", 40.0)]
        for i in range(n, 0, -1)
    }


def _market(db, *days):
    """Marca dias com pregão: um ponto de sinal de mercado em cada data."""
    history.record_points(
        "signal.brent", [(f"{d.isoformat()}T12:00:00Z", 80.0) for d in days],
        kind="observed", path=db,
    )


def test_reconstrucao_preenche_buraco_entre_ciclos_ao_vivo(db):
    d = lambda n: TODAY - timedelta(days=n)  # noqa: E731
    for n in (5, 1):  # IPH ao vivo nos dias -5 e -1; buraco em -4..-2
        history.record_points("iph", [(f"{d(n).isoformat()}T18:00:00Z", 55.0)],
                              kind="modeled", path=db)
    _market(db, d(4), d(3), d(2))
    written = history.record_reconstruction(_days(5), "v1", path=db)
    assert written == 3 * 2  # dias -4, -3, -2; duas chaves cada
    assert history.reconstructed_days(["iph"], path=db) == {
        "iph": [d(4).isoformat(), d(3).isoformat(), d(2).isoformat()]
    }
    until = history.reconstructed_until(["iph"], path=db)
    assert until == {"iph": f"{d(2).isoformat()}T23:59:59Z"}


def test_dia_sem_pregao_repete_o_ultimo_iph_sem_recalcular(db):
    d = lambda n: TODAY - timedelta(days=n)  # noqa: E731
    history.record_points("iph", [(f"{d(4).isoformat()}T18:00:00Z", 55.0)],
                          kind="modeled", path=db)
    _market(db, d(4), d(1))  # -3 e -2 sem pregão; -1 com pregão
    history.record_reconstruction(_days(3), "v1", path=db)
    data = history.query(
        ["iph"], datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 5, tzinfo=timezone.utc), path=db,
    )
    # -3 e -2 repetem 55.0 (não o valor recalculado); -1 usa o recalculado.
    assert [v for _, v in data["iph"]] == [55.0, 55.0, 55.0, 51.0]
    assert history.reconstructed_days(["iph"], path=db)["iph"] == [
        d(3).isoformat(), d(2).isoformat(), d(1).isoformat()
    ]


def test_dia_com_pregao_abaixo_do_piso_de_cobertura_fica_lacuna(db):
    d = TODAY - timedelta(days=1)
    _market(db, d)
    rows = {d: [("iph", 50.0), ("coverage", 59.0)]}
    assert history.record_reconstruction(rows, "v1", path=db) == 0
    rows = {d: [("iph", 50.0), ("coverage", 60.0)]}
    assert history.record_reconstruction(rows, "v1", path=db) == 2


def test_mesma_versao_nao_refaz_e_versao_nova_substitui(db):
    assert history.record_reconstruction(_days(3), "v1", path=db) == 6
    changed = {d: [(k, v + 10) for k, v in rows] for d, rows in _days(3).items()}
    assert history.record_reconstruction(changed, "v1", path=db) == 0

    assert history.record_reconstruction(changed, "v2", path=db) == 6
    data = history.query(
        ["iph"],
        datetime(2026, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 5, tzinfo=timezone.utc),
        path=db,
    )
    assert [v for _, v in data["iph"]] == [63.0, 62.0, 61.0]


def test_reconstrucao_nunca_sobrescreve_ponto_ao_vivo(db):
    day = TODAY - timedelta(days=1)
    history.record_points("iph", [(f"{day.isoformat()}T23:59:59Z", 70.0)],
                          kind="modeled", path=db)
    assert history.record_reconstruction({day: [("iph", 10.0)]}, "v1", path=db) == 0
    assert history.reconstructed_until(["iph"], path=db) == {}


# ---------------- horizonte e janelas ----------------


def test_horizonte_de_30_dias_e_um_terco_da_calibracao():
    assert ranking.HORIZON_DAYS == 30
    collected = {
        "market.micron": _fetched("market.micron", _daily(TODAY - timedelta(days=60), [100.0] * 30 + [140.0] * 31)),
    }
    drivers = build_drivers(collected)
    brazil = build_brazil(collected)
    items = {i.key: i for i in ranking.build_ranking(drivers, brazil, collected)}
    gpu = next(c for c in ranking.CATEGORIES if c.key == "gpu")
    by_key = {d.key: d for d in drivers}
    betas = {k: v for k, v in gpu.betas.items() if k != "cambio_br"}
    total = sum(betas.values())
    dev = sum(b / total * (by_key[k].score - 50) / 50 for k, b in betas.items())
    assert items["gpu"].projected_global_30d_pct == pytest.approx(
        dev * gpu.sensitivity_pct / 3, abs=0.01
    )


def test_sinais_diarios_olham_30_dias_e_mensais_continuam_longos():
    daily = {"brent", "micron", "soxx", "tsmc", "nvda", "remx", "copper", "ptax",
             "taiwan_relative", "usd_twd", "fab_quakes"}
    for driver in DRIVERS:
        for s in driver.signals:
            if s.key in daily:
                assert s.window_days == 30, s.key
            if s.source.startswith(("comtrade.", "sec.")) or s.key in {"natgas", "igpm"}:
                assert s.window_days >= 180, s.key


def test_indice_nao_usa_contagem_de_noticias():
    for driver in DRIVERS:
        for sig in driver.signals:
            assert not sig.source.startswith("gdelt."), sig.key
            assert "noticiosa" not in sig.label, sig.key


def test_media_movel_diaria():
    pts = [("2026-10-01", 0.0), ("2026-10-02", 10.0), ("2026-10-03", 20.0), ("2026-10-10", 70.0)]
    out = trailing_mean(pts, 7)
    assert [v for _, v in out] == [0.0, 5.0, 10.0, 70.0]
    assert trailing_mean(pts, 0) == pts


# ---------------- fatores geopolíticos ----------------


def test_vetor_geopolitico_usa_dados_observados():
    geo = DRIVERS_BY_KEY["geopolitica_chips"]
    assert {s.source for s in geo.signals} == {
        "market.taiwan_index", "market.usd_twd", "usgs.fab_quakes", "fedreg.bis_chip_rules",
    }
    rel = next(s for s in geo.signals if s.key == "taiwan_relative")
    assert rel.relative_to == "market.soxx" and rel.invert
    quake = next(s for s in geo.signals if s.key == "fab_quakes")
    assert quake.mode == "peak" and quake.threshold == 5.5
    assert abs(sum(d.weight for d in DRIVERS) - 1.0) < 1e-9
    for driver in DRIVERS:
        assert abs(sum(s.weight for s in driver.signals) - 1.0) < 1e-9, driver.key


def test_bolsa_de_taiwan_relativa_ao_setor():
    twii = [["2026-10-01", 100.0], ["2026-10-02", 90.0], ["2026-10-03", 80.0]]
    soxx = [["2026-10-01", 50.0], ["2026-10-03", 50.0]]
    # Só datas presentes nas duas séries.
    assert ratio_series(twii, soxx) == [("2026-10-01", 2.0), ("2026-10-03", 1.6)]
    # Taiwan caindo contra o setor = pressão (sinal invertido).
    start = TODAY - timedelta(days=40)
    collected = {
        "market.taiwan_index": _fetched("market.taiwan_index", _daily(start, [100.0] * 15 + [85.0] * 26)),
        "market.soxx": _fetched("market.soxx", _daily(start, [50.0] * 41)),
    }
    geo = next(d for d in build_drivers(collected) if d.key == "geopolitica_chips")
    rel = next(s for s in geo.signals if s.key == "taiwan_relative")
    assert rel.change_pct == pytest.approx(15.0, abs=0.1)
    assert rel.score > 50
    # Sem a série do setor, não cai para a bolsa absoluta: fica sem sinal.
    alone = {"market.taiwan_index": collected["market.taiwan_index"]}
    geo2 = next(d for d in build_drivers(alone) if d.key == "geopolitica_chips")
    assert next(s for s in geo2.signals if s.key == "taiwan_relative").score is None


def test_terremoto_vira_pressao_so_acima_do_limiar():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 4, tzinfo=timezone.utc)
    events = [
        {"mag": 6.8, "time": datetime(2026, 9, 10, 3, tzinfo=timezone.utc)},
        {"mag": 5.7, "time": datetime(2026, 10, 20, 8, tzinfo=timezone.utc)},
        {"mag": 6.1, "time": datetime(2026, 10, 20, 9, tzinfo=timezone.utc)},
    ]
    series = usgs.daily_max_series(events, start, end)
    assert len(series) == (end.date() - start.date()).days + 1
    assert dict(series)["2026-10-20"] == 6.1  # maior do dia
    assert dict(series)["2026-10-21"] == 0.0  # dia sem evento é observação, não lacuna
    # Janela de 30 dias até 04/11 vê o 6,1 de outubro, não o 6,8 de setembro.
    assert window_peak(series, 30) == 6.1
    assert peak_score(5.0, 5.5, 1.0) == 50.0  # abaixo do limiar: neutro, nunca alívio
    assert peak_score(6.5, 5.5, 1.0) > 85.0


def test_series_ja_coletadas_entram_no_indice():
    sources = {s.source for d in DRIVERS for s in d.signals}
    assert {"comtrade.helium", "comtrade.processors", "fred.cpi_computers_us", "market.tsmc"} <= sources
    # TSMC é sinal próprio, não reserva do SOXX.
    soxx = next(s for s in DRIVERS_BY_KEY["alocacao_chips"].signals if s.key == "soxx")
    assert soxx.fallback_source is None


# ---------------- controles de exportação (Federal Register) ----------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Additions to the Entity List", 1.0),
        ("Revocation of Validated End-User Authorizations in the People's Republic of China", 1.0),
        ("Revisions to the Entity List", 0.5),
        ("Removal From the Entity List", -1.0),
        ("Extension of Authorized Integrated Circuit (IC) Designer Status", -1.0),
        ("Enhanced Favorable Treatment for the United Arab Emirates Under the EAR", None),
        ("Firearms export controls update", None),
    ],
)
def test_sentido_da_regra_do_bis(title, expected):
    assert fedreg.rule_direction(title) == expected


def test_regras_viram_pressao_liquida_na_janela():
    rules = [
        {"date": "2026-09-01", "direction": 1.0},
        {"date": "2026-10-20", "direction": 1.0},
        {"date": "2026-10-28", "direction": -1.0},
        {"date": "2026-10-28", "direction": 0.5},
    ]
    series = fedreg.daily_net_series(rules, date(2026, 8, 1), TODAY)
    assert dict(series)["2026-10-28"] == -0.5
    assert dict(series)["2026-10-29"] == 0.0
    # 30 dias até 04/11: 20/10 (+1) e 28/10 (−0,5); setembro fica fora.
    assert window_sum(series, 30) == 0.5

    collected = {"fedreg.bis_chip_rules": _fetched("fedreg.bis_chip_rules", [list(p) for p in series])}
    geo = next(d for d in build_drivers(collected) if d.key == "geopolitica_chips")
    sig = next(s for s in geo.signals if s.key == "bis_chip_rules")
    assert sig.latest == 0.5 and sig.change_pct is None
    assert 55 < sig.score < 70
    # Mês sem regra nenhuma é neutro, não ausência de dado.
    quiet = {"fedreg.bis_chip_rules": _fetched(
        "fedreg.bis_chip_rules", [list(p) for p in fedreg.daily_net_series([], date(2026, 8, 1), TODAY)]
    )}
    geo2 = next(d for d in build_drivers(quiet) if d.key == "geopolitica_chips")
    assert next(s for s in geo2.signals if s.key == "bis_chip_rules").score == 50.0
