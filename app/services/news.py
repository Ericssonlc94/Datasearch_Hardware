"""Coleta de manchetes: RSS público de veículos identificados.

O provider devolve artigos brutos já filtrados por idioma, data e relevância
para preço; aqui o digest agrupa a mesma história publicada em veículos
diferentes, calcula a corroboração por domínio e escolhe a lista final com
variedade de fontes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..cache import Fetched, cache
from ..config import settings
from ..domain.news import build_digest
from ..providers import news_rss

log = logging.getLogger(__name__)

# Até 3 páginas de 5 na interface. O propósito é dar ao leitor fontes reais
# para conferir o panorama, não virar portal de notícias.
HEADLINES_LIMIT = 15

_LABEL = "Notícias e análises ligadas a preço de hardware"
_PROVIDER = "RSS público de veículos identificados"


async def collect_headlines(
    limit: int = HEADLINES_LIMIT, *, force: bool = False
) -> Fetched:
    """Lê os feeds (via cache), roda o digest e devolve a lista final."""
    if not settings.enable_news_rss:
        return Fetched(
            key="news.headlines",
            label=_LABEL,
            provider=_PROVIDER,
            url="",
            status="unavailable",
            error="fontes de notícias desligadas na configuração",
        )

    result = await cache.get_or_fetch(
        "news.rss", settings.ttl_news, lambda: news_rss.fetch_articles(limit), force=force
    )
    payload = result.payload if result.ok and isinstance(result.payload, dict) else {}
    raw = list(payload.get("articles") or [])
    stale_note = result.note if result.status == "stale" else None

    items, digest, stats = build_digest(raw, limit=limit)
    if not items:
        # Levantar (em vez de devolver `unavailable`) deixa o cache servir as
        # últimas manchetes boas como `stale`, sem apagar a seção por 1 ciclo.
        detail = result.error or "nenhuma notícia passou pelo filtro editorial"
        raise ValueError(f"notícias: nenhuma manchete disponível ({detail})")

    log.info(
        "manchetes: digest %s · %s de %s exibidas · %s análise(s) · "
        "%s corroborada(s) · %s fonte única · %s agrupada(s) por entidade "
        "(%s entre idiomas) · %s fora de en/pt/es · "
        "%s sem relação com preço · %s bloqueada(s) · %s duplicada(s)",
        digest,
        stats["kept"],
        stats["raw"],
        stats.get("analysis", 0),
        stats["corroborated"],
        stats["single_source"],
        stats.get("merged_by_keys", 0),
        stats.get("cross_language", 0),
        stats["language"],
        stats["irrelevant"],
        stats["blocked"],
        stats["duplicate"],
    )

    note = (
        f"{stats['kept']} de {stats['raw']} manchetes após filtro interno · "
        f"{stats['corroborated']} corroborada(s) · "
        f"{stats['language']} fora de en/pt/es · "
        f"{stats['irrelevant']} sem relação com preço · "
        f"{stats['blocked']} descartada(s) · {stats['duplicate']} duplicada(s)"
    )
    if stale_note:
        note += f" · RSS: {stale_note}"

    return Fetched(
        key="news.headlines",
        label=_LABEL,
        provider=_PROVIDER,
        url="",
        status="ok",
        payload={"items": items, "digest": digest, "stats": stats},
        as_of=datetime.now(timezone.utc),
        note=note,
    )
