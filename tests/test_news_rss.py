"""Notícias por RSS — testes offline, sem rede.

Cobre o parser RSS 2.0/Atom/RDF, o filtro de relevância, o recorte de data,
o serviço que monta o digest e a preservação das últimas manchetes boas.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched, TTLCache  # noqa: E402
from app.providers import news_rss  # noqa: E402
from app.services import news as news_service  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Exemplo</title><language>pt-BR</language>
  <item>
    <title>Preço da memória RAM dispara com demanda de data centers</title>
    <link>https://tecnoblog.net/noticias/ram-dispara/?utm_source=rss</link>
    <pubDate>Tue, 03 Nov 2026 12:00:00 -0300</pubDate>
    <description>&lt;p&gt;Fabricantes priorizam IA.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Novo tratamento para enxaqueca é aprovado</title>
    <link>https://tecnoblog.net/noticias/saude/</link>
    <pubDate>Tue, 03 Nov 2026 13:00:00 -0300</pubDate>
  </item>
  <item>
    <title>Sem link não entra</title>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
  <title>Exemplo</title>
  <entry>
    <title>TSMC warns of chip shortage as tariffs bite</title>
    <link rel="alternate" href="https://www.theregister.com/2026/11/03/tsmc/"/>
    <updated>2026-11-03T15:00:00Z</updated>
    <summary>Foundry capacity is booked.</summary>
  </entry>
  <entry>
    <title>Minister said the budget is final</title>
    <link href="https://www.theregister.com/2026/11/03/budget/"/>
    <updated>2026-11-03T16:00:00Z</updated>
  </entry>
</feed>"""

FEED_PT = news_rss.Feed("Tecnoblog", "https://tecnoblog.net/feed/", "pt-BR")
FEED_EN = news_rss.Feed("The Register", "https://www.theregister.com/headlines.atom", "en")
NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _sem_relogio(monkeypatch):
    """Os feeds de teste têm data fixa; o recorte de 7 dias não pode envelhecê-los."""
    monkeypatch.setattr(news_rss, "MAX_AGE", timedelta(days=36500))


def test_relevancia_e_a_mesma_regra_do_dominio():
    assert news_rss.is_price_relevant("Preço de memória e GPU sobe")
    assert news_rss.is_price_relevant("Escassez de hélio afeta fábricas")
    assert news_rss.is_price_relevant("AI demand drains DRAM supply")
    # "ai" não pode casar dentro de "said"/"again".
    assert not news_rss.is_price_relevant("Minister said again the budget is final")
    assert not news_rss.is_price_relevant("Novo tratamento para enxaqueca")


def test_descarta_item_antigo_ou_sem_data(monkeypatch):
    monkeypatch.setattr(news_rss, "MAX_AGE", timedelta(days=7))
    old = ATOM.replace("2026-11-03T15:00:00Z", "2026-10-20T15:00:00Z")
    assert news_rss._parse_feed(old, FEED_EN, limit=10, now=NOW) == []
    undated = RSS.replace("<pubDate>Tue, 03 Nov 2026 12:00:00 -0300</pubDate>", "")
    assert news_rss._parse_feed(undated, FEED_PT, limit=10, now=NOW) == []
    assert len(news_rss._parse_feed(ATOM, FEED_EN, limit=10, now=NOW)) == 1


def test_parser_rss_extrai_campos_e_descarta_irrelevante():
    articles = news_rss._parse_feed(RSS, FEED_PT, limit=10)
    assert len(articles) == 1
    art = articles[0]
    assert art["title"].startswith("Preço da memória RAM")
    assert art["domain"] == "tecnoblog.net"
    assert art["language"] == "pt"
    assert art["seen_at"] == "2026-11-03T15:00:00+00:00"
    assert set(art) == {
        "title", "url", "domain", "country", "language", "seen_at", "kind", "region",
    }
    assert art["kind"] == "news"


def test_parser_atom_le_href_xml_lang_e_updated():
    articles = news_rss._parse_feed(ATOM, FEED_EN, limit=10)
    assert [a["url"] for a in articles] == ["https://www.theregister.com/2026/11/03/tsmc/"]
    assert articles[0]["domain"] == "theregister.com"
    assert articles[0]["language"] == "en"
    assert articles[0]["seen_at"] == "2026-11-03T15:00:00+00:00"


def test_parser_respeita_limite_por_feed():
    assert len(news_rss._parse_feed(ATOM, FEED_EN, limit=0)) == 0


def test_fetch_articles_tolera_feed_com_falha(monkeypatch):
    feeds = (FEED_PT, FEED_EN)

    async def fake_get_text(url, **kw):
        if "tecnoblog" in url:
            raise RuntimeError("HTTP 503")
        return ATOM

    monkeypatch.setattr(news_rss, "FEEDS", feeds)
    monkeypatch.setattr(news_rss, "get_text", fake_get_text)
    fetched = asyncio.run(news_rss.fetch_articles(limit=5))
    assert fetched.status == "ok"
    assert len(fetched.payload["articles"]) == 1
    assert "1 feed(s) falharam" in (fetched.note or "")


