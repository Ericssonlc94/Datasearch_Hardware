"""Defesas de rede da T09 em `app/http.py` e `app/providers/news_rss.py` — sem rede.

Cobre o teto de corpo (`ResponseTooLarge`), o filtro de redirecionamento
(`RedirectRefused` e `max_redirects`), o tempo total por tentativa, a
separação entre mensagem e trecho do corpo em `FetchError`, o descarte de
links inseguros no RSS e a recusa de expat antiga. O cliente é sempre o de
`http.build_client`, com `httpx.MockTransport`: as defesas ficam ativas e
nenhum pedido sai da máquina. A resolução de nomes é falsa.
"""

from __future__ import annotations

import asyncio
import gzip
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import http  # noqa: E402
from app.providers import news_rss  # noqa: E402

# `http.asyncio` é o próprio módulo asyncio: o fixture anula `asyncio.sleep`
# para todos. O corpo lento do caso (8) precisa do sleep verdadeiro.
_SLEEP_REAL = asyncio.sleep

# Nomes conhecidos pelo resolvedor falso; o resto "não resolve".
_DNS = {
    "localhost": "127.0.0.1",
    "interno.test": "10.0.0.5",
    "publico.test": "93.184.216.34",
    "exemplo.test": "93.184.216.35",
}


async def _getaddrinfo_falso(self, host, port, *_a, **_k):
    ip = _DNS.get(host)
    if ip is None:
        raise socket.gaierror(f"nome desconhecido no teste: {host}")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]


