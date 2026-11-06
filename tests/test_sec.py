"""SEC EDGAR XBRL — testes offline, sem rede.

Cobre a derivação do trimestre a partir dos acumulados do ano
(Q2 = H1 − Q1, Q3 = 9M − H1), a preferência pelo trimestre publicado
direto, a deduplicação por `filed` (a apresentação mais recente vence) e
a agregação por trimestre-calendário.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import sec  # noqa: E402


def _row(start, end, val, filed="2026-01-01"):
    return {"start": start, "end": end, "val": val, "filed": filed}


def _data(rows):
    return {"units": {"USD": rows}}


def _by_end(rows):
    return {r["end"]: r for r in rows}


def test_trimestre_derivado_dos_acumulados():
    rows = sec._flow_rows(
        _data(
            [
                _row("2026-01-01", "2026-03-31", 100),  # Q1
                _row("2026-01-01", "2026-06-30", 250),  # H1
                _row("2026-01-01", "2026-09-30", 450),  # 9M
            ]
        )
    )
    q = _by_end(rows)
    assert q["2026-03-31"]["val"] == pytest.approx(100)
    assert q["2026-06-30"]["val"] == pytest.approx(150)  # H1 − Q1
    assert q["2026-09-30"]["val"] == pytest.approx(200)  # 9M − H1
    assert q["2026-06-30"]["start"] == "2026-03-31"
    assert q["2026-03-31"]["direct"] is True
    assert q["2026-06-30"]["direct"] is False


def test_trimestre_publicado_direto_vence_o_derivado():
    rows = sec._flow_rows(
        _data(
            [
                _row("2026-01-01", "2026-03-31", 100),
                _row("2026-01-01", "2026-06-30", 250),
                _row("2026-04-01", "2026-06-30", 149),  # Q2 direto
            ]
        )
    )
    q2 = _by_end(rows)["2026-06-30"]
    assert q2["val"] == pytest.approx(149)
    assert q2["direct"] is True


def test_dedup_por_filed_fica_com_a_apresentacao_mais_recente():
    rows = sec._flow_rows(
        _data(
            [
                _row("2026-01-01", "2026-03-31", 90, filed="2026-04-20"),
                _row("2026-01-01", "2026-03-31", 100, filed="2026-07-25"),  # reapresentado
                _row("2026-01-01", "2026-03-31", 80, filed="2026-04-01"),
                _row("2026-01-01", "2026-06-30", 250, filed="2026-07-25"),
            ]
        )
    )
    q = _by_end(rows)
    assert q["2026-03-31"]["val"] == pytest.approx(100)
    assert q["2026-03-31"]["filed"] == "2026-07-25"
    assert q["2026-06-30"]["val"] == pytest.approx(150)


def test_comparacao_anual_e_acumulado_que_cai_nao_viram_trimestre():
    rows = sec._flow_rows(
        _data(
            [
                _row("2025-01-01", "2025-12-31", 900),  # anual: não deriva
                _row("2026-01-01", "2026-03-31", 300),
                _row("2026-01-01", "2026-06-30", 200),  # acumulado menor: para
                _row("2026-01-01", "2026-01-10", 5),  # curto demais
                _row(None, "2026-03-31", 1),
            ]
        )
    )
    assert [r["end"] for r in rows] == ["2026-03-31"]


def test_saldo_de_estoque_deduplica_por_filed():
    data = _data(
        [
            {"end": "2026-03-31", "val": 10, "filed": "2026-04-20"},
            {"end": "2026-03-31", "val": 12, "filed": "2026-07-25"},
            {"end": "2026-06-30", "val": 15, "filed": "2026-07-25"},
            {"start": "2026-01-01", "end": "2026-06-30", "val": 99},  # fluxo: fora
        ]
    )
    rows = sec._instant_rows(data)
    assert [(r["end"], r["val"]) for r in rows] == [("2026-03-31", 12), ("2026-06-30", 15)]


def test_agregacao_por_trimestre_calendario_e_ttm():
    a = [{"end": f"2025-{m:02d}-28", "val": 10} for m in (3, 6, 9, 12)]
    b = [{"end": f"2025-{m:02d}-30", "val": 1} for m in (3, 6, 9)]  # falta Q4
    quarters = sec._aggregate_quarters([a, b])
    assert [(q["key"], q["value"], q["count"]) for q in quarters] == [
        ((2025, 1), 11.0, 2),
        ((2025, 2), 11.0, 2),
        ((2025, 3), 11.0, 2),
        ((2025, 4), 10.0, 1),
    ]
    assert sec._rolling_ttm(quarters, min_companies=1) == [("2025-12-28", 43.0)]
    assert sec._rolling_ttm(quarters, min_companies=2) == []