def test_fetch_articles_sem_nenhum_artigo_levanta(monkeypatch):
    async def fake_get_text(url, **kw):
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(news_rss, "FEEDS", (FEED_PT,))
    monkeypatch.setattr(news_rss, "get_text", fake_get_text)
    with pytest.raises(ValueError, match="RSS"):
        asyncio.run(news_rss.fetch_articles(limit=5))


def _rss_fetched(articles: list[dict]) -> Fetched:
    return Fetched(
        key="news.rss", label="RSS", provider="RSS", url="", status="ok",
        payload={"articles": articles},
    )


def test_servico_monta_digest_com_rss(monkeypatch):
    calls = []
    original = news_service.build_digest

    def spy(raw, limit):
        calls.append(len(raw))
        return original(raw, limit=limit)

    second = {
        "title": "TSMC warns chip shortage as tariffs bite",
        "url": "https://bloomberg.com/tech/tsmc", "domain": "bloomberg.com",
        "country": None, "language": "en",
        "seen_at": "2026-11-03T14:00:00+00:00", "kind": "news", "region": "global",
    }

    async def rss_ok(limit=12):
        return _rss_fetched(news_rss._parse_feed(ATOM, FEED_EN, limit=10) + [second])

    monkeypatch.setattr(news_service, "cache", TTLCache())
    monkeypatch.setattr(news_service, "build_digest", spy)
    monkeypatch.setattr(news_rss, "fetch_articles", rss_ok)

    fetched = asyncio.run(news_service.collect_headlines(limit=5))
    assert fetched.status == "ok"
    assert calls == [2], "todos os feeds passam juntos por um único digest"
    # A mesma história em dois veículos vira um item corroborado.
    assert fetched.payload["items"][0]["corroboration"] == 2
    # O digest continua interno: está no payload, nunca na nota exibível.
    assert fetched.payload["digest"] not in (fetched.note or "")


def test_falha_total_preserva_ultimas_manchetes_como_stale(monkeypatch):
    state = {"ok": True}

    async def rss_toggle(limit=12):
        if state["ok"]:
            return _rss_fetched(news_rss._parse_feed(ATOM, FEED_EN, limit=10))
        raise RuntimeError("HTTP 503")

    outer = TTLCache()
    monkeypatch.setattr(news_service, "cache", TTLCache())
    monkeypatch.setattr(news_rss, "fetch_articles", rss_toggle)

    async def run(force: bool) -> Fetched:
        return await outer.get_or_fetch(
            "news.headlines", 60,
            lambda: news_service.collect_headlines(limit=5, force=force),
            force=force,
        )

    async def scenario():
        first = await run(force=False)
        # Zera o cache interno para simular RSS sem valor bom anterior.
        monkeypatch.setattr(news_service, "cache", TTLCache())
        state["ok"] = False
        second = await run(force=True)
        return first, second

    first, second = asyncio.run(scenario())
    assert first.status == "ok"
    assert second.status == "stale"
    assert second.payload["items"] == first.payload["items"]


def test_analise_vale_30_dias_e_noticia_7(monkeypatch):
    monkeypatch.setattr(news_rss, "MAX_AGE", timedelta(days=7))
    monkeypatch.setattr(news_rss, "MAX_AGE_ANALYSIS", timedelta(days=30))
    old = ATOM.replace("2026-11-03T15:00:00Z", "2026-10-20T15:00:00Z")
    analysis = news_rss.Feed("EE Times", "https://www.eetimes.com/feed/", "en", kind="analysis")
    arts = news_rss._parse_feed(old, analysis, limit=10, now=NOW)
    assert len(arts) == 1 and arts[0]["kind"] == "analysis"
    assert news_rss._parse_feed(old, FEED_EN, limit=10, now=NOW) == []


def test_feed_de_ultimas_sem_data_entra_sem_data_inventada(monkeypatch):
    monkeypatch.setattr(news_rss, "MAX_AGE", timedelta(days=7))
    rdf = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/">
  <channel><title>Nikkei</title></channel>
  <item rdf:about="https://asia.nikkei.com/a">
    <title>Samsung raises DRAM prices as AI demand drains supply</title>
    <link>https://asia.nikkei.com/a</link>
  </item>
</rdf:RDF>"""
    nikkei = news_rss.Feed("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar", "en", "asia", dated=False)
    arts = news_rss._parse_feed(rdf, nikkei, limit=10, now=NOW)
    assert len(arts) == 1
    assert arts[0]["seen_at"] is None
    # Feed comum sem data continua descartado.
    assert news_rss._parse_feed(rdf, FEED_EN, limit=10, now=NOW) == []


def test_cobre_vale_europa_leste_asia_brasil_e_analise():
    regions = {f.region for f in news_rss.FEEDS}
    assert {"vale-do-silicio", "europa", "leste-europeu", "asia", "brasil"} <= regions
    assert any(f.kind == "analysis" for f in news_rss.FEEDS)
    assert all(f.url.startswith(("https://", "http://")) for f in news_rss.FEEDS)
    assert len({f.url for f in news_rss.FEEDS}) == len(news_rss.FEEDS)
