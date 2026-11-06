"""SEC EDGAR XBRL — capex de datacenter, receita e estoque de memória.

A API `companyconcept` é pública e sem chave:

    https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<tag>.json

A SEC exige `User-Agent` identificável e no máximo 10 requisições por segundo.
O projeto usa o UA de `config.py` e um semáforo de 4 com respiro entre chamadas.

O que este provider acrescenta ao painel: **alocação**, não preço de ação. O
capex agregado dos cinco maiores compradores de capacidade de IA e o giro de
estoque da Micron mostram se a cadeia está sendo puxada para datacenter antes
de o consumidor doméstico ser atendido.

Limitações declaradas:
* trimestres fiscais diferentes são alinhados por trimestre-calendário;
* TTM = soma dos últimos quatro trimestres, sempre com cobertura mínima;
* não há preço spot de DRAM/NAND keyless — isso continua sendo lacuna.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from ..cache import Fetched
from ..http import FetchError, get_json, limiter
from ..series_utils import Point

log = logging.getLogger(__name__)

BASE = "https://data.sec.gov/api/xbrl/companyconcept"
# A SEC aceita até 10 req/s; 4 simultâneas com 120 ms de respiro ficam abaixo.
_CONCURRENCY = 4
_SPACING_S = 0.12


@dataclass(frozen=True)
class Company:
    name: str
    cik: int
    capex_tags: tuple[str, ...] = ()
    revenue_tags: tuple[str, ...] = ()


CAPEX_COMPANIES: tuple[Company, ...] = (
    Company(
        "Microsoft",
        789019,
        capex_tags=("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
    Company(
        "Amazon",
        1018724,
        capex_tags=(
            "PaymentsToAcquireProductiveAssets",
            "PaymentsToAcquirePropertyPlantAndEquipment",
        ),
    ),
    Company(
        "Alphabet",
        1652044,
        capex_tags=("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
    Company(
        "Meta",
        1326801,
        capex_tags=("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
    Company(
        "Oracle",
        1341439,
        capex_tags=("PaymentsToAcquirePropertyPlantAndEquipment",),
    ),
)

CHIP_COMPANIES: tuple[Company, ...] = (
    Company(
        "NVIDIA",
        1045810,
        revenue_tags=(
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        ),
    ),
    Company(
        "Micron",
        723125,
        revenue_tags=(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ),
    ),
    Company(
        "AMD",
        2488,
        revenue_tags=(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
        ),
    ),
)

MICRON = CHIP_COMPANIES[1]


# ---------------- parsing XBRL ----------------


def _unit_rows(data: dict, unit: str = "USD") -> list[dict]:
    return list(((data or {}).get("units") or {}).get(unit) or [])


def _flow_rows(data: dict) -> list[dict]:
    """Trimestres de um conceito de fluxo (receita/capex), sem YTD.

    O XBRL mistura trimestre isolado e acumulado do ano. Primeiro deduplicamos
    por (start, end); depois, para cada início de exercício, derivamos o
    trimestre por diferença dos acumulados (Q2 = H1 − Q1 etc.). Isso é
    necessário porque Alphabet, Meta e Oracle só publicam Q1 e acumulados no
    `companyconcept`; ficar com os períodos de 90 dias descartaria três
    trimestres de cada ano.
    """
    dedup: dict[tuple[str, str], dict] = {}
    for row in _unit_rows(data):
        start, end = row.get("start"), row.get("end")
        if not start or not end:
            continue
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if not 60 <= days <= 380:
            continue
        key = (start, end)
        prev = dedup.get(key)
        if prev is None or str(row.get("filed", "")) >= str(prev.get("filed", "")):
            dedup[key] = row

    by_start: dict[str, list[dict]] = {}
    for row in dedup.values():
        by_start.setdefault(row["start"], []).append(row)

    def duration(row: dict) -> int:
        return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days

    derived: dict[str, dict] = {}
    for start, group in by_start.items():
        group.sort(key=lambda r: r["end"])
        # Grupo que começa num período anual é comparação de 12 meses, não
        # início de exercício: não dá para derivar trimestre dele.
        if not group or duration(group[0]) > 120:
            continue
        prev_val = 0.0
        prev_end = start
        for row in group:
            try:
                span = (date.fromisoformat(row["end"]) - date.fromisoformat(prev_end)).days
                value = float(row["val"])
            except (TypeError, ValueError):
                break
            if not 60 <= span <= 120 or value < prev_val:
                break
            quarter = value - prev_val
            direct = 60 <= duration(row) <= 110
            candidate = {
                "start": prev_end,
                "end": row["end"],
                "val": quarter,
                "filed": str(row.get("filed", "")),
                "direct": direct,
            }
            old = derived.get(row["end"])
            if old is None:
                derived[row["end"]] = candidate
            elif direct and not old["direct"]:
                derived[row["end"]] = candidate
            elif direct == old["direct"] and candidate["filed"] >= old["filed"]:
                derived[row["end"]] = candidate
            prev_val, prev_end = value, row["end"]

    return [derived[k] for k in sorted(derived)]


def _instant_rows(data: dict) -> list[dict]:
    """Saldos de balanço (estoque): só `end`, sem `start`."""
    dedup: dict[str, dict] = {}
    for row in _unit_rows(data):
        end = row.get("end")
        if not end or row.get("start"):
            continue
        prev = dedup.get(end)
        if prev is None or str(row.get("filed", "")) >= str(prev.get("filed", "")):
            dedup[end] = row
    return [dedup[k] for k in sorted(dedup)]


def _quarter_key(iso: str) -> tuple[int, int]:
    d = date.fromisoformat(iso)
    return d.year, (d.month - 1) // 3 + 1


def _next_quarter(key: tuple[int, int]) -> tuple[int, int]:
    year, quarter = key
    return (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def _aggregate_quarters(
    per_company: list[list[dict]],
) -> list[dict]:
    """Soma o fluxo trimestral de várias empresas por trimestre-calendário.

    Empresas com ano fiscal deslocado (Oracle, NVIDIA) caem no trimestre do
    calendário em que o período termina. Cada bucket guarda a maior data real
    de fechamento e quantas empresas contribuíram.
    """
    buckets: dict[tuple[int, int], dict] = {}
    for rows in per_company:
        latest: dict[tuple[int, int], dict] = {}
        for row in rows:
            latest[_quarter_key(row["end"])] = row  # rows ordenadas: último vence
        for key, row in latest.items():
            bucket = buckets.setdefault(
                key, {"value": 0.0, "count": 0, "end": row["end"]}
            )
            bucket["value"] += float(row["val"])
            bucket["count"] += 1
            bucket["end"] = max(bucket["end"], row["end"])
    return [
        {"key": key, **buckets[key]}
        for key in sorted(buckets)
    ]


def _rolling_ttm(quarters: list[dict], *, min_companies: int) -> list[Point]:
    """TTM = 4 trimestres consecutivos com cobertura mínima de empresas."""
    out: list[Point] = []
    for i in range(3, len(quarters)):
        window = quarters[i - 3 : i + 1]
        if any(w["count"] < min_companies for w in window):
            continue
        if any(
            window[j + 1]["key"] != _next_quarter(window[j]["key"])
            for j in range(3)
        ):
            continue
        out.append((window[-1]["end"], sum(w["value"] for w in window)))
    return out


def _growth_points(ttm: list[Point]) -> list[Point]:
    """Crescimento ano contra ano de cada TTM, exigindo ~365 dias de distância."""
    out: list[Point] = []
    for i in range(4, len(ttm)):
        try:
            gap = (
                date.fromisoformat(ttm[i][0]) - date.fromisoformat(ttm[i - 4][0])
            ).days
        except ValueError:
            continue
        if not 300 <= gap <= 430 or not ttm[i - 4][1]:
            continue
        out.append((ttm[i][0], (ttm[i][1] / ttm[i - 4][1] - 1.0) * 100.0))
    return out


def _ttm_at(rows: list[dict]) -> list[Point]:
    """TTM de uma única empresa, ancorado no fechamento real de cada trimestre."""
    out: list[Point] = []
    for i in range(3, len(rows)):
        out.append((rows[i]["end"], sum(float(rows[j]["val"]) for j in range(i - 3, i + 1))))
    return out


def _pct(now: float | None, before: float | None) -> float | None:
    if now is None or not before:
        return None
    return (now / before - 1.0) * 100.0


def _as_of(rows: list[dict]) -> datetime | None:
    if not rows:
        return None
    try:
        return datetime.fromisoformat(max(r["end"] for r in rows)).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


# ---------------- HTTP ----------------


async def _concept(cik: int, tag: str) -> dict:
    url = f"{BASE}/CIK{cik:010d}/us-gaap/{tag}.json"
    async with limiter("sec", _CONCURRENCY):
        data = await get_json(url)
        await asyncio.sleep(_SPACING_S)
    return data


async def _first_tag(cik: int, tags: tuple[str, ...]) -> tuple[dict, str]:
    errors: list[str] = []
    for tag in tags:
        try:
            return await _concept(cik, tag), tag
        except FetchError as exc:
            errors.append(f"{tag}: {exc}")
            continue
    raise FetchError(f"CIK {cik}: nenhum conceito disponível ({'; '.join(errors)})")


# ---------------- coletas ----------------


async def fetch_capex_hyperscaler() -> Fetched:
    per_company: list[list[dict]] = []
    meta: list[dict] = []
    errors: list[str] = []

    for company in CAPEX_COMPANIES:
        try:
            data, tag = await _first_tag(company.cik, company.capex_tags)
        except Exception as exc:  # noqa: BLE001 — uma empresa não invalida as outras
            errors.append(f"{company.name}: {type(exc).__name__}")
            continue
        rows = _flow_rows(data)
        if not rows:
            errors.append(f"{company.name}: sem trimestres")
            continue
        per_company.append(rows)
        own_ttm = _ttm_at(rows)
        own_growth = _growth_points(own_ttm)
        meta.append(
            {
                "name": company.name,
                "cik": company.cik,
                "tag": tag,
                "ttm_usd": own_ttm[-1][1] if own_ttm else None,
                "growth_pct": round(own_growth[-1][1], 2) if own_growth else None,
                "as_of": rows[-1]["end"],
            }
        )

    if not per_company:
        raise ValueError(
            "SEC capex: nenhuma empresa retornou trimestres"
            + (f" ({'; '.join(errors)})" if errors else "")
        )

    quarters = _aggregate_quarters(per_company)
    # Exigimos 3 das 5 empresas para um TTM não ficar artificialmente baixo.
    ttm = _rolling_ttm(quarters, min_companies=3)
    growth = _growth_points(ttm)
    latest_ttm = ttm[-1][1] if ttm else None
    latest_growth = growth[-1][1] if growth else None
    as_of = _as_of([r for rows in per_company for r in rows])

    note = (
        "XBRL companyconcept; 5 hyperscalers; trimestres alinhados por "
        "trimestre-calendário; TTM exige 3 empresas por trimestre."
    )
    if errors:
        note += f" Sem retorno: {', '.join(errors)}."
    if latest_growth is not None:
        note += f" Capex TTM crescendo {latest_growth:+.1f}% a/a."

    return Fetched(
        key="sec.capex_hyperscaler",
        label="Capex trimestral dos hyperscalers (MSFT, AMZN, GOOGL, META, ORCL)",
        provider="SEC EDGAR — XBRL companyconcept",
        url=f"{BASE}/CIK0000789019/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment.json",
        status="ok",
        payload={
            "companies": meta,
            "quarterly": [[q["end"], q["value"]] for q in quarters],
            "ttm_points": ttm,
            "growth_points": growth,
            "ttm_usd": latest_ttm,
            "ttm_growth_pct": round(latest_growth, 2) if latest_growth is not None else None,
            "errors": errors,
        },
        as_of=as_of,
        note=note,
    )


async def fetch_chip_revenue() -> Fetched:
    per_company: list[list[dict]] = []
    meta: list[dict] = []
    errors: list[str] = []

    for company in CHIP_COMPANIES:
        try:
            data, tag = await _first_tag(company.cik, company.revenue_tags)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{company.name}: {type(exc).__name__}")
            continue
        rows = _flow_rows(data)
        if not rows:
            errors.append(f"{company.name}: sem trimestres")
            continue
        per_company.append(rows)
        own_ttm = _ttm_at(rows)
        own_growth = _growth_points(own_ttm)
        meta.append(
            {
                "name": company.name,
                "cik": company.cik,
                "tag": tag,
                "ttm_usd": own_ttm[-1][1] if own_ttm else None,
                "growth_pct": round(own_growth[-1][1], 2) if own_growth else None,
                "as_of": rows[-1]["end"],
            }
        )

    if not per_company:
        raise ValueError(
            "SEC receita: nenhuma empresa retornou trimestres"
            + (f" ({'; '.join(errors)})" if errors else "")
        )

    quarters = _aggregate_quarters(per_company)
    ttm = _rolling_ttm(quarters, min_companies=2)
    growth = _growth_points(ttm)
    latest_ttm = ttm[-1][1] if ttm else None
    latest_growth = growth[-1][1] if growth else None
    as_of = _as_of([r for rows in per_company for r in rows])

    note = (
        "XBRL companyconcept; NVIDIA, Micron e AMD; receita trimestral agregada; "
        "TTM exige 2 empresas por trimestre."
    )
    if errors:
        note += f" Sem retorno: {', '.join(errors)}."

    return Fetched(
        key="sec.chip_revenue",
        label="Receita trimestral de chips (NVDA, MU, AMD)",
        provider="SEC EDGAR — XBRL companyconcept",
        url=f"{BASE}/CIK0001045810/us-gaap/Revenues.json",
        status="ok",
        payload={
            "companies": meta,
            "quarterly": [[q["end"], q["value"]] for q in quarters],
            "ttm_points": ttm,
            "growth_points": growth,
            "ttm_usd": latest_ttm,
            "ttm_growth_pct": round(latest_growth, 2) if latest_growth is not None else None,
            "errors": errors,
        },
        as_of=as_of,
        note=note,
    )


async def fetch_memory_inventory() -> Fetched:
    inv_data, inv_tag = await _first_tag(MICRON.cik, ("InventoryNet",))
    rev_data, rev_tag = await _first_tag(MICRON.cik, MICRON.revenue_tags)

    inventory = _instant_rows(inv_data)
    revenue = _flow_rows(rev_data)
    if not inventory or not revenue:
        raise ValueError(
            f"SEC estoque: Micron sem {'estoque' if not inventory else 'receita'}"
        )

    # Receita TTM ancorada no fechamento de cada trimestre.
    rev_ttm = _ttm_at(revenue)
    inv_by_end = {row["end"]: float(row["val"]) for row in inventory}

    ratio_points: list[Point] = []
    for end, rev in rev_ttm:
        inv = inv_by_end.get(end)
        if inv is None or rev <= 0:
            continue
        ratio_points.append((end, inv / rev))

    if not ratio_points:
        raise ValueError("SEC estoque: sem interseção entre estoque e receita trimestral")

    latest_ratio = ratio_points[-1][1]
    ratio_change = None
    if len(ratio_points) >= 5 and ratio_points[-5][1]:
        ratio_change = (latest_ratio / ratio_points[-5][1] - 1.0) * 100.0

    inventory_usd = inv_by_end.get(ratio_points[-1][0])
    revenue_ttm = dict(rev_ttm).get(ratio_points[-1][0])

    note = (
        f"XBRL companyconcept (Micron); estoque {inv_tag}, receita {rev_tag}. "
        "Razão = estoque de balanço ÷ receita TTM."
    )
    return Fetched(
        key="sec.memory_inventory",
        label="Estoque/receita de memória — Micron",
        provider="SEC EDGAR — XBRL companyconcept",
        url=f"{BASE}/CIK0000723125/us-gaap/InventoryNet.json",
        status="ok",
        payload={
            "inventory_points": [[r["end"], float(r["val"])] for r in inventory],
            "revenue_points": [[r["end"], float(r["val"])] for r in revenue],
            "ratio_points": ratio_points,
            "inventory_usd": inventory_usd,
            "revenue_ttm_usd": revenue_ttm,
            "ratio": latest_ratio,
            "ratio_change_pct": round(ratio_change, 2) if ratio_change is not None else None,
            "inventory_tag": inv_tag,
            "revenue_tag": rev_tag,
        },
        as_of=_as_of(inventory),
        note=note,
    )


# ---------------- trimestres para dias de estoque (T30) ----------------
#
# Dias de estoque = estoque ÷ (CPV ÷ dias do trimestre), com a duração real do
# trimestre fiscal: o Q4 FY2026 da Micron teve 98 dias (ano de 53 semanas) e
# inflaria o número em ~7% com um divisor fixo. O CPV vem do mesmo
# `_flow_rows` da receita (trimestre isolado ou derivado de acumulados).

COGS_TAGS = ("CostOfGoodsAndServicesSold", "CostOfRevenue")
INTEL = Company("Intel", 50863)
LOGIC_COMPANIES: tuple[tuple[str, Company], ...] = (
    ("NVDA", CHIP_COMPANIES[0]),
    ("AMD", CHIP_COMPANIES[2]),
    ("INTC", INTEL),
)
MEMORY_COMPANIES: tuple[tuple[str, Company], ...] = (("MU", MICRON),)


async def _latest_flow(cik: int, tags: tuple[str, ...]) -> tuple[list[dict], str]:
    """Entre tags equivalentes, a que tem o trimestre mais recente.

    Empresas trocam de tag ao longo dos anos (a NVIDIA usa `CostOfRevenue`, a
    AMD `CostOfGoodsAndServicesSold`); a tag antiga para no tempo e não pode
    vencer só por vir primeiro na lista.
    """
    best: tuple[list[dict], str] | None = None
    errors: list[str] = []
    for tag in tags:
        try:
            rows = _flow_rows(await _concept(cik, tag))
        except FetchError as exc:
            errors.append(f"{tag}: {type(exc).__name__}")
            continue
        if rows and (best is None or rows[-1]["end"] > best[0][-1]["end"]):
            best = (rows, tag)
    if best is None:
        raise FetchError(f"CIK {cik}: sem CPV trimestral ({'; '.join(errors) or 'vazio'})")
    return best


def _quarters(cogs: list[dict], inventory: list[dict]) -> list[dict]:
    """Trimestres com CPV e estoque no mesmo fechamento."""
    inv = {row["end"]: row for row in inventory}
    out: list[dict] = []
    for row in cogs:
        stock = inv.get(row["end"])
        if stock is None:
            continue
        try:
            days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
            value, cost = float(stock["val"]), float(row["val"])
        except (TypeError, ValueError, KeyError):
            continue
        if days <= 0 or cost <= 0 or value < 0:
            continue
        out.append({
            "end": row["end"],
            "days": days,
            "inventory": value,
            "cogs": cost,
            "filed": max(str(row.get("filed") or ""), str(stock.get("filed") or "")) or None,
        })
    return out


async def _fetch_quarters(key: str, label: str, companies: tuple[tuple[str, Company], ...]) -> Fetched:
    by_company: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    errors: list[str] = []
    for ticker, company in companies:
        try:
            inv_data, inv_tag = await _first_tag(company.cik, ("InventoryNet",))
            cogs_rows, cogs_tag = await _latest_flow(company.cik, COGS_TAGS)
        except Exception as exc:  # noqa: BLE001 — uma empresa não invalida as outras
            errors.append(f"{company.name}: {type(exc).__name__}")
            continue
        quarters = _quarters(cogs_rows, _instant_rows(inv_data))
        if not quarters:
            errors.append(f"{company.name}: sem trimestre com estoque e CPV")
            continue
        by_company[ticker] = quarters
        meta[ticker] = {"name": company.name, "cik": company.cik, "inventory_tag": inv_tag, "cogs_tag": cogs_tag}
    if not by_company:
        raise ValueError(f"SEC {label}: nenhuma empresa" + (f" ({'; '.join(errors)})" if errors else ""))
    ends = [q["end"] for qs in by_company.values() for q in qs]
    note = "XBRL companyconcept: InventoryNet (saldo) e CPV trimestral; dias = duração real do trimestre."
    if errors:
        note += f" Sem retorno: {', '.join(errors)}."
    return Fetched(
        key=key,
        label=f"Trimestres de estoque e CPV — {label}",
        provider="SEC EDGAR — XBRL companyconcept",
        url=f"{BASE}/CIK{companies[0][1].cik:010d}/us-gaap/InventoryNet.json",
        status="ok",
        payload={"by_company": by_company, "companies": meta, "errors": errors},
        as_of=datetime.fromisoformat(max(ends)).replace(tzinfo=timezone.utc),
        note=note,
    )


async def fetch_memory_quarters() -> Fetched:
    return await _fetch_quarters("sec.memory_quarters", "memória (Micron)", MEMORY_COMPANIES)


async def fetch_logic_quarters() -> Fetched:
    return await _fetch_quarters("sec.logic_quarters", "lógica (NVIDIA, AMD, Intel)", LOGIC_COMPANIES)
