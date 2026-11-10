"""T42b/T42c/T43b (10/11/2026) — Comtrade e http.py, offline.

T42b: o ciclo mensal pede cada período uma vez para as 9 categorias e guarda
a falha; 429/403/disjuntor param o ciclo inteiro e abrem o disjuntor pelo
`Retry-After`. T42c: série anual pede só o último ano completo e lê os
anteriores do cache (mesmo vencido). T43b: timeout por provider e sem retry
em tempo esgotado para quem está em `http_no_retry_timeout`.

Substitui `test_falha_total_nao_fica_no_memo` de tests/test_comtrade_monthly.py
(a regra mudou: a falha agora fica no ciclo).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app import http  # noqa: E402
from app.domain.catalog import CATEGORIES  # noqa: E402
from app.http import FetchError  # noqa: E402
from app.providers import comtrade  # noqa: E402


class _Cache:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def peek(self, key):
        payload = self.entries.get(key)
        return None if payload is None else SimpleNamespace(payload=payload)


@pytest.fixture(autouse=True)
def _isola(monkeypatch):
    fixo = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)

    class _DataFixa(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixo if tz is not None else fixo.replace(tzinfo=None)

    monkeypatch.setattr(comtrade, "datetime", _DataFixa)
    monkeypatch.setattr(comtrade, "_monthly_memo", {})
    monkeypatch.setattr(comtrade, "_monthly_lock", asyncio.Lock())
    monkeypatch.setattr(comtrade, "_SPACING_S", 0)
    monkeypatch.setattr(comtrade, "cache", _Cache())
    monkeypatch.setattr(http, "_breakers", {})


class _Rede:
    def __init__(self, erro=None, falha_em=(), por_periodo=None):
        self.erro = erro
        self.falha_em = set(falha_em)
        self.por_periodo = por_periodo or {}
        self.chamadas: list[dict] = []
        self.kwargs: list[dict] = []

    async def __call__(self, url, params=None, **kw):
        self.chamadas.append(dict(params or {}))
        self.kwargs.append(kw)
        periodo = params["period"]
        if self.erro is not None and ("*" in self.falha_em or periodo in self.falha_em):
            raise self.erro
        if periodo in self.por_periodo:
            return {"data": self.por_periodo[periodo]}
        codigos = params["cmdCode"].split(",")
        return {"data": [{"cmdCode": c, "primaryValue": 1000, "netWgt": 10} for c in codigos]}


def _todas(rede, monkeypatch):
    monkeypatch.setattr(comtrade, "get_json", rede)
    todos = [c.sh6 for c in CATEGORIES]

    async def _run():
        return await asyncio.gather(
            *(
                comtrade.fetch_monthly_imports(c.key, c.sh6, c.label, todos)
                for c in CATEGORIES
            ),
            return_exceptions=True,
        )

    return asyncio.run(_run())


def _meses(sh6, periodos):
    return {
        "sh6": sh6,
        "months": [
            {"period": f"{p[:4]}-{p[4:]}", "fob_usd": 1.0, "kg": 1.0, "usd_per_kg": 1.0}
            for p in periodos
        ],
    }


# --- T42b -------------------------------------------------------------------


def test_concorrencia_um():
    assert comtrade._CONCURRENCY == 1


def test_cache_quente_nove_categorias_fazem_tres_pedidos(monkeypatch):
    periodos = comtrade._recent_periods()
    fechados = periodos[: -comtrade._TAIL_MONTHS]
    monkeypatch.setattr(
        comtrade,
        "cache",
        _Cache({f"comtrade_monthly.{c.key}": _meses(c.sh6, fechados) for c in CATEGORIES}),
    )
    rede = _Rede()
    res = _todas(rede, monkeypatch)
    assert all(not isinstance(r, BaseException) for r in res)
    assert len(rede.chamadas) == 3
    assert all(len(r.payload["months"]) == 16 for r in res)


def test_meses_fechados_diferentes_nao_repetem_a_cauda(monkeypatch):
    """Uma categoria sem histórico pede os fechados; a cauda sai uma vez só."""
    periodos = comtrade._recent_periods()
    fechados = periodos[: -comtrade._TAIL_MONTHS]
    entradas = {f"comtrade_monthly.{c.key}": _meses(c.sh6, fechados) for c in CATEGORIES}
    entradas.pop(f"comtrade_monthly.{CATEGORIES[-1].key}")
    monkeypatch.setattr(comtrade, "cache", _Cache(entradas))
    rede = _Rede()
    _todas(rede, monkeypatch)
    pedidos = [c["period"] for c in rede.chamadas]
    assert len(pedidos) == len(set(pedidos)) == 16


def test_429_para_o_ciclo_todo_com_um_pedido(monkeypatch):
    rede = _Rede(erro=FetchError("HTTP 429", status_code=429, retry_after=120.0), falha_em={"*"})
    res = _todas(rede, monkeypatch)
    assert len(rede.chamadas) == 1
    assert all(isinstance(r, ValueError) for r in res)
    aberto = http._breakers["comtrade"].open_until
    import time

    assert 100 < aberto - time.monotonic() <= 120


def test_429_sem_retry_after_usa_o_padrao(monkeypatch):
    rede = _Rede(erro=FetchError("HTTP 429", status_code=429), falha_em={"*"})
    _todas(rede, monkeypatch)
    import time

    restante = http._breakers["comtrade"].open_until - time.monotonic()
    assert comtrade._RATE_FALLBACK_S - 5 < restante <= comtrade._RATE_FALLBACK_S


def test_erro_comum_de_um_mes_nao_e_repetido_no_ciclo(monkeypatch):
    alvo = comtrade._recent_periods()[-1]
    rede = _Rede(erro=RuntimeError("timeout"), falha_em={alvo})
    res = _todas(rede, monkeypatch)
    assert all(not isinstance(r, BaseException) for r in res)
    assert [c["period"] for c in rede.chamadas].count(alvo) == 1
    assert len(rede.chamadas) == 16


def test_falha_total_fica_no_ciclo_e_vence_depois(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(comtrade.time, "monotonic", lambda: agora[0])
    rede = _Rede(erro=RuntimeError("x"), falha_em={"*"})
    monkeypatch.setattr(comtrade, "get_json", rede)

    def _uma():
        return asyncio.run(comtrade.fetch_monthly_imports("memory", "854232", "M", ["854232"]))

    with pytest.raises(ValueError, match="nenhum mês"):
        _uma()
    with pytest.raises(ValueError, match="nenhum mês"):
        _uma()
    assert len(rede.chamadas) == 16  # a segunda leu a falha do ciclo

    agora[0] += comtrade._CYCLE_S + 1
    rede.erro = None
    assert _uma().status == "ok"
    assert len(rede.chamadas) == 32


def test_get_passa_o_provider(monkeypatch):
    rede = _Rede()
    monkeypatch.setattr(comtrade, "get_json", rede)
    asyncio.run(comtrade.fetch_monthly_imports("memory", "854232", "M", ["854232"]))
    assert all(kw.get("provider") == "comtrade" for kw in rede.kwargs)


# --- T42c -------------------------------------------------------------------


def _anual(hs, anos):
    return {
        "hs_code": hs,
        "totals": [[str(a), 100.0 * (a - 2000)] for a in anos],
        "unit_values": [[str(a), 1.0 * (a - 2000)] for a in anos],
    }


def test_anual_com_cache_pede_so_o_ultimo_ano(monkeypatch):
    monkeypatch.setattr(comtrade, "cache", _Cache({"comtrade.memory": _anual("854232", [2022, 2023, 2024])}))
    rede = _Rede()
    monkeypatch.setattr(comtrade, "get_json", rede)
    got = asyncio.run(comtrade.fetch_flow("memory"))
    assert [c["period"] for c in rede.chamadas] == ["2025"]
    assert [y for y, _ in got.payload["totals"]] == ["2022", "2023", "2024", "2025"]
    assert got.payload["totals"][0][1] == pytest.approx(2200.0)


def test_anual_sem_cache_pede_os_quatro(monkeypatch):
    rede = _Rede()
    monkeypatch.setattr(comtrade, "get_json", rede)
    asyncio.run(comtrade.fetch_flow("memory"))
    assert [c["period"] for c in rede.chamadas] == ["2022", "2023", "2024", "2025"]


def test_anual_ultimo_ano_vazio_mantem_o_valor_anterior(monkeypatch):
    monkeypatch.setattr(
        comtrade, "cache", _Cache({"comtrade.memory": _anual("854232", [2022, 2023, 2024, 2025])})
    )
    rede = _Rede(por_periodo={"2025": []})
    monkeypatch.setattr(comtrade, "get_json", rede)
    got = asyncio.run(comtrade.fetch_flow("memory"))
    assert len(rede.chamadas) == 1
    assert dict(got.payload["totals"])["2025"] == pytest.approx(2500.0)


def test_anual_cache_de_outro_sh_nao_serve(monkeypatch):
    monkeypatch.setattr(comtrade, "cache", _Cache({"comtrade.memory": _anual("999999", [2022, 2023, 2024])}))
    rede = _Rede()
    monkeypatch.setattr(comtrade, "get_json", rede)
    asyncio.run(comtrade.fetch_flow("memory"))
    assert len(rede.chamadas) == 4


def test_anual_429_para_e_abre_disjuntor(monkeypatch):
    rede = _Rede(erro=FetchError("HTTP 429", status_code=429, retry_after=30.0), falha_em={"*"})
    monkeypatch.setattr(comtrade, "get_json", rede)

    async def _run():
        return await asyncio.gather(
            *(comtrade.fetch_flow(k) for k in comtrade.COMMODITIES), return_exceptions=True
        )

    res = asyncio.run(_run())
    assert len(rede.chamadas) == 1  # os outros viram o disjuntor aberto
    assert all(isinstance(r, ValueError) for r in res)


# --- T43b -------------------------------------------------------------------


def _cliente(monkeypatch, handler):
    monkeypatch.setattr(http, "_client", http.build_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(http.asyncio, "sleep", _sem_espera)


async def _sem_espera(_s):
    return None


def test_timeout_sem_retry_para_provider_marcado(monkeypatch):
    monkeypatch.setattr(http.settings, "http_no_retry_timeout", "comtrade")
    chamadas = []

    def handler(req):
        chamadas.append(req)
        raise httpx.ReadTimeout("lento", request=req)

    _cliente(monkeypatch, handler)
    with pytest.raises(FetchError):
        asyncio.run(http.get_json("https://example.org/x", provider="comtrade"))
    assert len(chamadas) == 1


def test_timeout_com_retry_sem_provider(monkeypatch):
    monkeypatch.setattr(http.settings, "http_no_retry_timeout", "comtrade")
    chamadas = []

    def handler(req):
        chamadas.append(req)
        raise httpx.ReadTimeout("lento", request=req)

    _cliente(monkeypatch, handler)
    with pytest.raises(FetchError):
        asyncio.run(http.get_json("https://example.org/x"))
    assert len(chamadas) == http.settings.http_retries + 1


def test_timeout_do_provider_vai_no_pedido(monkeypatch):
    monkeypatch.setattr(http.settings, "http_timeout_providers", "comtrade=60")
    vistos = []

    def handler(req):
        vistos.append(req.extensions.get("timeout"))
        return httpx.Response(200, json={"ok": True})

    _cliente(monkeypatch, handler)
    asyncio.run(http.get_json("https://example.org/x", provider="comtrade"))
    asyncio.run(http.get_json("https://example.org/x"))
    assert vistos[0]["read"] == 60
    assert vistos[1]["read"] == http.settings.http_timeout
