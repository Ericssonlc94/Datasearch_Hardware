"""Orquestra a coleta paralela de todas as fontes e monta o Snapshot.

Nada aqui levanta exceção para o chamador: cada fonte é isolada pelo cache,
que converte falha em `stale` (último valor bom) ou `unavailable`. O painel
sempre renderiza — o que muda é a `coverage` e a lista `degraded`.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ..cache import Fetched, cache
from ..config import settings
from ..domain import prices as prices_domain
from ..domain import supply_fronts
from ..domain.analyzer import build_brazil, build_drivers, build_summary
from ..domain.catalog import CATEGORIES
from ..domain.fx import explain_fx
from ..domain.ranking import build_ranking
from ..domain.supply import build_supply
from ..providers import bcb, comexstat, comtrade, fedreg, fred, ibge, markets, sec, usgs
from ..schemas import Snapshot
from . import history, news
from .progress import progress


def _optional_provider(name: str):
    """Provider ainda em construção (T30) não derruba o coletor: o job só entra
    quando o módulo e a função existirem."""
    try:
        return importlib.import_module(f"..providers.{name}", __package__)
    except ImportError:
        return None


kabum = _optional_provider("kabum")
tsmc = _optional_provider("tsmc")

log = logging.getLogger(__name__)

DISCLAIMER = (
    "Esta é uma estimativa, feita com dados públicos. Não é uma "
    "previsão garantida nem recomendação de compra. Os números oficiais "
    "(inflação, dólar, importação) aparecem identificados; o resto é conta "
    "do modelo. Quer conferir as fontes? Abra a aba Técnico."
)

# Frequências mensais não mudam a cada 15 minutos; bater nelas nesse ritmo é
# desperdício e convite a bloqueio.
_FRED_MONTHLY = {
    "ppi_semiconductors",
    "import_px_semis",
    "copper",
    "aluminum",
    "natgas_eu",
    "cpi_computers_us",
    "global_metals",
    "global_energy",
    "global_all",
    "freight_deep_sea",
    "customs_duties",
}


# Lojas (T26 da Segurança): coleta semanal, às terças (decisão do usuário,
# 05/11): o preço cheio muda devagar e a análise olha 30 dias.
# K1: o `force` do botão "atualizar" e do POST /api/refresh não vale para elas.
# K2: uma falha (403, 429, desafio, robots proibindo) fica guardada 24 h, e o
# cache.db a leva para o próximo start; reiniciar o app não volta a bater.
# Prazos fixos no código, sem variável de ambiente, para ninguém encurtá-los.
STORE_PREFIXES = ("kabum.",)
STORE_TTL = 7 * 24 * 60 * 60
STORE_FAILURE_TTL = 24 * 60 * 60
STORE_WEEKDAY = 1  # terça (segunda = 0)
STORE_HOUR = 6


def _store_ttl(now: datetime | None = None) -> int:
    """Segundos até a próxima terça às 6 h (hora local), para as coletas
    caírem sempre no mesmo dia da semana e ficarem pareadas."""
    now = now or datetime.now().astimezone()
    target = now.replace(hour=STORE_HOUR, minute=0, second=0, microsecond=0)
    target += timedelta(days=(STORE_WEEKDAY - now.weekday()) % 7)
    if target <= now:
        target += timedelta(days=7)
    return int((target - now).total_seconds())


def is_store(key: str) -> bool:
    return key.startswith(STORE_PREFIXES)


def _tasks(force: bool = False) -> list[tuple[str, int, callable]]:
    """Monta a lista (chave, ttl, fetcher) de tudo que precisa ser coletado."""
    jobs: list[tuple[str, int, callable]] = []

    for key in bcb.SERIES:
        jobs.append((f"bcb.{key}", settings.ttl_daily, lambda k=key: bcb.fetch_series(k)))

    jobs.append(
        ("ibge.ipca_hardware", settings.ttl_monthly, lambda: ibge.fetch_ipca_hardware())
    )

    if settings.enable_fred:
        for key in fred.SERIES:
            ttl = settings.ttl_monthly if key in _FRED_MONTHLY else settings.ttl_daily
            jobs.append((f"fred.{key}", ttl, lambda k=key: fred.fetch_series(k)))

    if settings.enable_markets:
        for key in markets.TICKERS:
            jobs.append(
                (f"market.{key}", settings.ttl_realtime, lambda k=key: markets.fetch_quote(k))
            )

    if settings.enable_news_rss:
        # Uma única entrada no progresso e no cache para a seção de notícias:
        # todos os feeds passam juntos pelo digest.
        jobs.append(
            (
                "news.headlines",
                settings.ttl_news,
                lambda f=force: news.collect_headlines(force=f),
            )
        )

    if settings.enable_usgs:
        jobs.append(("usgs.fab_quakes", settings.ttl_daily, lambda: usgs.fetch_fab_quakes()))

    if settings.enable_fedreg:
        # Regra federal sai em dia útil, no máximo algumas por mês.
        jobs.append(
            ("fedreg.bis_chip_rules", settings.ttl_daily, lambda: fedreg.fetch_bis_chip_rules())
        )

    if settings.enable_comtrade:
        for key in comtrade.COMMODITIES:
            jobs.append(
                (f"comtrade.{key}", settings.ttl_monthly, lambda k=key: comtrade.fetch_flow(k))
            )

    if settings.enable_sec:
        # Dado trimestral: TTL de 24 h é suficiente e respeita a SEC.
        jobs.extend(
            [
                (
                    "sec.capex_hyperscaler",
                    settings.ttl_monthly,
                    lambda: sec.fetch_capex_hyperscaler(),
                ),
                (
                    "sec.chip_revenue",
                    settings.ttl_monthly,
                    lambda: sec.fetch_chip_revenue(),
                ),
                (
                    "sec.memory_inventory",
                    settings.ttl_monthly,
                    lambda: sec.fetch_memory_inventory(),
                ),
            ]
        )
        # DIO por trimestre das frentes memória (Micron) e lógica (NVIDIA,
        # AMD, Intel), §T24c.
        for key, name in (
            ("sec.memory_quarters", "fetch_memory_quarters"),
            ("sec.logic_quarters", "fetch_logic_quarters"),
        ):
            fetcher = getattr(sec, name, None)
            if fetcher is not None:
                jobs.append((key, settings.ttl_monthly, fetcher))

    if settings.enable_tsmc and hasattr(tsmc, "fetch_monthly_revenue"):
        jobs.append(("tsmc.monthly_revenue", settings.ttl_monthly, tsmc.fetch_monthly_revenue))

    # A loja liga com DSH_ENABLE_KABUM; DSH_CONTACT é opcional. Prazo e falha de
    # 24 h e `force` ignorado valem pelo prefixo `kabum.` (K1/K2, em `_run`).
    if settings.kabum_enabled and hasattr(kabum, "fetch_basket"):
        jobs.append(("kabum.basket", _store_ttl(), kabum.fetch_basket))

    if settings.enable_comtrade_monthly:
        # Substituto do Comex Stat (T05): o Brasil reporta ao Comtrade o mesmo
        # FOB e peso da SECEX. Todos os SH6 saem numa coleta compartilhada.
        all_sh6 = [c.sh6 for c in CATEGORIES]
        for cat in _one_per_sh6():
            jobs.append(
                (
                    f"comtrade_monthly.{cat.key}",
                    settings.ttl_monthly,
                    lambda c=cat: comtrade.fetch_monthly_imports(
                        c.key, c.sh6, c.label, all_sh6
                    ),
                )
            )

    if settings.enable_comexstat:
        for cat in _one_per_sh6():
            jobs.append(
                (
                    f"comexstat.{cat.key}",
                    settings.ttl_monthly,
                    lambda c=cat: comexstat.fetch_imports(c.key, c.sh6, c.ncms, c.label),
                )
            )

    return jobs


def _one_per_sh6() -> list:
    """Primeira categoria de cada SH6: placa de vídeo e placa-mãe dividem um."""
    seen: set[str] = set()
    firsts = []
    for cat in CATEGORIES:
        if cat.sh6 not in seen:
            seen.add(cat.sh6)
            firsts.append(cat)
    return firsts


def _share_by_sh6(collected: dict[str, Fetched], prefix: str) -> None:
    """Categoria sem coleta própria herda a de outra com o mesmo SH6."""
    by_sh6: dict[str, Fetched] = {}
    for cat in CATEGORIES:
        got = collected.get(f"{prefix}.{cat.key}")
        if got is not None and got.ok:
            by_sh6.setdefault(cat.sh6, got)
    for cat in CATEGORIES:
        slot = f"{prefix}.{cat.key}"
        if slot not in collected or not collected[slot].ok:
            shared = by_sh6.get(cat.sh6)
            if shared is not None:
                collected[slot] = shared


async def collect(force: bool = False) -> dict[str, Fetched]:
    jobs = _tasks(force)
    progress.start(len(jobs))

    async def _run(key: str, ttl: int, fetcher: callable) -> Fetched:
        store = is_store(key)
        try:
            return await cache.get_or_fetch(
                key,
                _store_ttl() if store else ttl,
                fetcher,
                force=force and not store,
                failure_ttl=STORE_FAILURE_TTL if store else None,
                # Cesta nova invalida a coleta guardada (T35).
                version=getattr(prices_domain, "BASKET_VERSION", None) if store else None,
            )
        finally:
            # Conta mesmo quando a fonte falha: a tela precisa avançar e dizer
            # que aquela consulta terminou, com sucesso ou não.
            progress.step(key)

    results = await asyncio.gather(
        *(_run(key, ttl, fetcher) for key, ttl, fetcher in jobs),
        return_exceptions=True,
    )

    collected: dict[str, Fetched] = {}
    for (key, _, _), res in zip(jobs, results):
        if isinstance(res, BaseException):
            log.error("coleta '%s' levantou inesperadamente: %s", key, res)
            collected[key] = Fetched(
                key=key,
                label=key,
                provider="?",
                url="",
                status="unavailable",
                error=f"{type(res).__name__}: {res}",
            )
        else:
            collected[key] = res

    # Categorias que dividem SH6 herdam a mesma coleta de importação.
    if settings.enable_comtrade_monthly:
        _share_by_sh6(collected, "comtrade_monthly")
    if settings.enable_comexstat:
        _share_by_sh6(collected, "comexstat")

    return collected


def _usd_brl_points(collected: dict[str, Fetched]) -> list[tuple[str, float]]:
    """Mesma cadeia da camada Brasil: PTAX oficial → spot → H.10 do Fed."""
    for key in ("bcb.ptax_usd", "market.usd_brl", "fred.usd_brl_fed"):
        fetched = collected.get(key)
        if fetched is not None and fetched.ok and isinstance(fetched.payload, dict):
            points = [(str(t), float(v)) for t, v in fetched.payload.get("points") or []]
            if points:
                return points
    return []


PRICE_SOURCE_KEY = "kabum.basket"
# 30 dias da variação pareada + folga para dias sem coleta.
MODEL_HISTORY_DAYS = 60


def _ipca_only_categories(ranking: list | None) -> list[dict]:
    """Categorias só com o IPCA do subitem, para a aba Preços sem a loja."""
    observed = {item.key: item.observed_br for item in ranking or []}
    out = []
    for cat in CATEGORIES:
        obs = observed.get(cat.key)
        out.append({
            "key": cat.key,
            "label": cat.label,
            "published": False,
            "ipca_only": True,
            "warnings": [],
            "ipca": {
                "subitem": cat.ipca_subitem,
                "label": obs.subitem_label if obs else None,
                "is_proxy": cat.ipca_is_proxy,
                "period": obs.period if obs else None,
                "change_12m_pct": obs.var_12m_pct if obs else None,
                "status": obs.status if obs else "unavailable",
            },
            "tiers": [],
        })
    return out


def _disabled_prices(
    reason: str, status: str = "disabled", ranking: list | None = None
) -> dict:
    """Payload de /api/prices sem preço: o painel explica o motivo (§T28c)."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "key": "kabum",
            "label": prices_domain.PRICE_LABEL,
            "note": None,
            "status": status,
            "status_reason": reason,
            "as_of": None,
            "listings_tracked": 0,
            "listings_valid": 0,
        },
        "tiers": [],
        "categories": _ipca_only_categories(ranking),
        "brand_view": None,
        "technical": {},
    }


