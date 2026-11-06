"""Política de fontes — testes offline (nenhuma requisição de rede).

O que estes testes protegem: HTML de bloqueio nunca pode ser gravado no cache
como se fosse dado, e as fontes rejeitadas não voltam ao código por acidente.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.http as http  # noqa: E402
from app.http import ChallengeDetected, FetchError, reject_challenge  # noqa: E402
from app.providers import comexstat, fedreg, markets, usgs  # noqa: E402

FIXTURES = {
    "stooq": "<html><body>This site requires JavaScript to verify your browser</body></html>",
    "cloudflare": "<html><title>Just a moment...</title><div id='cf-chl-widget'></div></html>",
    "cloudflare_block": "<html><h1>Attention Required! | Cloudflare</h1></html>",
    "captcha": "<html><form action='/captcha'><h2>Prove you are human</h2></form></html>",
    "missing_key": "<html><body>Access Denied — missing_key.html</body></html>",
}


def _response(text: str, *, status: int = 200, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://exemplo.invalid/x"),
    )


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_reject_challenge_detecta_interstitials(name: str):
    with pytest.raises(ChallengeDetected):
        reject_challenge(FIXTURES[name], url="https://exemplo.invalid")


def test_reject_challenge_aceita_conteudo_legitimo():
    reject_challenge('{"data": [{"valor": 5.43}]}', url="https://exemplo.invalid")
    reject_challenge("date,close\n2026-11-01,123.4\n", url="https://exemplo.invalid")


def test_challenge_e_fetch_error():
    assert issubclass(ChallengeDetected, FetchError)


def test_get_json_rejeita_html(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method, url, **kw):
        return _response(FIXTURES["cloudflare"])

    monkeypatch.setattr(http, "_request", fake_request)
    with pytest.raises(ChallengeDetected):
        asyncio.run(http.get_json("https://exemplo.invalid/json"))


def test_get_json_rejeita_html_sem_marcador(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method, url, **kw):
        return _response("<html><body>erro interno</body></html>")

    monkeypatch.setattr(http, "_request", fake_request)
    with pytest.raises(FetchError) as exc:
        asyncio.run(http.get_json("https://exemplo.invalid/json"))
    assert "HTML" in str(exc.value)


def test_get_json_aceita_json(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method, url, **kw):
        return _response('{"ok": true}', content_type="application/json")

    monkeypatch.setattr(http, "_request", fake_request)
    assert asyncio.run(http.get_json("https://exemplo.invalid/json")) == {"ok": True}


def test_get_text_rejeita_challenge(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method, url, **kw):
        return _response(FIXTURES["stooq"])

    monkeypatch.setattr(http, "_request", fake_request)
    with pytest.raises(ChallengeDetected):
        asyncio.run(http.get_text("https://exemplo.invalid/csv"))


def test_post_json_rejeita_challenge(monkeypatch: pytest.MonkeyPatch):
    async def fake_request(method, url, **kw):
        return _response(FIXTURES["missing_key"])

    monkeypatch.setattr(http, "_request", fake_request)
    with pytest.raises(ChallengeDetected):
        asyncio.run(http.post_json("https://exemplo.invalid/post", {}))


# ---------------- fontes rejeitadas não voltam ----------------


def test_markets_nao_referencia_stooq():
    source = inspect.getsource(markets)
    # O docstring pode citar a fonte removida como histórico; o que não pode
    # existir é endpoint, constante ou parser dela.
    assert "stooq.com" not in source
    assert "STOOQ" not in source
    assert "_parse_stooq" not in source
    assert set(markets.TICKERS) == {
        "soxx", "nvda", "micron", "tsmc", "rare_earth", "brent", "copper", "usd_brl",
        "taiwan_index", "usd_twd",
        "dxy", "usd_mxn", "usd_clp", "usd_zar", "usd_cop", "vix",
    }
    # O contrato do ticker não carrega mais um símbolo alternativo.
    assert all(len(spec) == 3 for spec in markets.TICKERS.values())


def test_gdelt_foi_removido():
    root = Path(__file__).resolve().parents[1] / "app"
    assert not (root / "providers" / "gdelt.py").exists()
    for path in root.rglob("*.py"):
        imports = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        assert not any("gdelt" in line for line in imports), path


def test_usgs_e_federal_register_sao_publicos_e_sem_chave():
    for module, host in ((usgs, "https://earthquake.usgs.gov/"), (fedreg, "https://www.federalregister.gov/")):
        source = inspect.getsource(module)
        assert module.BASE.startswith(host)
        assert "api_key" not in source.lower() and "token" not in source.lower()


def test_comexstat_sem_headers_forjados():
    source = inspect.getsource(comexstat)
    assert '"Origin"' not in source
    assert '"Referer"' not in source
    assert "_HEADERS" not in source
