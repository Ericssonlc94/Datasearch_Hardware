"""Notícias por RSS público, sem chave e sem agregador.

Única fonte de manchetes do painel: lê feeds RSS/Atom publicados pelos
próprios veículos, extrai os campos que o digest editorial usa e deixa a
deduplicação/corroboração para `app/domain/news.py`. (O GDELT foi removido em
04/11/2026: respondia 429 na maior parte dos ciclos.)

A lista cobre tecnologia, Vale do Silício, imprensa geral/econômica, Europa
(com leste europeu), Ásia, Brasil e artigos de análise. O
que entra é decidido por `domain.news.is_price_relevant`, então review, oferta de loja e entretenimento ficam fora
mesmo quando o veículo publica de tudo.
"""

from __future__ import annotations

import asyncio
import html
import pyexpat
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from ..cache import Fetched
from ..domain.news import is_price_relevant, language_code
from ..http import get_text, limiter

try:
    # defusedxml recusa entidades e DTD externos em XML de terceiros.
    from defusedxml.ElementTree import fromstring as _defused_fromstring
except ImportError:  # dependência opcional até entrar em requirements.txt
    _defused_fromstring = None

# Sem defusedxml, a proteção contra "billion laughs" vem da própria expat,
# que só passou a barrar amplificação de entidades na 2.4.1.
_MIN_EXPAT = (2, 4, 1)

# Feeds testados em 04/11/2026: todos responderam 200 com itens recentes.
# Fora da lista, com o motivo: VideoCardz (403), Washington Post (502), CNN
# (feeds parados em 2016/2017), Reuters, AP e AFP (sem RSS público acessível:
# 401/403), bne IntelliNews e Japan Times (403), Taipei
# Times e Focus Taiwan (404), Korea Herald (XML inválido), BusinessKorea (feed
# em coreano), TrendForce (parado em julho), CSIS (parado em 2016), MERICS,
# PIIE e CFR (404), Euractiv (o feed passou a entregar links de outra
# publicação, rapporteur.com). Veículos gerais publicam de tudo; quem decide o que entra
# é `is_price_relevant`.
@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    language: str
    region: str = "global"
    kind: str = "news"  # news | analysis
    dated: bool = True  # False: feed de "últimas" sem data por item (Nikkei)