def _prices_view(
    collected: dict[str, Fetched], model_history: dict, ranking: list
) -> dict:
    if not settings.kabum_enabled:
        return _disabled_prices(
            "Para ligar, use DSH_ENABLE_KABUM=true no .env.",
            ranking=ranking,
        )
    build = getattr(prices_domain, "build_prices_view", None)
    if build is None:
        return _disabled_prices("As contas de preço ainda não estão ligadas.", ranking=ranking)
    try:
        return build(
            collected, {}, datetime.now(timezone.utc).date(), model_history=model_history
        )
    except Exception:  # noqa: BLE001 — preço é uma aba; não derruba o snapshot
        log.exception("falha ao montar os preços da loja")
        return _disabled_prices(
            "Falha ao calcular os preços nesta rodada.", "unavailable", ranking
        )


def _fronts(collected: dict[str, Fetched]) -> list[dict]:
    build = getattr(supply_fronts, "build_fronts", None)
    if build is None:
        return []
    try:
        return build(collected, datetime.now(timezone.utc).date())
    except Exception:  # noqa: BLE001
        log.exception("falha ao montar as frentes de oferta")
        return []


def _model_history() -> dict[str, list]:
    """Últimos 60 dias de cada modelo da cesta (`kabum_model.<key>`), T35.

    Falha de disco só tira a variação de 30 dias, não o preço do dia.
    """
    if not settings.kabum_enabled or not hasattr(prices_domain, "model_series"):
        return {}
    keys = [prices_domain.model_series(m.key) for m in getattr(prices_domain, "BASKET", ())]
    try:
        return history.model_price_history(keys, days=MODEL_HISTORY_DAYS)
    except Exception:  # noqa: BLE001
        log.exception("falha ao ler o histórico dos modelos da loja; seguindo sem ele")
        return {}


