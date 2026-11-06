"""UN Comtrade — endpoint público de preview (sem chave).

    https://comtradeapi.un.org/public/v1/preview/C/A/HS
        ?reporterCode=76&period=2024&partnerCode=0&cmdCode=854232&flowCode=M

Restrição confirmada ao vivo: o preview aceita **um único período por
chamada** ("Maximum number of periods for preview is 1") e devolve 429 para
rajadas paralelas. Por isso montamos a série ano a ano, em fila.

Serve para ancorar as teses em fluxo físico de comércio, não só em preço:
  280429 -> outros gases raros (inclui hélio) — a tese do Estreito de Ormuz
  280530 -> compostos de terras raras
  854232 -> memórias (DRAM/NAND)
  854231 -> processadores e controladores
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..cache import Fetched
from ..http import FetchError, breaker_guard, breaker_record, get_json, limiter
from ..series_utils import Point

BASE = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

BRAZIL = "76"
WORLD_PARTNER = "0"

# O preview é rigoroso com taxa: uma requisição por vez, com respiro entre elas.
_CONCURRENCY = 1
_SPACING_S = 0.35

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


def _note_failure(exc: Exception) -> None:
    if isinstance(exc, FetchError) and exc.status_code == _QUOTA_STATUS:
        raw = exc.retry_after
        cooldown = _QUOTA_FALLBACK_S if raw is None else min(max(raw, _QUOTA_MIN_S), _QUOTA_MAX_S)
        breaker_record(_BREAKER, ok=False, threshold=1, cooldown=cooldown)


async def _get(url: str, params: dict) -> dict:
    async with limiter("comtrade", _CONCURRENCY):
        # Checado dentro do semáforo: quem espera na fila enxerga o 403 de quem
        # acabou de passar e desiste sem pedido.
        breaker_guard(_BREAKER)
        try:
            data = await get_json(url, params=params)
        except Exception as exc:
            _note_failure(exc)
            raise
        breaker_record(_BREAKER, ok=True)
        await asyncio.sleep(_SPACING_S)
    return data or {}


def _blocked(exc: Exception) -> bool:
    """Cota esgotada ou disjuntor aberto: os próximos períodos falhariam igual."""
    return isinstance(exc, FetchError) and (
        exc.status_code == _QUOTA_STATUS or "disjuntor aberto" in str(exc)
    )


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


async def fetch_flow(key: str, reporter: str = BRAZIL, years: int = 4) -> Fetched:
    hs_code, label = COMMODITIES[key]
    # O ano corrente ainda não fechou; começamos pelo último ano completo.
    last_full = datetime.now(timezone.utc).year - 1
    wanted = list(range(last_full - years + 1, last_full + 1))

    unit_values: list[Point] = []
    totals: list[Point] = []
    errors: list[str] = []

    for year in wanted:
        try:
            rows = await _fetch_year(hs_code, reporter, year)
        except Exception as exc:  # noqa: BLE001 — um ano faltando não invalida a série
            if _blocked(exc):
                raise ValueError(f"Comtrade HS {hs_code}: {exc}") from exc
            errors.append(f"{year}: {type(exc).__name__}")
            continue
        if not rows:
            continue
        value, weight = _aggregate(rows)
        if value > 0:
            totals.append((str(year), value))
        if value > 0 and weight > 0:
            unit_values.append((str(year), value / weight))

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
        payload={"unit_values": unit_values, "totals": totals, "hs_code": hs_code},
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

_monthly_lock = asyncio.Lock()
_monthly_memo: dict[tuple[str, tuple[str, ...]], dict[str, list[dict]]] = {}


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


async def _monthly_batch(codes: tuple[str, ...]) -> dict[str, list[dict]]:
    """Coleta os meses uma vez para todos os SH6; as categorias leem do memo.

    O memo vale para o mês-calendário corrente. Ele não substitui o TTLCache:
    só evita que N categorias disparem N vezes as mesmas 16 chamadas no mesmo
    ciclo. Falha não é memorizada, para que o próximo ciclo tente de novo.
    """
    memo_key = (_recent_periods()[-1], codes)
    async with _monthly_lock:
        if memo_key in _monthly_memo:
            return _monthly_memo[memo_key]

        rows_by_period: dict[str, list[dict]] = {}
        errors: list[str] = []
        for period in _recent_periods():
            try:
                rows_by_period[period] = await _fetch_month(period, codes)
            except Exception as exc:  # noqa: BLE001 — um mês faltando não invalida a série
                if _blocked(exc):
                    raise ValueError(f"Comtrade mensal: {exc}") from exc
                errors.append(f"{period}: {type(exc).__name__}")

        grouped = _group_monthly(rows_by_period)
        if not grouped:
            raise ValueError(
                "Comtrade mensal: nenhum mês retornou dados"
                + (f" ({'; '.join(errors)})" if errors else "")
            )
        _monthly_memo.clear()
        _monthly_memo[memo_key] = grouped
        return grouped


async def fetch_monthly_imports(
    category_key: str, sh6: str, label: str, all_sh6: list[str]
) -> Fetched:
    """Mesmo contrato de `comexstat.fetch_imports`, com fonte UN Comtrade.

    `all_sh6` é a lista de todos os SH6 do catálogo: entra numa única coleta
    compartilhada. Categoria cujo SH6 não voltou levanta erro — o slot fica
    `unavailable` e o painel mostra a coluna vazia, nunca um número estimado.
    """
    codes = tuple(sorted(set(all_sh6) | {sh6}))
    grouped = await _monthly_batch(codes)
    months = grouped.get(sh6)
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
