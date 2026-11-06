"""UN Comtrade mensal (T05) — testes offline, sem rede.

Cobre `comtrade.fetch_monthly_imports` com `get_json` substituído por dado
local: soma de várias linhas do mesmo SH6 e mês, mês com peso 0 fora da série,
SH6 sem dado levantando erro, ordem e formato AAAA-MM, uma única rodada de
coleta para as 10 categorias do catálogo (memo), falha não memorizada e a
virada de ano em `_recent_periods`.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.catalog import CATEGORIES  # noqa: E402
from app.providers import comtrade  # noqa: E402


def _congela_data(monkeypatch, ano: int, mes: int, dia: int = 15) -> None:
    """Fixa `datetime.now` dentro do provider (o resto de datetime segue igual)."""
    fixo = datetime(ano, mes, dia, 12, 0, tzinfo=timezone.utc)

    class _DataFixa(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401 — assinatura de datetime.now
            return fixo if tz is not None else fixo.replace(tzinfo=None)

    monkeypatch.setattr(comtrade, "datetime", _DataFixa)


@pytest.fixture(autouse=True)
def _isola_provider(monkeypatch):
    """Memo limpo, sem espera entre chamadas e data fixa em 04/11/2026."""
    monkeypatch.setattr(comtrade, "_monthly_memo", {})
    monkeypatch.setattr(comtrade, "_SPACING_S", 0)
    # Lock novo por teste (Python >= 3.10 só liga o lock ao loop no primeiro uso).
    monkeypatch.setattr(comtrade, "_monthly_lock", asyncio.Lock())
    _congela_data(monkeypatch, 2026, 11, 4)


def _linha(sh6: str, fob, kg) -> dict:
    return {"cmdCode": sh6, "primaryValue": fob, "netWgt": kg}


class _RedeFalsa:
    """Substitui `get_json`: devolve linhas por período e conta as chamadas."""

    def __init__(self, por_periodo=None, padrao=None, falha_em=()):
        self.por_periodo = por_periodo or {}
        self.padrao = padrao  # função (período, códigos) -> linhas
        self.falha_em = set(falha_em)
        self.chamadas: list[dict] = []

    async def __call__(self, url, params=None, **kwargs):
        self.chamadas.append({"url": url, **(params or {})})
        periodo = params["period"]
        if periodo in self.falha_em or "*" in self.falha_em:
            raise RuntimeError("HTTP 429")
        if periodo in self.por_periodo:
            return {"data": self.por_periodo[periodo]}
        if self.padrao is not None:
            return {"data": self.padrao(periodo, params["cmdCode"].split(","))}
        return {"data": []}


def _instala(monkeypatch, rede: _RedeFalsa) -> None:
    monkeypatch.setattr(comtrade, "get_json", rede)


def _coleta(sh6: str, all_sh6: list[str] | None = None, chave: str = "memory"):
    async def _run():
        return await comtrade.fetch_monthly_imports(chave, sh6, "Memória", all_sh6 or [sh6])

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# 1. Soma de linhas
# ---------------------------------------------------------------------------


def test_varias_linhas_do_mesmo_mes_sao_somadas(monkeypatch):
    rede = _RedeFalsa(
        por_periodo={
            "202608": [
                _linha("854232", 1000, 10),
                _linha("854232", 500, 15),
                _linha("847130", 9999, 1),  # outro SH6 não entra na soma
            ]
        }
    )
    _instala(monkeypatch, rede)

    res = _coleta("854232", ["854232", "847130"])

    assert res.status == "ok"
    assert res.key == "comtrade_monthly.memory"
    meses = res.payload["months"]
    assert meses == [
        {"period": "2026-08", "fob_usd": 1500.0, "kg": 25.0, "usd_per_kg": 60.0}
    ]
    assert res.payload["sh6"] == "854232"
    assert res.as_of == datetime(2026, 8, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 2. Peso zero fica de fora
# ---------------------------------------------------------------------------


def test_mes_com_peso_zero_ou_ausente_fica_fora(monkeypatch):
    rede = _RedeFalsa(
        por_periodo={
            "202606": [_linha("854232", 1000, 0)],  # peso zero
            "202607": [_linha("854232", 1000, None)],  # peso ausente
            "202608": [_linha("854232", 800, 4)],
        }
    )
    _instala(monkeypatch, rede)

    meses = _coleta("854232").payload["months"]

    assert [m["period"] for m in meses] == ["2026-08"]
    assert meses[0]["usd_per_kg"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# 3. SH6 ausente
# ---------------------------------------------------------------------------


def test_sh6_sem_dado_levanta_value_error(monkeypatch):
    rede = _RedeFalsa(por_periodo={"202608": [_linha("847130", 1000, 10)]})
    _instala(monkeypatch, rede)

    with pytest.raises(ValueError, match="854232"):
        _coleta("854232", ["854232", "847130"])


def test_sh6_so_com_peso_zero_tambem_levanta_erro(monkeypatch):
    rede = _RedeFalsa(
        por_periodo={"202608": [_linha("854232", 1000, 0), _linha("847130", 100, 1)]}
    )
    _instala(monkeypatch, rede)

    with pytest.raises(ValueError, match="854232"):
        _coleta("854232", ["854232", "847130"])


# ---------------------------------------------------------------------------
# 4. Ordem e formato AAAA-MM
# ---------------------------------------------------------------------------


def test_meses_em_ordem_crescente_no_formato_aaaa_mm(monkeypatch):
    # Os 16 meses cruzam a virada 2025→2026: a saída tem de ser cronológica
    # e no formato AAAA-MM (com hífen), não AAAAMM como na consulta.
    def _padrao(periodo, codigos):
        return [_linha("854232", int(periodo), 1)]

    rede = _RedeFalsa(padrao=_padrao)
    _instala(monkeypatch, rede)

    meses = _coleta("854232").payload["months"]
    periodos = [m["period"] for m in meses]

    assert len(periodos) == 16
    assert periodos == sorted(periodos)
    assert periodos[0] == "2025-07"
    assert periodos[-1] == "2026-10"
    assert "2025-12" in periodos and "2026-01" in periodos
    assert all(len(p) == 7 and p[4] == "-" for p in periodos)


def test_parametros_da_chamada(monkeypatch):
    rede = _RedeFalsa(por_periodo={"202608": [_linha("854232", 10, 1)]})
    _instala(monkeypatch, rede)

    _coleta("854232", ["847130", "854232", "847130"])

    assert len(rede.chamadas) == 16
    primeira = rede.chamadas[0]
    assert primeira["url"] == comtrade.MONTHLY_BASE
    assert primeira["reporterCode"] == "76"
    assert primeira["partnerCode"] == "0"
    assert primeira["flowCode"] == "M"
    # Códigos sem repetição e ordenados, numa só chamada.
    assert primeira["cmdCode"] == "847130,854232"


# ---------------------------------------------------------------------------
# 5. Memo: uma rodada de rede para as 10 categorias
# ---------------------------------------------------------------------------


def test_dez_categorias_compartilham_uma_unica_rodada(monkeypatch):
    todos = [c.sh6 for c in CATEGORIES]
    assert len(CATEGORIES) == 10

    def _padrao(periodo, codigos):
        return [_linha(c, 1000, 10) for c in codigos]

    rede = _RedeFalsa(padrao=_padrao)
    _instala(monkeypatch, rede)

    async def _run():
        return [
            await comtrade.fetch_monthly_imports(c.key, c.sh6, c.label, todos)
            for c in CATEGORIES
        ]

    resultados = asyncio.run(_run())

    assert len(rede.chamadas) == 16  # 16 meses, uma vez só
    assert len({ch["period"] for ch in rede.chamadas}) == 16
    assert all(r.status == "ok" for r in resultados)
    assert {r.key for r in resultados} == {f"comtrade_monthly.{c.key}" for c in CATEGORIES}
    for c, r in zip(CATEGORIES, resultados):
        assert r.payload["sh6"] == c.sh6
        assert len(r.payload["months"]) == 16


def test_categorias_em_paralelo_tambem_fazem_uma_rodada(monkeypatch):
    todos = [c.sh6 for c in CATEGORIES]

    def _padrao(periodo, codigos):
        return [_linha(c, 1000, 10) for c in codigos]

    rede = _RedeFalsa(padrao=_padrao)
    _instala(monkeypatch, rede)

    async def _run():
        return await asyncio.gather(
            *(comtrade.fetch_monthly_imports(c.key, c.sh6, c.label, todos) for c in CATEGORIES)
        )

    resultados = asyncio.run(_run())

    assert len(rede.chamadas) == 16
    assert all(r.status == "ok" for r in resultados)


# ---------------------------------------------------------------------------
# 6. Falha não é memorizada
# ---------------------------------------------------------------------------


def test_falha_total_nao_fica_no_memo(monkeypatch):
    quebrada = _RedeFalsa(falha_em={"*"})
    _instala(monkeypatch, quebrada)

    with pytest.raises(ValueError, match="nenhum mês retornou dados"):
        _coleta("854232")
    assert len(quebrada.chamadas) == 16
    assert comtrade._monthly_memo == {}

    boa = _RedeFalsa(por_periodo={"202608": [_linha("854232", 100, 2)]})
    _instala(monkeypatch, boa)

    res = _coleta("854232")

    assert len(boa.chamadas) == 16  # tentou de novo, não leu falha do memo
    assert res.payload["months"][0]["usd_per_kg"] == pytest.approx(50.0)


def test_mes_com_erro_nao_derruba_a_serie(monkeypatch):
    rede = _RedeFalsa(
        por_periodo={
            "202607": [_linha("854232", 100, 1)],
            "202608": [_linha("854232", 300, 1)],
        },
        falha_em={"202606"},
    )
    _instala(monkeypatch, rede)

    meses = _coleta("854232").payload["months"]

    assert [m["period"] for m in meses] == ["2026-07", "2026-08"]


# ---------------------------------------------------------------------------
# 7. Virada de ano em _recent_periods
# ---------------------------------------------------------------------------


def test_recent_periods_em_janeiro_termina_em_dezembro_do_ano_anterior(monkeypatch):
    _congela_data(monkeypatch, 2026, 1, 10)

    periodos = comtrade._recent_periods()

    assert len(periodos) == 16
    assert periodos[-1] == "202512"
    assert periodos[0] == "202409"
    assert periodos == sorted(periodos)


def test_recent_periods_em_fevereiro_cruza_dezembro_para_janeiro(monkeypatch):
    _congela_data(monkeypatch, 2026, 2, 1)

    periodos = comtrade._recent_periods(3)

    assert periodos == ["202511", "202512", "202601"]


def test_recent_periods_nunca_gera_mes_13_ou_00(monkeypatch):
    for mes in range(1, 13):
        _congela_data(monkeypatch, 2026, mes, 15)
        for p in comtrade._recent_periods(30):
            assert len(p) == 6
            assert 1 <= int(p[4:]) <= 12