def _record_model_prices(view: dict | None) -> None:
    """Grava o preço do dia de cada modelo e tira `series_values` da resposta.

    As séries `kabum_model.*` são internas; as `price.*` já são gravadas a
    partir das faixas pelo `history.record_snapshot`.
    """
    if not isinstance(view, dict):
        return
    values = view.pop("series_values", None) or {}
    try:
        history.record_model_prices(values, datetime.now(timezone.utc).date())
    except Exception:  # noqa: BLE001
        log.exception("falha ao gravar o preço dos modelos da loja")


def build_snapshot(
    collected: dict[str, Fetched], model_history: dict | None = None
) -> Snapshot:
    drivers = build_drivers(collected)
    supply = build_supply(collected)
    brazil = build_brazil(collected)
    brazil.fx_explanation = explain_fx(
        collected, _usd_brl_points(collected), brazil.fx_passthrough
    )
    summary = build_summary(drivers, brazil)
    ranking = build_ranking(drivers, brazil, collected)

    sources = sorted(
        (f.to_source_info() for f in collected.values()),
        key=lambda s: (s.status != "ok", s.provider, s.label),
    )
    degraded = [
        f"{f.label or key} ({f.status})"
        for key, f in sorted(collected.items())
        if f.status in ("stale", "unavailable")
    ]

    headlines_f = collected.get("news.headlines")
    headlines: list[dict] = []
    if headlines_f and headlines_f.ok:
        payload = headlines_f.payload
        # O serviço devolve {items, digest, stats}. O digest é interno: serve
        # para auditoria em log e não é serializado no Snapshot.
        if isinstance(payload, dict):
            headlines = payload.get("items") or []
        elif isinstance(payload, list):
            headlines = payload

    now = datetime.now(timezone.utc)
    return Snapshot(
        generated_at=now,
        next_refresh_at=now + timedelta(seconds=settings.refresh_seconds),
        refresh_seconds=settings.refresh_seconds,
        summary=summary,
        drivers=drivers,
        supply=supply,
        brazil=brazil,
        ranking=ranking,
        sources=sources,
        degraded=degraded,
        headlines=headlines or [],
        prices=_prices_view(collected, model_history or {}, ranking),
        supply_fronts=_fronts(collected),
        disclaimer=DISCLAIMER,
    )


