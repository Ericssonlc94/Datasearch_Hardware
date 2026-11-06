"""TSMC — receita consolidada mensal (sinal de demanda da frente lógica/demanda).

Duas fontes públicas da bolsa de Taiwan, sem chave:

    https://openapi.twse.com.tw/v1/opendata/t187ap05_L
        Receita mensal de todas as listadas (JSON). Só o último mês; valores
        em NT$ mil. `資料年月` = AAAMM Minguo (115 = 2026) e `出表日期` = data de
        publicação (AAAMMDD Minguo). Única fonte da data real de divulgação.

    https://mops.twse.com.tw/mops/api/t05st10_ifrs  (POST JSON)
        API da tela de receita mensal do MOPS novo, uma empresa e um mês por
        chamada; devolve o mês e o mesmo mês do ano anterior (NT$ mil). Dá o
        histórico: uma chamada por mês de anos alternados.

Robots (verificado em 05/11/2026): openapi.twse e mops.twse respondem 404
(tudo permitido, RFC 9309). O MOPS antigo (`mopsov.twse.com.tw`) proíbe tudo
(`Disallow: /`) e o RI da TSMC (`investor.tsmc.com`) devolve desafio do
Cloudflare ao cliente do app — os dois ficam de fora, sem contorno.

A divulgação legal é até o dia 10 do mês seguinte. Para os meses que não vêm
da TWSE, `released` fica com a data-limite (dia 10) e `released_estimated`
lista esses meses — a reconstrução histórica não pode usar um mês antes de ele
existir.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timezone

from ..cache import Fetched
from ..http import ChallengeDetected, FetchError, get_json, limiter, post_json

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
MOPS_URL = "https://mops.twse.com.tw/mops/api/t05st10_ifrs"
TSMC_CODE = "2330"
# 8 anos (4 anos consultados, cada um traz o anterior): 60 meses de "normal"
# + 12 do a/a + 3 da soma (supply_fronts.NORMAL_MONTHS) com folga.
HISTORY_PAIRS = 4
_CONCURRENCY = 1
_SPACING_S = 1.5
_NUMBER_RE = re.compile(r"\d{1,3}(,\d{3})*|\d+")


def _minguo_period(raw: str) -> str | None:
    """`11509` → `2026-09`."""
    raw = (raw or "").strip()
    if not re.fullmatch(r"\d{5}", raw):
        return None
    year, month = int(raw[:3]) + 1911, int(raw[3:])
    return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None


def _minguo_date(raw: str) -> str | None:
    """`1151017` → `2026-10-17`."""
    raw = (raw or "").strip()
    if not re.fullmatch(r"\d{7}", raw):
        return None
    try:
        return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:])).isoformat()
    except ValueError:
        return None


def _deadline(period: str) -> str:
    """Data-limite de divulgação: dia 10 do mês seguinte."""
    year, month = (int(x) for x in period.split("-"))
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(year, month, 10).isoformat()


def parse_twse(rows: list) -> tuple[str, float, str | None] | None:
    """(período, NT$ milhões, data de publicação) da TSMC no JSON da TWSE."""
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("公司代號", "")).strip() != TSMC_CODE:
            continue
        period = _minguo_period(str(row.get("資料年月", "")))
        try:
            value = float(str(row.get("營業收入-當月營收", "")).replace(",", "")) / 1000.0
        except ValueError:
            return None
        if period and value > 0:
            return period, value, _minguo_date(str(row.get("出表日期", "")))
    return None


def _thousands_to_millions(raw: object) -> float | None:
    """`"330,980,920"` (NT$ mil) → 330980.92 (NT$ milhões); o resto é `None`."""
    text = str(raw or "").strip()
    if not _NUMBER_RE.fullmatch(text):
        return None
    value = int(text.replace(",", "")) / 1000.0
    return value if value > 0 else None


def parse_mops(body: object) -> dict[str, float]:
    """Mês consultado e o mesmo mês do ano anterior, em NT$ milhões."""
    if not isinstance(body, dict) or body.get("code") != 200:
        return {}
    result = body.get("result")
    if not isinstance(result, dict):
        return {}
    period = _minguo_period(str(result.get("yymm", "")))
    if period is None:
        return {}
    rows = {
        row[0]: row[1]
        for row in result.get("data") or []
        if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str)
    }
    out: dict[str, float] = {}
    if (now := _thousands_to_millions(rows.get("本月"))) is not None:
        out[period] = now
    if (before := _thousands_to_millions(rows.get("去年同期"))) is not None:
        year, month = period.split("-")
        out[f"{int(year) - 1:04d}-{month}"] = before
    return out


def _mops_queries(last: str) -> list[tuple[int, int]]:
    """(ano, mês) a consultar: anos alternados até `last`, do mais novo.

    Mês do ano corrente ainda não publicado vira consulta do ano anterior,
    senão o fim do ano passado (out–dez) ficaria sem ninguém que o trouxesse.
    """
    last_year, last_month = (int(x) for x in last.split("-"))
    out = []
    for pair in range(HISTORY_PAIRS):
        year = last_year - 2 * pair
        for month in range(12, 0, -1):
            out.append((year, month) if (year, month) <= (last_year, last_month) else (year - 1, month))
    return out


async def _fetch_mops(last: str, errors: list[str]) -> dict[str, float]:
    monthly: dict[str, float] = {}
    for year, month in _mops_queries(last):
        payload = {"companyId": TSMC_CODE, "dataType": "2", "month": str(month),
                   "year": str(year - 1911), "subsidiaryCompanyId": ""}
        try:
            async with limiter("tsmc", _CONCURRENCY):
                body = await post_json(MOPS_URL, payload)
                await asyncio.sleep(_SPACING_S)
        except ChallengeDetected:
            errors.append("MOPS: desafio antirrobô, coleta parada")
            break
        except FetchError as exc:
            errors.append(f"MOPS {year}-{month:02d}: {type(exc).__name__}")
            # Bloqueio ou cota: parar no primeiro, sem insistir.
            if exc.status_code in (403, 429):
                break
            continue
        for period, value in parse_mops(body).items():
            monthly.setdefault(period, value)
    return monthly


def _previous_month(today: date) -> str:
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return f"{year:04d}-{month:02d}"


async def fetch_monthly_revenue() -> Fetched:
    today = datetime.now(timezone.utc).date()
    errors: list[str] = []
    try:
        latest = parse_twse(await get_json(TWSE_URL))
    except FetchError as exc:
        latest = None
        errors.append(f"TWSE: {type(exc).__name__}")

    monthly = await _fetch_mops(latest[0] if latest else _previous_month(today), errors)
    released = {p: _deadline(p) for p in monthly}
    estimated = set(monthly)
    if latest is not None:
        period, value, published = latest
        # A TWSE é a fonte oficial do mês corrente e traz a data real.
        monthly[period] = value
        released[period] = published or _deadline(period)
        if published:
            estimated.discard(period)

    if not monthly:
        raise FetchError("TSMC: nenhum mês lido (TWSE e MOPS)" + (f" — {'; '.join(errors)}" if errors else ""))
    points = sorted(monthly.items())
    last = points[-1][0]
    year, month = (int(x) for x in last.split("-"))
    note = "Receita consolidada mensal, NT$ milhões (histórico pelo MOPS; mês corrente pela TWSE)."
    if errors:
        note += f" Falhas: {', '.join(errors[:5])}."
    return Fetched(
        key="tsmc.monthly_revenue",
        label="TSMC — receita consolidada mensal",
        provider="TWSE OpenAPI (t187ap05_L) + MOPS (t05st10_ifrs)",
        url=TWSE_URL,
        status="ok",
        payload={
            "points": [[p, v] for p, v in points],
            "unit": "NT$ milhões",
            "released": released,
            "released_estimated": sorted(estimated),
        },
        as_of=datetime(year, month, 1, tzinfo=timezone.utc),
        note=note,
    )
