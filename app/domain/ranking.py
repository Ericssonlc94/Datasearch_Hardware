"""Ranking de variação por tipo de hardware, com o corte Brasil.

Distinção que o painel mantém explícita:

* `projected_global_30d_pct` — pressão modelada sobre o preço em dólar,
  a partir dos drivers, sem a camada local.
* `projected_brazil_30d_pct` — a mesma pressão composta com a variação
  cambial esperada de repasse. Impostos ad valorem escalam nível, não
  percentual, então NÃO multiplicamos a variação percentual pela carga
  tributária — seria inflar o número. A carga aparece em
  `brl_impact_per_100usd`, onde ela de fato importa: no valor absoluto.
* `observed_br` / `imports` — dado medido, para o leitor conferir o modelo
  contra a realidade.
"""

from __future__ import annotations

from ..cache import Fetched
from ..schemas import (
    BrazilContext,
    CategoryImport,
    CategoryObservedBR,
    Driver,
    DriverContribution,
    RankingItem,
)
from ..series_utils import to_points
from .catalog import CATEGORIES, Category
from .drivers import DRIVERS_BY_KEY
from .supply_fronts import FRONTS_ENABLED, front_score

# Horizonte exibido ao leitor. `Category.sensitivity_pct` foi calibrado para
# 90 dias; a conversão é linear porque o modelo projeta uma deriva sustentada
# pela pressão atual (não um passeio aleatório): um terço do prazo, um terço
# do movimento. O câmbio usa a variação observada na mesma janela de 30 dias.
HORIZON_DAYS = 30
CALIBRATION_DAYS = 90
HORIZON_FACTOR = HORIZON_DAYS / CALIBRATION_DAYS


def _observed_br(cat: Category, collected: dict[str, Fetched]) -> CategoryObservedBR | None:
    if not cat.ipca_subitem:
        return None
    fetched = collected.get("ibge.ipca_hardware")
    if fetched is None or not fetched.ok:
        return CategoryObservedBR(
            subitem_code=cat.ipca_subitem,
            subitem_label="—",
            status=fetched.status if fetched else "unavailable",
        )
    slot = (fetched.payload or {}).get(cat.ipca_subitem)
    if not slot:
        return CategoryObservedBR(
            subitem_code=cat.ipca_subitem, subitem_label="—", status="unavailable"
        )

    monthly = slot.get("monthly") or []
    yoy = slot.get("yoy") or []
    label = slot.get("label", "—")
    if cat.ipca_is_proxy:
        label = f"{label} (proxy)"

    return CategoryObservedBR(
        subitem_code=cat.ipca_subitem,
        subitem_label=label,
        var_month_pct=monthly[-1][1] if monthly else None,
        var_12m_pct=yoy[-1][1] if yoy else None,
        period=(monthly or yoy)[-1][0] if (monthly or yoy) else None,
        series=to_points(monthly, limit=24),
        status=fetched.status,
    )


# Fontes de importação por categoria, em ordem de preferência. O Comtrade
# mensal substituiu o Comex Stat (bloqueado por WAF, T05); o Comex Stat fica
# como alternativa caso volte a ser ligado. Mesmo payload nas duas:
# months = [{period "AAAA-MM", fob_usd, kg, usd_per_kg}], só meses reais.
IMPORT_SOURCES = (
    ("comtrade_monthly", "UN Comtrade (dado SECEX)"),
    ("comexstat", "Comex Stat (MDIC/SECEX)"),
)


def _year_before(period: str) -> str | None:
    """'2026-08' → '2025-08'; formato inesperado devolve None."""
    try:
        year, month = period.split("-")
        return f"{int(year) - 1:04d}-{int(month):02d}"
    except ValueError:
        return None