@pytest.fixture
def servidor(monkeypatch):
    """Instala transporte e DNS falsos; devolve `instalar(handler) -> pedidos`."""
    calls: list[httpx.Request] = []

    async def no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(http.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop, "getaddrinfo", _getaddrinfo_falso
    )

    def instalar(handler):
        async def registra(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            out = handler(request)
            if asyncio.iscoroutine(out):
                out = await out
            return out

        monkeypatch.setattr(
            http, "_client", http.build_client(transport=httpx.MockTransport(registra))
        )
        return calls

    return instalar


def _em_pedacos(total: int, pedaco: int = 1024):
    async def gerador():
        enviado = 0
        while enviado < total:
            n = min(pedaco, total - enviado)
            enviado += n
            yield b"x" * n

    return gerador()


# (1) Content-Length declarado acima do teto


def test_content_length_acima_do_teto_falha_sem_repetir(servidor):
    calls = servidor(lambda r: httpx.Response(200, content=b"x" * 500))
    with pytest.raises(http.ResponseTooLarge, match="Content-Length 500"):
        asyncio.run(http.get_json("https://exemplo.test/api", max_bytes=100))
    assert len(calls) == 1


def test_teto_padrao_vale_para_content_length(servidor):
    # Com o teto padrão (20 MB) só o cabeçalho é grande: o corpo é curto.
    calls = servidor(
        lambda r: httpx.Response(
            200,
            content=b"{}",
            headers={"content-length": str(http.MAX_BODY_BYTES + 1)},
        )
    )
    with pytest.raises(http.ResponseTooLarge):
        asyncio.run(http.get_json("https://exemplo.test/api"))
    assert len(calls) == 1


# (2) Corpo em streaming acima do teto, sem Content-Length


def test_streaming_sem_content_length_acima_do_teto(servidor):
    def handler(_r):
        resp = httpx.Response(200, content=_em_pedacos(5000))
        assert "content-length" not in resp.headers
        return resp

    calls = servidor(handler)
    with pytest.raises(http.ResponseTooLarge, match="corpo acima do teto"):
        asyncio.run(http.get_json("https://exemplo.test/api", max_bytes=1000))
    assert len(calls) == 1


def test_streaming_dentro_do_teto_passa(servidor):
    servidor(lambda r: httpx.Response(200, content=_em_pedacos(900, 100)))
    assert asyncio.run(http.get_text("https://exemplo.test/feed", max_bytes=1000)) == "x" * 900


# (3) get_text(max_bytes=...) respeita o teto


def test_get_text_respeita_max_bytes(servidor):
    servidor(lambda r: httpx.Response(200, text="<rss>" + "a" * 300 + "</rss>"))
    with pytest.raises(http.ResponseTooLarge):
        asyncio.run(http.get_text("https://exemplo.test/feed", max_bytes=200))
    assert "<rss>" in asyncio.run(http.get_text("https://exemplo.test/feed", max_bytes=400))


def test_feed_rss_usa_teto_proprio(servidor, monkeypatch):
    monkeypatch.setattr(news_rss, "_MAX_FEED_BYTES", 64)
    servidor(lambda r: httpx.Response(200, content=_em_pedacos(1000)))
    feed = news_rss.Feed("Teste", "https://exemplo.test/feed", "en")
    with pytest.raises(http.ResponseTooLarge):
        asyncio.run(news_rss._fetch_feed(feed, 10))


# (4) gzip continua decodificado


def test_gzip_continua_decodificado(servidor):
    original = b'{"ok": true, "texto": "' + b"abc" * 200 + b'"}'
    servidor(
        lambda r: httpx.Response(
            200,
            content=gzip.compress(original),
            headers={"content-encoding": "gzip", "content-type": "application/json"},
        )
    )
    dado = asyncio.run(http.get_json("https://exemplo.test/api"))
    assert dado["ok"] is True and dado["texto"] == "abc" * 200


def test_gzip_bomba_para_no_teto_descomprimido(servidor):
    comprimido = gzip.compress(b"\0" * 200_000)
    assert len(comprimido) < 1000
    calls = servidor(
        lambda r: httpx.Response(
            200, content=comprimido, headers={"content-encoding": "gzip"}
        )
    )
    with pytest.raises(http.ResponseTooLarge):
        asyncio.run(http.get_text("https://exemplo.test/feed", max_bytes=10_000))
    assert len(calls) == 1


# (5) Redirecionamento recusado: um pedido só, sem retry


@pytest.mark.parametrize(
    "destino",
    [
        "http://publico.test/feed",  # sai de https
        "https://10.1.2.3/feed",  # IP privado
        "https://192.168.0.1/feed",  # IP privado
        "https://127.0.0.1/feed",  # loopback
        "https://[::1]/feed",  # loopback IPv6
        "https://169.254.169.254/latest/meta-data/",  # link-local (metadados de nuvem)
        "https://localhost/feed",  # nome que resolve para loopback
        "https://interno.test/feed",  # nome que resolve para IP privado
    ],
)
def test_redirect_inseguro_recusado_com_um_pedido(servidor, destino):
    calls = servidor(lambda r: httpx.Response(302, headers={"location": destino}))
    with pytest.raises(http.RedirectRefused):
        asyncio.run(http.get_text("https://exemplo.test/feed"))
    assert len(calls) == 1


def test_redirect_relativo_continua_https_e_segue(servidor):
    def handler(r):
        if r.url.path == "/velho":
            return httpx.Response(301, headers={"location": "/novo"})
        return httpx.Response(200, text="ok")

    calls = servidor(handler)
    assert asyncio.run(http.get_text("https://exemplo.test/velho")) == "ok"
    assert [str(c.url) for c in calls] == [
        "https://exemplo.test/velho",
        "https://exemplo.test/novo",
    ]


# (6) Redirecionamento https público segue


def test_redirect_https_publico_segue(servidor):
    def handler(r):
        if r.url.host == "exemplo.test":
            return httpx.Response(301, headers={"location": "https://publico.test/feed.xml"})
        return httpx.Response(200, text="<rss/>")

    calls = servidor(handler)
    assert asyncio.run(http.get_text("https://exemplo.test/feed")) == "<rss/>"
    assert [c.url.host for c in calls] == ["exemplo.test", "publico.test"]


def test_redirect_para_ip_publico_literal_segue(servidor):
    def handler(r):
        if r.url.host == "exemplo.test":
            return httpx.Response(302, headers={"location": "https://93.184.216.34/x"})
        return httpx.Response(200, text="ok")

    servidor(handler)
    assert asyncio.run(http.get_text("https://exemplo.test/feed")) == "ok"


# (7) Mais de 5 redirecionamentos vira FetchError


def test_mais_de_cinco_redirects_vira_fetch_error(servidor):
    def handler(r):
        n = int(r.url.params.get("n", "0"))
        return httpx.Response(302, headers={"location": f"https://publico.test/r?n={n + 1}"})

    calls = servidor(handler)
    with pytest.raises(http.FetchError, match="TooManyRedirects") as exc:
        asyncio.run(http.get_text("https://exemplo.test/r?n=0"))
    assert not isinstance(exc.value, http.RedirectRefused)
    # Nenhuma tentativa passa de 1 pedido original + 5 redirecionamentos.
    tentativas = [c for c in calls if c.url.host == "exemplo.test"]
    assert len(tentativas) == 1 + http.settings.http_retries
    assert len(calls) == len(tentativas) * (1 + 5)


def test_cinco_redirects_ainda_seguem(servidor):
    def handler(r):
        n = int(r.url.params.get("n", "0"))
        if n < 5:
            return httpx.Response(302, headers={"location": f"https://publico.test/r?n={n + 1}"})
        return httpx.Response(200, text="fim")

    calls = servidor(handler)
    assert asyncio.run(http.get_text("https://exemplo.test/r?n=0")) == "fim"
    assert len(calls) == 6


# (8) Corpo lento: tempo total por tentativa


def test_corpo_lento_estoura_tempo_total(servidor, monkeypatch):
    monkeypatch.setattr(http.settings, "http_timeout", 0.1)

    async def gotejando():
        for _ in range(100):
            yield b"x"
            await _SLEEP_REAL(0.05)

    calls = servidor(lambda r: httpx.Response(200, content=gotejando()))
    inicio = time.monotonic()
    with pytest.raises(http.FetchError, match="tempo total") as exc:
        asyncio.run(http.get_text("https://exemplo.test/feed"))
    decorrido = time.monotonic() - inicio
    assert type(exc.value) is http.FetchError
    assert len(calls) == 1 + http.settings.http_retries
    assert decorrido < 2.0


def test_timeout_explicito_define_o_tempo_total(servidor, monkeypatch):
    # `timeout=` no pedido manda no teto (2x a fase), não o settings.
    monkeypatch.setattr(http.settings, "http_retries", 0)

    async def gotejando():
        for _ in range(100):
            yield b"x"
            await _SLEEP_REAL(0.05)

    servidor(lambda r: httpx.Response(200, content=gotejando()))
    inicio = time.monotonic()
    with pytest.raises(http.FetchError, match="tempo total"):
        asyncio.run(http.get_text("https://exemplo.test/feed", timeout=0.1))
    assert time.monotonic() - inicio < 1.0


# (9) Mensagem do FetchError sem o corpo de terceiro


@pytest.mark.parametrize(
    "content_type, corpo",
    [
        ("text/plain", "SEGREDO-DO-CORPO não é json"),
        ("text/html", "<html><body>SEGREDO-DO-CORPO pagina comum</body></html>"),
    ],
)
def test_fetch_error_guarda_corpo_fora_da_mensagem(servidor, content_type, corpo):
    servidor(lambda r: httpx.Response(200, text=corpo, headers={"content-type": content_type}))
    with pytest.raises(http.FetchError) as exc:
        asyncio.run(http.get_json("https://exemplo.test/api"))
    assert "SEGREDO-DO-CORPO" not in str(exc.value)
    assert "SEGREDO-DO-CORPO" in exc.value.body_snippet
    assert "exemplo.test/api" in str(exc.value)
    assert "200" in str(exc.value)


# (10) _parse_feed só aceita link http(s) com host


_AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _item(link: str, titulo: str) -> str:
    return (
        f"<item><title>{titulo}</title><link>{link}</link>"
        "<pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate></item>"
    )


def test_parse_feed_descarta_links_inseguros():
    itens = [
        ("javascript:alert(1)", "GPU prices rise on tariffs A"),
        ("JaVa\tScript:alert(1)", "GPU prices rise on tariffs B"),
        ("data:text/html;base64,PHNjcmlwdD4=", "GPU prices rise on tariffs C"),
        ("https:///sem-host", "GPU prices rise on tariffs D"),
        ("https://www.exemplo.test/gpu-prices", "GPU prices rise on tariffs E"),
    ]
    xml = (
        "<rss><channel><language>en</language>"
        + "".join(_item(link, titulo) for link, titulo in itens)
        + "</channel></rss>"
    )
    feed = news_rss.Feed("Teste", "https://exemplo.test/feed", "en")
    artigos = news_rss._parse_feed(xml, feed, 10, now=_AGORA)
    assert [a["url"] for a in artigos] == ["https://www.exemplo.test/gpu-prices"]
    assert artigos[0]["domain"] == "exemplo.test"


@pytest.mark.parametrize(
    "link",
    ["javascript:alert(1)", "JaVa\tScript:alert(1)", "data:,oi", "https:", "ftp://exemplo.test/x", ""],
)
def test_safe_link_recusa(link):
    assert news_rss._safe_link(link) == ""


def test_safe_link_aceita_http_e_https():
    assert news_rss._safe_link("https://exemplo.test/a?b=1") == "https://exemplo.test/a?b=1"
    assert news_rss._safe_link("HTTP://exemplo.test/a") == "HTTP://exemplo.test/a"


# (11) _parse_xml recusa expat antiga sem defusedxml


def test_parse_xml_recusa_expat_antiga(monkeypatch):
    monkeypatch.setattr(news_rss, "_defused_fromstring", None)
    monkeypatch.setattr(news_rss.pyexpat, "version_info", (2, 4, 0))
    with pytest.raises(ValueError, match="defusedxml"):
        news_rss._parse_xml("<rss/>")


def test_parse_xml_aceita_expat_recente(monkeypatch):
    monkeypatch.setattr(news_rss, "_defused_fromstring", None)
    monkeypatch.setattr(news_rss.pyexpat, "version_info", (2, 4, 1))
    assert news_rss._parse_xml("<rss><channel/></rss>").tag == "rss"


def test_parse_xml_prefere_defusedxml(monkeypatch):
    usado: list[str] = []

    def falso(text):
        usado.append(text)
        return news_rss.ET.fromstring(text)

    monkeypatch.setattr(news_rss, "_defused_fromstring", falso)
    monkeypatch.setattr(news_rss.pyexpat, "version_info", (2, 0, 0))
    assert news_rss._parse_xml("<rss/>").tag == "rss"
    assert usado == ["<rss/>"]