async def collect_and_build(
    force: bool = False,
) -> tuple[Snapshot, dict[str, Fetched]]:
    """Snapshot e as coletas que o geraram (a reconstrução do histórico usa as séries)."""
    collected = await collect(force=force)
    progress.building()
    model_history = await asyncio.to_thread(_model_history)
    snap = build_snapshot(collected, model_history)
    await asyncio.to_thread(_record_model_prices, snap.prices)
    return snap, collected


async def get_snapshot(force: bool = False) -> Snapshot:
    snap, _ = await collect_and_build(force=force)
    return snap


# T43 — snapshot de partida sem rede.
#
# O cache em disco guarda o último valor bom de cada fonte mesmo vencido. Montar
# o snapshot a partir dele no start evita a página presa na tela de carregamento
# pelo tempo da coleta inteira (9 min observados com o cache de 4 dias). O
# payload sai marcado como `stale`; a coleta em background substitui.
#
# Abaixo desta fração de fontes o índice sairia de quase nada: aí vale mais
# esperar a coleta do que mostrar um número enganoso.
CACHE_SNAPSHOT_MIN_SHARE = 0.5

CACHE_SNAPSHOT_REASON = (
    "Snapshot montado do cache em disco; os números são da última coleta "
    "gravada e a coleta nova ainda não terminou."
)


