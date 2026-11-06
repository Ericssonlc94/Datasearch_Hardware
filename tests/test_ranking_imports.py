"""Importação por categoria no ranking (T11b) — testes offline, sem rede.

Cobre `ranking._imports` com `months` sintéticos (usd_per_kg crescente):
variação de 12 meses pelo mesmo AAAA-MM do ano anterior, FOB de 12 meses só
com a janela completa, série curta, chave ausente e a ordem de preferência
entre UN Comtrade mensal e Comex Stat, incluindo o rótulo `source`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.domain import ranking  # noqa: E402
from app.domain.catalog import CATEGORIES_BY_KEY  # noqa: E402

CAT = CATEGORIES_BY_KEY["ram"]

ROTULO_COMTRADE = "UN Comtrade (dado SECEX)"
ROTULO_COMEX = "Comex Stat (MDIC/SECEX)"


def _periodos(inicio: str, fim: str) -> list[str]:
    ano, mes = (int(x) for x in inicio.split("-"))
    fim_ano, fim_mes = (int(x) for x in fim.split("-"))
    out = []
    while (ano, mes) <= (fim_ano, fim_mes):
        out.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    return out


def _meses(inicio="2025-01", fim="2026-08", sem=(), fob_base=1000.0):
    """Série sintética: usd_per_kg cresce 1 por mês; FOB = fob_base + i."""
    out = []
    for i, p in enumerate(_periodos(inicio, fim)):
        if p in sem:
            continue
        out.append(
            {"period": p, "fob_usd": fob_base + i, "kg": 10.0, "usd_per_kg": 100.0 + i}
        )
    return out


def _fetched(prefixo: str, meses=None, status="ok") -> Fetched:
    return Fetched(
        key=f"{prefixo}.{CAT.key}",
        label="teste",
        provider="teste",
        url="local",
        status=status,
        payload={"months": meses, "sh6": CAT.sh6} if status in ("ok", "stale") else None,
    )


def _coletado(**fontes: Fetched) -> dict[str, Fetched]:
    return {f.key: f for f in fontes.values()}


def _sem_numeros(imp) -> None:
    assert imp.usd_per_kg is None
    assert imp.usd_per_kg_change_12m_pct is None
    assert imp.fob_usd_12m is None
    assert imp.period is None


def _por_periodo(meses):
    return {m["period"]: m for m in meses}


# 1. Série completa ----------------------------------------------------------


def test_serie_completa():
    meses = _meses()
    imp = ranking._imports(CAT, _coletado(c=_fetched("comtrade_monthly", meses)))
    p = _por_periodo(meses)

    assert imp.status == "ok"
    assert imp.period == "2026-08"
    assert imp.usd_per_kg == round(p["2026-08"]["usd_per_kg"], 2)
    esperado_var = (p["2026-08"]["usd_per_kg"] / p["2025-08"]["usd_per_kg"] - 1) * 100
    assert imp.usd_per_kg_change_12m_pct == pytest.approx(round(esperado_var, 2))
    janela = _periodos("2025-09", "2026-08")
    assert len(janela) == 12
    assert imp.fob_usd_12m == pytest.approx(sum(p[x]["fob_usd"] for x in janela))
    assert imp.ncm == CAT.sh6
    assert imp.source == ROTULO_COMTRADE


# 2. Sem o mês do ano anterior ----------------------------------------------


def test_sem_mes_do_ano_anterior_variacao_none():
    meses = _meses(sem={"2025-08"})
    imp = ranking._imports(CAT, _coletado(c=_fetched("comtrade_monthly", meses)))
    p = _por_periodo(meses)

    assert imp.period == "2026-08"
    assert imp.usd_per_kg_change_12m_pct is None
    # Antes (months[-13]) comparava com 2025-07; agora não compara com mês errado.
    janela = _periodos("2025-09", "2026-08")
    assert imp.fob_usd_12m == pytest.approx(sum(p[x]["fob_usd"] for x in janela))


# 3. Mês faltando dentro da janela ------------------------------------------


def test_mes_faltando_na_janela_fob_none():
    meses = _meses(sem={"2026-03"})
    imp = ranking._imports(CAT, _coletado(c=_fetched("comtrade_monthly", meses)))
    p = _por_periodo(meses)

    assert imp.period == "2026-08"
    esperado_var = (p["2026-08"]["usd_per_kg"] / p["2025-08"]["usd_per_kg"] - 1) * 100
    assert imp.usd_per_kg_change_12m_pct == pytest.approx(round(esperado_var, 2))
    assert imp.fob_usd_12m is None


# 4. Série curta --------------------------------------------------------------


def test_serie_curta():
    meses = _meses(inicio="2026-07", fim="2026-08")
    imp = ranking._imports(CAT, _coletado(c=_fetched("comtrade_monthly", meses)))

    assert imp.status == "ok"
    assert imp.period == "2026-08"
    assert imp.usd_per_kg == round(meses[-1]["usd_per_kg"], 2)
    assert imp.usd_per_kg_change_12m_pct is None
    assert imp.fob_usd_12m is None


# 5. Chave ausente -----------------------------------------------------------


def test_chave_ausente_unavailable():
    imp = ranking._imports(CAT, {})

    assert imp.status == "unavailable"
    _sem_numeros(imp)
    assert imp.source is None
    assert imp.ncm == CAT.sh6


# 6. Comtrade indisponível, Comex Stat ok -----------------------------------


def test_comtrade_indisponivel_usa_comex_stat():
    comex = _meses(fob_base=5000.0)
    imp = ranking._imports(
        CAT,
        _coletado(
            c=_fetched("comtrade_monthly", status="unavailable"),
            x=_fetched("comexstat", comex),
        ),
    )

    assert imp.status == "ok"
    assert imp.period == "2026-08"
    assert imp.source == ROTULO_COMEX
    janela = _periodos("2025-09", "2026-08")
    p = _por_periodo(comex)
    assert imp.fob_usd_12m == pytest.approx(sum(p[x]["fob_usd"] for x in janela))


# 7. Os dois ausentes ---------------------------------------------------------


def test_comtrade_indisponivel_e_comex_ausente_fica_unavailable():
    imp = ranking._imports(
        CAT, _coletado(c=_fetched("comtrade_monthly", status="unavailable"))
    )

    assert imp.status == "unavailable"
    _sem_numeros(imp)
    assert imp.source is None


def test_status_da_falha_e_mostrado():
    imp = ranking._imports(CAT, _coletado(c=_fetched("comtrade_monthly", status="disabled")))

    assert imp.status == "disabled"
    _sem_numeros(imp)


# 8. Os dois ok: Comtrade tem prioridade -------------------------------------


def test_os_dois_ok_comtrade_tem_prioridade():
    comtrade = _meses(fob_base=1000.0)
    comex = _meses(inicio="2025-01", fim="2026-09", fob_base=9000.0)
    imp = ranking._imports(
        CAT,
        _coletado(
            x=_fetched("comexstat", comex),  # ordem no dict não decide
            c=_fetched("comtrade_monthly", comtrade),
        ),
    )

    assert imp.source == ROTULO_COMTRADE
    assert imp.period == "2026-08"  # não o 2026-09 do Comex Stat
    janela = _periodos("2025-09", "2026-08")
    p = _por_periodo(comtrade)
    assert imp.fob_usd_12m == pytest.approx(sum(p[x]["fob_usd"] for x in janela))


def test_dado_stale_do_comtrade_ainda_tem_prioridade():
    imp = ranking._imports(
        CAT,
        _coletado(
            c=_fetched("comtrade_monthly", _meses(), status="stale"),
            x=_fetched("comexstat", _meses(fob_base=9000.0)),
        ),
    )

    assert imp.status == "stale"
    assert imp.source == ROTULO_COMTRADE
