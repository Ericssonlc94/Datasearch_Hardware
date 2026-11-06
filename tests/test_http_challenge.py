"""Detecção de página anti-robô em `app/http.py` — testes offline, sem rede.

Usa `httpx.MockTransport` no lugar do cliente real. Política do projeto: a
página de bloqueio é detectada e vira falha visível; nunca é contornada nem
gravada no cache como dado.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import http  # noqa: E402

CHALLENGE = "<html><head><title>Just a moment...</title></head><body>cf-chl</body></html>"
CAPTCHA = "<html><body>Please solve the CAPTCHA to continue</body></html>"


@pytest.fixture
def servidor(monkeypatch):
    """Instala um transporte falso; devolve a lista de pedidos recebidos."""
    calls: list[httpx.Request] = []
    state: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return state["response"]()

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(http, "_client", http.build_client(transport=httpx.MockTransport(handler)))

    def responder(status, text, content_type):
        state["response"] = lambda: httpx.Response(
            status, text=text, headers={"content-type": content_type}
        )
        return calls

    return responder


def test_get_json_detecta_desafio_em_200_html(servidor):
    calls = servidor(200, CHALLENGE, "text/html; charset=utf-8")
    with pytest.raises(http.ChallengeDetected, match="just a moment"):
        asyncio.run(http.get_json("https://exemplo.test/api"))
    assert len(calls) == 1


def test_post_json_detecta_desafio_em_200_html(servidor):
    calls = servidor(200, CAPTCHA, "text/html")
    with pytest.raises(http.ChallengeDetected, match="captcha"):
        asyncio.run(http.post_json("https://exemplo.test/api", {"q": 1}))
    assert len(calls) == 1
    assert calls[0].method == "POST"


def test_get_text_detecta_desafio_mesmo_sem_content_type_html(servidor):
    servidor(200, "Access Denied - checking your browser", "text/plain")
    with pytest.raises(http.ChallengeDetected):
        asyncio.run(http.get_text("https://exemplo.test/feed"))


def test_desafio_e_um_fetch_error(servidor):
    servidor(200, CHALLENGE, "text/html")
    with pytest.raises(http.FetchError):
        asyncio.run(http.get_json("https://exemplo.test/api"))


def test_get_json_html_comum_falha_sem_virar_dado(servidor):
    servidor(200, "<html><body>Página institucional</body></html>", "text/html")
    with pytest.raises(http.FetchError, match="HTML onde se esperava JSON") as exc:
        asyncio.run(http.get_json("https://exemplo.test/api"))
    assert not isinstance(exc.value, http.ChallengeDetected)


def test_resposta_legitima_passa(servidor):
    servidor(200, '{"ok": true}', "application/json")
    assert asyncio.run(http.get_json("https://exemplo.test/api")) == {"ok": True}
    servidor(200, '{"id": 7}', "application/json")
    assert asyncio.run(http.post_json("https://exemplo.test/api", {})) == {"id": 7}
    servidor(200, "<rss><channel><title>Feed</title></channel></rss>", "application/rss+xml")
    assert "<rss>" in asyncio.run(http.get_text("https://exemplo.test/feed"))


def test_marcador_depois_do_inicio_do_corpo_nao_dispara(servidor):
    body = "<rss>" + "x" * (http._CHALLENGE_SCAN + 10) + "captcha</rss>"
    servidor(200, body, "application/rss+xml")
    assert asyncio.run(http.get_text("https://exemplo.test/feed")) == body


@pytest.mark.parametrize("status", [403, 429, 503])
def test_desafio_com_status_de_bloqueio_nao_repete(servidor, status):
    calls = servidor(status, CHALLENGE, "text/html")
    with pytest.raises(http.ChallengeDetected):
        asyncio.run(http.get_json("https://exemplo.test/api"))
    assert len(calls) == 1