FEEDS: tuple[Feed, ...] = (
    # tecnologia (cobertura global de hardware)
    Feed("Tom's Hardware", "https://www.tomshardware.com/feeds.xml", "en"),
    Feed("TechPowerUp", "https://www.techpowerup.com/rss/news", "en"),
    Feed("Wccftech", "https://wccftech.com/feed/", "en"),
    Feed("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "en"),
    Feed("The Register", "https://www.theregister.com/headlines.atom", "en"),
    # Vale do Silício
    Feed("TechCrunch", "https://techcrunch.com/feed/", "en", "vale-do-silicio"),
    Feed("The Verge", "https://www.theverge.com/rss/index.xml", "en", "vale-do-silicio"),
    Feed("CNBC — tecnologia", "https://www.cnbc.com/id/19854910/device/rss/rss.html", "en", "vale-do-silicio"),
    Feed("Wired — negócios", "https://www.wired.com/feed/category/business/latest/rss", "en", "vale-do-silicio"),
    Feed("Bloomberg — tecnologia", "https://feeds.bloomberg.com/technology/news.rss", "en", "vale-do-silicio"),
    # imprensa geral e econômica
    Feed("The Guardian — tecnologia", "https://www.theguardian.com/uk/technology/rss", "en"),
    Feed("The Guardian — economia", "https://www.theguardian.com/uk/business/rss", "en"),
    Feed("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "en"),
    Feed("Bloomberg — mercados", "https://feeds.bloomberg.com/markets/news.rss", "en"),
    Feed("BBC — tecnologia", "https://feeds.bbci.co.uk/news/technology/rss.xml", "en"),
    Feed("BBC — economia", "https://feeds.bbci.co.uk/news/business/rss.xml", "en"),
    # Europa
    Feed("Financial Times — tecnologia", "https://www.ft.com/technology?format=rss", "en", "europa"),
    Feed("Euronews — economia", "https://www.euronews.com/rss?level=theme&name=business", "en", "europa"),
    Feed("DW — economia", "https://rss.dw.com/rdf/rss-en-bus", "en", "europa"),
    Feed("Politico Europe", "https://www.politico.eu/feed/", "en", "europa"),
    # leste europeu
    Feed("Kyiv Independent", "https://kyivindependent.com/news-archive/rss/", "en", "leste-europeu"),
    Feed("Notes from Poland", "https://notesfrompoland.com/feed/", "en", "leste-europeu"),
    Feed("Balkan Insight", "https://balkaninsight.com/feed/", "en", "leste-europeu"),
    Feed("Emerging Europe", "https://emerging-europe.com/feed/", "en", "leste-europeu"),
    # Ásia
    Feed("Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar", "en", "asia", dated=False),
    Feed("SCMP — tecnologia", "https://www.scmp.com/rss/36/feed", "en", "asia"),
    Feed("SCMP — economia", "https://www.scmp.com/rss/92/feed", "en", "asia"),
    Feed("DigiTimes", "https://www.digitimes.com/rss/daily.xml", "en", "asia"),
    Feed("The Diplomat", "https://thediplomat.com/feed/", "en", "asia"),
    Feed("CNA — economia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936", "en", "asia"),
    # Brasil
    Feed("Tecnoblog", "https://tecnoblog.net/feed/", "pt-BR", "brasil"),
    Feed("Canaltech", "https://canaltech.com.br/rss/", "pt-BR", "brasil"),
    Feed("Olhar Digital", "https://olhardigital.com.br/feed/", "pt-BR", "brasil"),
    Feed("Gazeta do Povo — economia", "https://www.gazetadopovo.com.br/feed/rss/economia.xml", "pt-BR", "brasil"),
    Feed("Brasil 247", "https://www.brasil247.com/feed", "pt-BR", "brasil"),
    # artigos de análise
    Feed("EE Times", "https://www.eetimes.com/feed/", "en", kind="analysis"),
    Feed("Semiconductor Engineering", "https://semiengineering.com/feed/", "en", kind="analysis"),
    Feed("IEEE Spectrum — semicondutores", "https://spectrum.ieee.org/feeds/topic/semiconductors.rss", "en", kind="analysis"),
    Feed("Stratechery", "https://stratechery.com/feed/", "en", "vale-do-silicio", kind="analysis"),
    Feed("The Conversation — tecnologia", "https://theconversation.com/global/technology/articles.atom", "en", kind="analysis"),
    Feed("Lowy Institute — The Interpreter", "https://www.lowyinstitute.org/the-interpreter/rss.xml", "en", "asia", kind="analysis"),
    Feed("Project Syndicate", "https://www.project-syndicate.org/rss", "en", kind="analysis"),
    Feed("ChinaTalk", "https://www.chinatalk.media/feed", "en", "asia", kind="analysis"),
)

# Mesmo recorte que a seção promete ao leitor: notícia dos últimos 7 dias;
# artigo de análise, 30 dias (sai com menos frequência e envelhece devagar).
MAX_AGE = timedelta(days=7)
MAX_AGE_ANALYSIS = timedelta(days=30)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(text: str | None) -> str:
    raw = html.unescape(text or "")
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = set(names)
    for child in element:
        if _local(child.tag) in wanted and (child.text or "").strip():
            return _clean(child.text)
    return ""


def _entry_link(entry: ET.Element) -> str:
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        if (child.text or "").strip():
            return child.text.strip()
    return ""


def _parse_when(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _safe_link(url: str) -> str:
    """Só `http(s)` com host vira link: `javascript:`, `data:` e afins saem.

    O título é escapado no painel, mas um `href="javascript:…"` não tem nada
    a escapar. Item sem link seguro é descartado na origem.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    return url


def _parse_xml(text: str) -> ET.Element:
    if _defused_fromstring is not None:
        return _defused_fromstring(text)
    if pyexpat.version_info < _MIN_EXPAT:
        raise ValueError(
            "expat %d.%d.%d não barra amplificação de entidades; instale defusedxml"
            % pyexpat.version_info
        )
    return ET.fromstring(text)


def _entry_when(entry: ET.Element) -> datetime | None:
    for name in ("published", "updated", "pubDate", "date"):
        value = _child_text(entry, name)
        if value:
            parsed = _parse_when(value)
            if parsed is not None:
                return parsed
    return None


def _feed_language(root: ET.Element, feed: Feed) -> str:
    # RSS 2.0 declara <language> dentro de <channel>; Atom pode usar xml:lang
    # na raiz. Procuramos os dois sem depender do namespace do feed.
    for element in root.iter():
        if _local(element.tag) == "language" and (element.text or "").strip():
            return element.text.strip()
    xml_lang = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang")
    return xml_lang or feed.language


def _parse_feed(
    text: str, feed: Feed, limit: int, now: datetime | None = None
) -> list[dict]:
    """Extrai artigos de um RSS 2.0 ou Atom: idioma, data e relevância.

    A relevância usa só o título, que é o que o leitor vê. Sem data de publicação, o item fica de fora — não
    há como garantir que é recente —, exceto em feed de "últimas" declarado
    com `dated=False`, cuja lista já é, por construção, a mais recente.
    """
    root = _parse_xml(text)
    feed_language = _feed_language(root, feed)
    max_age = MAX_AGE_ANALYSIS if feed.kind == "analysis" else MAX_AGE
    cutoff = (now or datetime.now(timezone.utc)) - max_age
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    articles: list[dict] = []
    for entry in entries:
        if len(articles) >= limit:
            break
        title = _child_text(entry, "title")
        url = _safe_link(_entry_link(entry))
        if not title or not url:
            continue
        language = language_code(_child_text(entry, "language") or feed_language)
        if language not in ("en", "pt", "es"):
            continue
        seen_at = _entry_when(entry)
        if seen_at is None and feed.dated:
            continue
        if seen_at is not None and seen_at < cutoff:
            continue
        if not is_price_relevant(title):
            continue
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        articles.append(
            {
                "title": title,
                "url": url,
                "domain": host,
                "country": None,
                "language": language,
                # Sem data no feed, fica sem data: nunca preenchemos com a
                # hora da coleta, que pareceria data de publicação.
                "seen_at": seen_at.isoformat() if seen_at else None,
                "kind": feed.kind,
                "region": feed.region,
            }
        )
    return articles


# Dezenas de veículos: no máximo 8 requisições simultâneas, por educação com
# a rede e para não competir com as fontes de dados do índice.
_CONCURRENCY = 8

# Feed RSS legítimo tem dezenas a centenas de KB; 5 MB já é anomalia.
_MAX_FEED_BYTES = 5 * 1024 * 1024


async def _fetch_feed(feed: Feed, limit: int) -> list[dict]:
    # Timeout curto: os feeds são independentes e o painel não deve esperar
    # um veículo lento para montar a seção de notícias.
    async with limiter("rss", _CONCURRENCY):
        text = await get_text(feed.url, timeout=12.0, max_bytes=_MAX_FEED_BYTES)
    return _parse_feed(text, feed, limit)


async def fetch_articles(limit: int = 12) -> Fetched:
    """Busca os feeds em paralelo e devolve artigos brutos para o digest."""
    per_feed = min(max(limit * 3, 20), 40)
    results = await asyncio.gather(
        *(_fetch_feed(feed, per_feed) for feed in FEEDS),
        return_exceptions=True,
    )

    articles: list[dict] = []
    failures: list[str] = []
    for feed, result in zip(FEEDS, results):
        if isinstance(result, BaseException):
            failures.append(f"{feed.name}: {type(result).__name__}: {result}")
            continue
        articles.extend(result)

    if not articles:
        detail = "; ".join(failures[:3]) or "nenhuma notícia recente ligada a preço de hardware"
        raise ValueError(f"RSS: nenhum artigo disponível ({detail})")

    note = (
        f"{len(articles)} artigos de {len(FEEDS) - len(failures)} feed(s); "
        "só títulos ligados a preço/oferta de hardware, últimos 7 dias."
    )
    if failures:
        note += f" {len(failures)} feed(s) falharam."
    return Fetched(
        key="news.rss",
        label="Manchetes de veículos de tecnologia (RSS)",
        provider="RSS público — " + ", ".join(sorted({f.name.split(" — ")[0] for f in FEEDS})),
        url=", ".join(feed.url for feed in FEEDS),
        status="ok",
        payload={"articles": articles},
        as_of=datetime.now(timezone.utc),
        note=note,
    )
