"""UN Comtrade — endpoint público de preview (sem chave).

    https://comtradeapi.un.org/public/v1/preview/C/A/HS
        ?reporterCode=76&period=2024&partnerCode=0&cmdCode=854232&flowCode=M

Restrição confirmada ao vivo: o preview aceita **um único período por
chamada** ("Maximum number of periods for preview is 1") e devolve 429 para
rajadas paralelas. Por isso tudo sai em fila (`_CONCURRENCY = 1`), e cada
ciclo só pede o que ainda pode mudar: o último ano fechado na série anual e a
cauda de 3 meses na mensal. Anos e meses fechados vêm do cache (T42b/T42c).

Serve para ancorar as teses em fluxo físico de comércio, não só em preço:
  280429 -> outros gases raros (inclui hélio) — a tese do Estreito de Ormuz
  280530 -> compostos de terras raras
  854232 -> memórias (DRAM/NAND)
  854231 -> processadores e controladores
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from ..cache import Fetched, cache
from ..http import FetchError, breaker_guard, breaker_record, get_json, limiter
from ..series_utils import Point

BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

BRAZIL = "76"
WORLD_PARTNER = "0"

# O preview é rigoroso com taxa: com 3 vagas, o teste de 10/11/2026 12:06
# tomou 429 em 5 das 9 categorias. Um pedido por vez (T42b).
_CONCURRENCY = 1
_SPACING_S = 0.35
_PROVIDER = "comtrade"  # nome em DSH_HTTP_TIMEOUT_PROVIDERS / _NO_RETRY_TIMEOUT

# chave -> (código HS, rótulo)
COMMODITIES: dict[str, tuple[str, str]] = {
    "helium": ("280429", "Gases raros, inclui hélio — HS 280429"),
    "rare_earth": ("280530", "Metais de terras raras — HS 280530"),
    "memory": ("854232", "Memórias eletrônicas — HS 854232"),
    "processors": ("854231", "Processadores e controladores — HS 854231"),
}


# Cota do preview: ao esgotar, todo pedido volta `403 Quota Exceeded` com
# `Retry-After` (visto em 04/11/2026: 2285 s, "Quota will be replenished in
# 00:38:05"). Insistir só gasta o tempo do ciclo — antes eram 160 pedidos
# recusados por start. O primeiro 403 abre o disjuntor compartilhado por todas
# as chaves do Comtrade até o prazo que a própria API informa.
_BREAKER = "comtrade"
_QUOTA_STATUS = 403
_QUOTA_FALLBACK_S = 3600.0
# O `Retry-After` já chega finito e em [0, 6 h] (http.parse_retry_after); o
# piso evita martelar a API quando ela responde 0.
_QUOTA_MIN_S = 60.0
_QUOTA_MAX_S = 6 * 60 * 60.0

# 429 = rápido demais. O http.py já esperou o `Retry-After` (até 30 s) e
# repetiu uma vez; se ainda veio 429, o disjuntor fica aberto pelo prazo que a
# API pediu, e o resto do ciclo desiste sem pedido em vez de insistir.
_RATE_STATUS = 429
_RATE_FALLBACK_S = 60.0
_RATE_MIN_S = 5.0


def _cooldown(raw: float | None, fallback: float, floor: float) -> float:
    return fallback if raw is None else min(max(raw, floor), _QUOTA_MAX_S)


def _note_failure(exc: Exception) -> None:
    if not isinstance(exc, FetchError):
        return
    if exc.status_code == _QUOTA_STATUS:
        cooldown = _cooldown(exc.retry_after, _QUOTA_FALLBACK_S, _QUOTA_MIN_S)
    elif exc.status_code == _RATE_STATUS:
        cooldown = _cooldown(exc.retry_after, _RATE_FALLBACK_S, _RATE_MIN_S)
    else:
        return
    breaker_record(_BREAKER, ok=False, threshold=1, cooldown=cooldown)


async def _get(url: str, params: dict) -> dict:
    async with limiter("comtrade", _CONCURRENCY):
        # Checado dentro do semáforo: quem espera na fila enxerga o 403 de quem
        # acabou de passar e desiste sem pedido.
        breaker_guard(_BREAKER)
        try:
            data = await get_json(url, params=params, provider=_PROVIDER)
        except Exception as exc:
            _note_failure(exc)
            raise
        breaker_record(_BREAKER, ok=True)
        await asyncio.sleep(_SPACING_S)
    return data or {}


def _blocked(exc: BaseException) -> bool:
    """Cota, taxa ou disjuntor aberto: os próximos períodos falhariam igual."""
    return isinstance(exc, FetchError) and (
        exc.status_code in (_QUOTA_STATUS, _RATE_STATUS) or "disjuntor aberto" in str(exc)
    )


# Quanto vale um resultado (bom ou ruim) dentro do mesmo ciclo de coleta. As
# 9 categorias mensais e as 4 séries anuais rodam juntas no mesmo `gather`; o
# ciclo inteiro levou < 9 min no pior caso medido. Passado o prazo, o próximo
# ciclo tenta de novo (o TTLCache decide quando há próximo ciclo).
_CYCLE_S = 15 * 60.0


async def _fetch_year(hs_code: str, reporter: str, year: int) -> list[dict]:
    params = {
        "reporterCode": reporter,
        "period": str(year),
        "partnerCode": WORLD_PARTNER,
        "cmdCode": hs_code,
        "flowCode": "M",  # M = importações
    }
    return (await _get(BASE, params)).get("data") or []


def _aggregate(rows: list[dict]) -> tuple[float, float]:
    """Soma valor e peso do ano (o preview pode devolver várias linhas)."""
    value = weight = 0.0
    for row in rows:
        try:
            value += float(row.get("primaryValue") or 0)
            weight += float(row.get("netWgt") or 0)
        except (TypeError, ValueError):
            continue
    return value, weight


# Anos do fim da série que ainda podem mudar: o último ano completo chega ao
# Comtrade aos poucos ao longo do ano seguinte. Os anteriores já fecharam e vêm
# do cache (T42c): 4 anos × 4 SH eram 16 pedidos por ciclo; agora são 4.
_TAIL_YEARS = 1


def _point_map(raw: object) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str):
            try:
                out[item[0]] = float(item[1])
            except (TypeError, ValueError):
                continue
    return out


def _previous_years(key: str, hs_code: str, reporter: str) -> tuple[dict[str, float], dict[str, float]]:
    """(totais, US$/kg) por ano da coleta anterior, lidos do cache mesmo vencido.

    Ano fechado não muda; a entrada antiga de `cache.db` serve de memo entre
    ciclos e restarts. SH ou reporter diferente: a série antiga não serve.
    """
    entry = cache.peek(f"comtrade.{key}")
    payload = entry.payload if entry is not None else None
    if not isinstance(payload, dict) or payload.get("hs_code") != hs_code:
        return {}, {}
    if payload.get("reporter", BRAZIL) != reporter:
        return {}, {}
    return _point_map(payload.get("totals")), _point_map(payload.get("unit_values"))


async def fetch_flow(key: str, reporter: str = BRAZIL, years: int = 4) -> Fetched:
    hs_code, label = COMMODITIES[key]
    # O ano corrente ainda não fechou; começamos pelo último ano completo.
    last_full = datetime.now(timezone.utc).year - 1
    wanted = [str(y) for y in range(last_full - years + 1, last_full + 1)]
    tail = set(wanted[-_TAIL_YEARS:])

    prev_totals, prev_units = _previous_years(key, hs_code, reporter)
    totals_by_year = {y: v for y, v in prev_totals.items() if y in wanted and y not in tail}
    units_by_year = {y: v for y, v in prev_units.items() if y in wanted and y not in tail}
    # Ano da cauda que a API ainda não devolveu continua com o valor anterior.
    fallback = {y: (prev_totals.get(y), prev_units.get(y)) for y in tail}
    errors: list[str] = []

    for year in wanted:
        if year not in tail and year in totals_by_year:
            continue
        try:
            rows = await _fetch_year(hs_code, reporter, int(year))
        except Exception as exc:  # noqa: BLE001 — um ano faltando não invalida a série
            if _blocked(exc):
                raise ValueError(f"Comtrade HS {hs_code}: {exc}") from exc
            errors.append(f"{year}: {type(exc).__name__}")
            rows = []
        value, weight = _aggregate(rows) if rows else (0.0, 0.0)
        if value > 0:
            totals_by_year[year] = value
            if weight > 0:
                units_by_year[year] = value / weight
        elif year in fallback:
            old_total, old_unit = fallback[year]
            if old_total is not None:
                totals_by_year[year] = old_total
            if old_unit is not None:
                units_by_year[year] = old_unit

    totals: list[Point] = [(y, totals_by_year[y]) for y in wanted if y in totals_by_year]
    unit_values: list[Point] = [(y, units_by_year[y]) for y in wanted if y in units_by_year]

    if not totals and not unit_values:
        raise ValueError(
            f"Comtrade HS {hs_code}: nenhum ano retornou dados"
            + (f" ({'; '.join(errors)})" if errors else "")
        )

    as_of = datetime(int(totals[-1][0]), 12, 31, tzinfo=timezone.utc) if totals else None
    note = "Endpoint preview: 1 período por chamada, dado anual."
    if errors:
        note += f" Anos sem retorno: {', '.join(errors)}."

    return Fetched(
        key=f"comtrade.{key}",
        label=f"UN Comtrade — {label} (importações, reporter {reporter})",
        provider="United Nations Comtrade (preview público)",
        url=f"{BASE}?reporterCode={reporter}&cmdCode={hs_code}&flowCode=M&partnerCode=0",
        status="ok",
        payload={
            "unit_values": unit_values,
            "totals": totals,
            "hs_code": hs_code,
            "reporter": reporter,
        },
        as_of=as_of,
        note=note,
    )


# ---------------------------------------------------------------------------
# Importação mensal por SH6 — substituto do Comex Stat (T05, 04/11/2026)
# ---------------------------------------------------------------------------
#
# O Comex Stat responde 429 a todo POST em /general nesta rede, mesmo após 60 s
# parado, enquanto os GETs do mesmo host respondem 200 (docs/agentes/dados.md).
# O Brasil reporta ao Comtrade os números da própria SECEX, então o preview
# mensal (`/C/M/HS`) entrega o mesmo FOB e peso líquido, com ~1 mês a mais de
# defasagem. Restrições confirmadas ao vivo: um período por chamada, mas vários
# `cmdCode` separados por vírgula na mesma chamada. Por isso uma única coleta
# mensal serve todas as categorias, em vez de uma série por SH6.

MONTHLY_BASE = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"

# 16 meses: o ranking compara o último mês com o mesmo mês do ano anterior
# (months[-13]). Em 04/11/2026 o último mês publicado era 2026-08 (dois meses
# de defasagem); a sobra mantém 13 meses mesmo com um mês a mais de atraso.
_MONTHS_BACK = 16

# Quantos períodos do fim da janela ainda podem mudar: o Comtrade publica com
# ~2 meses de defasagem e revisa o mês seguinte, então 3 cobrem os dois + 1 de
# folga. O resto da janela já fechou e não é mais pedido: em 10/11/2026 os 13
# meses fechados custavam 13 × 18,2 s = 4 min por ciclo (medido na 1ª coleta).
# `_MONTHS_BACK` continua 16 porque define a série devolvida, não o que se pede.
_TAIL_MONTHS = 3

_monthly_lock = asyncio.Lock()


class _MonthlyCycle:
    """Pedidos mensais do ciclo, compartilhados pelas 9 categorias (T42b).

    Antes o memo tinha os períodos pedidos na chave e não guardava falha: cada
    categoria com meses fechados diferentes virava um lote novo, e cada 429
    era repetido pela categoria seguinte — 79 pedidos no teste de 10/11/2026
    em vez de 3. Agora cada período é pedido no máximo uma vez por ciclo, e um
    bloqueio (403, 429, disjuntor) vale para todas as categorias do ciclo.
    """

    def __init__(self, key: tuple[str, tuple[str, ...]]) -> None:
        self.key = key
        self.rows: dict[str, tuple[float, list[dict]]] = {}
        self.failed: dict[str, tuple[float, str]] = {}
        self.blocked: tuple[float, BaseException] | None = None

    @staticmethod
    def _live(stamp: float, now: float) -> bool:
        return now - stamp < _CYCLE_S

    def blocked_now(self, now: float) -> BaseException | None:
        if self.blocked is not None and self._live(self.blocked[0], now):
            return self.blocked[1]
        return None

    def settled(self, period: str, now: float) -> bool:
        """Já pedido neste ciclo, com sucesso ou falha: não pedir de novo."""
        got = self.rows.get(period) or self.failed.get(period)
        return got is not None and self._live(got[0], now)


# Um ciclo por vez: mês ou catálogo novo descarta o anterior.
_monthly_memo: dict[tuple[str, tuple[str, ...]], _MonthlyCycle] = {}


def _cycle_for(key: tuple[str, tuple[str, ...]]) -> _MonthlyCycle:
    cycle = _monthly_memo.get(key)
    if cycle is None:
        _monthly_memo.clear()
        cycle = _monthly_memo[key] = _MonthlyCycle(key)
    return cycle


def _recent_periods(months_back: int = _MONTHS_BACK) -> list[str]:
    """Períodos AAAAMM do mais antigo ao mês passado (o corrente não fechou)."""
    today = datetime.now(timezone.utc)
    last = today.year * 12 + (today.month - 1) - 1
    return [f"{m // 12}{m % 12 + 1:02d}" for m in range(last - months_back + 1, last + 1)]


async def _fetch_month(period: str, codes: tuple[str, ...]) -> list[dict]:
    params = {
        "reporterCode": BRAZIL,
        "period": period,
        "partnerCode": WORLD_PARTNER,
        "cmdCode": ",".join(codes),
        "flowCode": "M",
    }
    return (await _get(MONTHLY_BASE, params)).get("data") or []


def _group_monthly(rows_by_period: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """SH6 -> meses no formato que o ranking já lê do Comex Stat."""
    sums: dict[str, dict[str, list[float]]] = {}
    for period, rows in rows_by_period.items():
        for row in rows:
            code = str(row.get("cmdCode") or "")
            try:
                fob = float(row.get("primaryValue") or 0)
                kg = float(row.get("netWgt") or 0)
            except (TypeError, ValueError):
                continue
            slot = sums.setdefault(code, {}).setdefault(period, [0.0, 0.0])
            slot[0] += fob
            slot[1] += kg

    out: dict[str, list[dict]] = {}
    for code, by_period in sums.items():
        months = []
        for period in sorted(by_period):
            fob, kg = by_period[period]
            # Peso zero ou ausente não vira US$/kg: o mês fica de fora.
            if fob <= 0 or kg <= 0:
                continue
            months.append(
                {
                    "period": f"{period[:4]}-{period[4:]}",
                    "fob_usd": fob,
                    "kg": kg,
                    "usd_per_kg": fob / kg,
                }
            )
        if months:
            out[code] = months
    return out


async def _monthly_batch(
    codes: tuple[str, ...], missing_closed: tuple[str, ...] = ()
) -> dict[str, list[dict]]:
    """Coleta os períodos pedidos uma vez para todos os SH6; as categorias leem do ciclo.

    Pede a cauda (`_TAIL_MONTHS`) e, só quando a categoria ainda não os tem no
    cache, os meses fechados que faltam. Período já pedido no ciclo (com
    sucesso ou falha) não é pedido de novo; bloqueio interrompe o ciclo todo.
    Passado `_CYCLE_S`, tudo é pedido outra vez — o TTLCache decide quando.
    """
    periods = _recent_periods()
    wanted = tuple(periods[-_TAIL_MONTHS:]) + tuple(p for p in missing_closed if p in periods)
    async with _monthly_lock:
        cycle = _cycle_for((periods[-1], codes))
        now = time.monotonic()
        blocked = cycle.blocked_now(now)
        if blocked is not None:
            raise ValueError(f"Comtrade mensal: {blocked}") from blocked

        for period in wanted:
            if cycle.settled(period, now):
                continue
            try:
                rows = await _fetch_month(period, codes)
            except Exception as exc:  # noqa: BLE001 — um mês faltando não invalida a série
                if _blocked(exc):
                    cycle.blocked = (time.monotonic(), exc)
                    raise ValueError(f"Comtrade mensal: {exc}") from exc
                cycle.failed[period] = (time.monotonic(), f"{period}: {type(exc).__name__}")
                continue
            cycle.rows[period] = (time.monotonic(), rows)
            cycle.failed.pop(period, None)

        rows_by_period = {p: cycle.rows[p][1] for p in wanted if p in cycle.rows}
        grouped = _group_monthly(rows_by_period)
        if not grouped:
            errors = [cycle.failed[p][1] for p in wanted if p in cycle.failed]
            raise ValueError(
                "Comtrade mensal: nenhum mês retornou dados"
                + (f" ({'; '.join(errors)})" if errors else "")
            )
        return grouped


def _previous_months(category_key: str, sh6: str) -> dict[str, dict]:
    """Meses da coleta anterior desta categoria, lidos do cache (mesmo vencido).

    É a persistência dos meses fechados: eles não mudam mais, então a entrada
    de `cache.db` serve de memo entre processos e evita repetir os 13 pedidos
    de ~18 s a cada restart. A entrada vencida também vale — mês fechado não
    tem prazo. Quem chama descarta os meses que ainda estão na cauda.
    """
    entry = cache.peek(f"comtrade_monthly.{category_key}")
    payload = entry.payload if entry is not None else None
    if not isinstance(payload, dict) or payload.get("sh6") != sh6:
        # Categoria que trocou de SH6 no catálogo: a série antiga não serve.
        return {}
    months = payload.get("months")
    if not isinstance(months, list):
        return {}
    out: dict[str, dict] = {}
    for month in months:
        if isinstance(month, dict) and isinstance(month.get("period"), str):
            out[month["period"]] = month
    return out


async def fetch_monthly_imports(
    category_key: str, sh6: str, label: str, all_sh6: list[str]
) -> Fetched:
    """Mesmo contrato de `comexstat.fetch_imports`, com fonte UN Comtrade.

    `all_sh6` é a lista de todos os SH6 do catálogo: entra numa única coleta
    compartilhada. Categoria cujo SH6 não voltou levanta erro — o slot fica
    `unavailable` e o painel mostra a coluna vazia, nunca um número estimado.
    """
    codes = tuple(sorted(set(all_sh6) | {sh6}))
    periods = _recent_periods()
    tail = periods[-_TAIL_MONTHS:]
    closed = periods[:-_TAIL_MONTHS]
    formatted = {p: f"{p[:4]}-{p[4:]}" for p in periods}
    in_window = set(formatted.values())

    previous = _previous_months(category_key, sh6)
    kept = {p: m for p, m in previous.items() if p in in_window and p < formatted[tail[0]]}
    missing = tuple(p for p in closed if formatted[p] not in kept)

    grouped = await _monthly_batch(codes, missing)
    merged = dict(kept)
    merged.update({m["period"]: m for m in grouped.get(sh6) or []})
    months = [merged[p] for p in sorted(merged)]
    if not months:
        raise ValueError(f"Comtrade mensal: SH6 {sh6} sem meses com valor e peso")

    as_of = datetime.strptime(months[-1]["period"] + "-01", "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    return Fetched(
        key=f"comtrade_monthly.{category_key}",
        label=f"UN Comtrade — importação mensal de {label} (SH6 {sh6})",
        provider="United Nations Comtrade (preview público), dado da SECEX",
        url=f"{MONTHLY_BASE}?reporterCode={BRAZIL}&cmdCode={sh6}&flowCode=M&partnerCode=0",
        status="ok",
        payload={"months": months, "sh6": sh6},
        as_of=as_of,
        note="Valor FOB e peso líquido mensais reportados pelo Brasil ao Comtrade.",
    )