def cached_collected(
    jobs: list[tuple[str, int, callable]] | None = None,
) -> dict[str, Fetched]:
    """O que o cache já tem, sem rede. Entrada sem payload fica de fora.

    Valor fora do prazo da fonte entra como `stale`: o número é o último bom,
    mas não é deste ciclo — e o painel precisa dizer isso na lista `degraded`.
    """
    collected: dict[str, Fetched] = {}
    now = datetime.now(timezone.utc)
    for key, ttl, _fetcher in (jobs if jobs is not None else _tasks()):
        got = cache.peek(key)
        if got is None or got.payload is None:
            continue
        if got.status == "ok" and _out_of_date(got.fetched_at, ttl, now):
            got = replace(
                got, status="stale", note="valor do cache em disco; fora do prazo"
            )
        collected[key] = got
    return collected


def _out_of_date(fetched_at: datetime | None, ttl: int, now: datetime) -> bool:
    """Idade desconhecida conta como vencida: não dá para afirmar que está no prazo."""
    if fetched_at is None:
        return True
    return (now - fetched_at).total_seconds() > ttl


async def build_cached_snapshot() -> Snapshot | None:
    """Snapshot do cache em disco, marcado como desatualizado, ou `None`.

    Só leitura: não grava histórico, não grava preço de loja e não persiste o
    cache. Erro aqui nunca impede o start — quem chama cai na coleta normal.
    """
    jobs = _tasks()
    collected = cached_collected(jobs)
    minimum = max(1, math.ceil(len(jobs) * CACHE_SNAPSHOT_MIN_SHARE))
    if len(collected) < minimum:
        log.info(
            "cache: %d de %d fonte(s) com valor; sem snapshot de partida",
            len(collected),
            len(jobs),
        )
        return None

    if settings.enable_comtrade_monthly:
        _share_by_sh6(collected, "comtrade_monthly")
    if settings.enable_comexstat:
        _share_by_sh6(collected, "comexstat")

    try:
        model_history = await asyncio.to_thread(_model_history)
        snap = build_snapshot(collected, model_history)
    except Exception:  # noqa: BLE001 — o start não pode morrer por causa do cache
        log.exception("falha ao montar o snapshot do cache; seguindo para a coleta")
        return None

    # `generated_at` conta a idade do dado, não a hora em que ele foi lido.
    newest = max(
        (f.fetched_at for f in collected.values() if f.fetched_at is not None),
        default=None,
    )
    if newest is not None:
        snap.generated_at = newest
    snap.stale = True
    snap.stale_reason = CACHE_SNAPSHOT_REASON
    return snap