def _last_12_months(period: str) -> set[str]:
    """Os 12 AAAA-MM que terminam em `period`, inclusive."""
    year, month = (int(x) for x in period.split("-"))
    out: set[str] = set()
    for _ in range(12):
        out.add(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def _imports(cat: Category, collected: dict[str, Fetched]) -> CategoryImport:
    fetched: Fetched | None = None
    source_label: str | None = None
    for prefix, label in IMPORT_SOURCES:
        candidate = collected.get(f"{prefix}.{cat.key}")
        if candidate is not None and candidate.ok:
            fetched, source_label = candidate, label
            break
        if fetched is None and candidate is not None:
            fetched = candidate  # guarda o status da falha para exibir

    base = CategoryImport(
        ncm=cat.sh6,
        ncm_label=f"SH6 {cat.sh6}",
        status=fetched.status if fetched else "unavailable",
    )
    if fetched is None or not fetched.ok:
        return base
    if source_label and "source" in CategoryImport.model_fields:
        base.source = source_label

    months = (fetched.payload or {}).get("months") or []
    if not months:
        return base

    # A data de referência é o último mês com dado (o Comtrade tem ~2 meses
    # de defasagem), nunca a data da coleta.
    last = months[-1]
    base.usd_per_kg = round(last["usd_per_kg"], 2)
    base.period = last["period"]
    base.status = fetched.status

    # Meses podem faltar (peso zero sai da série): a comparação é com o mesmo
    # AAAA-MM do ano anterior, achado pela string. Sem ele, fica vazio.
    by_period = {m["period"]: m for m in months}
    prev = by_period.get(_year_before(last["period"]) or "")
    if prev and prev.get("usd_per_kg"):
        base.usd_per_kg_change_12m_pct = round(
            (last["usd_per_kg"] / prev["usd_per_kg"] - 1.0) * 100.0, 2
        )
    # Soma de 12 meses só com os 12 meses presentes; soma parcial pareceria
    # queda de importação.
    try:
        window = _last_12_months(last["period"])
    except ValueError:
        window = set()
    if window and window <= by_period.keys():
        base.fob_usd_12m = round(sum(by_period[p]["fob_usd"] for p in window), 2)
    return base


def _category_scores(cat: Category, by_key: dict[str, Driver]) -> dict[str, float]:
    """Nota de cada vetor para a categoria.

    `alocacao_chips` é pesado pela exposição da categoria às frentes
    (`supply_fronts.front_score`, §T24c): RAM sente a memória, CPU a lógica.
    Sem nenhum sinal com nota, fica a nota do vetor (neutra, com coverage 0).
    """
    scores = {k: d.score for k, d in by_key.items()}
    chips = by_key.get("alocacao_chips")
    if FRONTS_ENABLED and chips is not None:
        exposed = front_score({s.key: s.score for s in chips.signals}, cat.key)
        if exposed is not None:
            scores["alocacao_chips"] = exposed
    return scores


def _contributions(cat: Category, by_key: dict[str, Driver]) -> list[DriverContribution]:
    scores = _category_scores(cat, by_key)
    out: list[DriverContribution] = []
    for dk, beta in cat.betas.items():
        if dk not in by_key:
            continue
        # Contribuição em pontos percentuais do projetado global.
        contrib = beta * (scores[dk] - 50.0) / 50.0 * cat.sensitivity_pct * HORIZON_FACTOR
        out.append(
            DriverContribution(
                driver_key=dk,
                driver_label=DRIVERS_BY_KEY[dk].label,
                beta=beta,
                contribution_pct=round(contrib, 2),
            )
        )
    out.sort(key=lambda c: abs(c.contribution_pct), reverse=True)
    return out


def _narrative(cat: Category, item: RankingItem, brazil: BrazilContext) -> str:
    parts: list[str] = []
    if item.top_drivers:
        top = item.top_drivers[0]
        direction = "empurra para cima" if top.contribution_pct >= 0 else "puxa para baixo"
        parts.append(
            f"{top.driver_label} {direction} o preço "
            f"({top.contribution_pct:+.1f} p.p. do projetado)."
        )
    if brazil.usd_brl_change_30d_pct is not None:
        parts.append(
            f"O dólar variou {brazil.usd_brl_change_30d_pct:+.1f}% em 30 dias, "
            f"com repasse assumido de {brazil.fx_passthrough:.0%}."
        )
    obs = item.observed_br
    if obs and obs.var_12m_pct is not None:
        parts.append(
            f"Medido pelo IPCA, '{obs.subitem_label}' acumula "
            f"{obs.var_12m_pct:+.2f}% em 12 meses até {obs.period}."
        )
    if cat.note:
        parts.append(cat.note)
    return " ".join(parts)


def build_ranking(
    drivers: list[Driver],
    brazil: BrazilContext,
    collected: dict[str, Fetched],
) -> list[RankingItem]:
    by_key = {d.key: d for d in drivers}
    # O efeito do dólar é o mesmo para todo produto: vem pronto da camada
    # Brasil, onde também é exibido uma única vez como síntese.
    fx_effect = brazil.fx_price_effect_30d_pct or 0.0

    items: list[RankingItem] = []
    for cat in CATEGORIES:
        scores = _category_scores(cat, by_key)
        # Pressão global: exclui o vetor Brasil e renormaliza os betas restantes.
        global_betas = {k: v for k, v in cat.betas.items() if k != "cambio_br"}
        total_gb = sum(global_betas.values()) or 1.0
        dev_global = sum(
            (beta / total_gb) * (scores[dk] - 50.0) / 50.0
            for dk, beta in global_betas.items()
            if dk in by_key
        )
        proj_global = dev_global * cat.sensitivity_pct * HORIZON_FACTOR

        # Composição correta: preço em US$ x câmbio.
        proj_brazil = (
            (1.0 + proj_global / 100.0) * (1.0 + fx_effect / 100.0) - 1.0
        ) * 100.0

        # Pressão 0-100 usando o vetor completo, inclusive câmbio.
        pressure = 50.0 + 50.0 * sum(
            beta * (scores[dk] - 50.0) / 50.0
            for dk, beta in cat.betas.items()
            if dk in by_key
        )

        brl_impact = None
        if brazil.usd_brl:
            brl_impact = round(100.0 * brazil.usd_brl * cat.tax_multiplier, 2)

        item = RankingItem(
            key=cat.key,
            label=cat.label,
            icon=cat.icon,
            rank=0,
            pressure_score=round(max(0.0, min(100.0, pressure)), 1),
            projected_global_30d_pct=round(proj_global, 2),
            projected_brazil_30d_pct=round(proj_brazil, 2),
            observed_br=_observed_br(cat, collected),
            imports=_imports(cat, collected),
            tax_multiplier=cat.tax_multiplier,
            tax_note=cat.tax_note,
            brl_impact_per_100usd=brl_impact,
            top_drivers=_contributions(cat, by_key),
        )
        item.narrative = _narrative(cat, item, brazil)
        items.append(item)

    items.sort(key=lambda i: i.projected_brazil_30d_pct, reverse=True)
    for idx, item in enumerate(items, start=1):
        item.rank = idx
    return items
