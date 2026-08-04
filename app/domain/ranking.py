"""Ranking de variação por tipo de hardware, com o corte Brasil.

Distinção que o painel mantém explícita:

* `projected_global_90d_pct` — pressão modelada sobre o preço em dólar,
  a partir dos drivers, sem a camada local.
* `projected_brazil_90d_pct` — a mesma pressão composta com a variação
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


def _imports(cat: Category, collected: dict[str, Fetched]) -> CategoryImport:
    fetched = collected.get(f"comexstat.{cat.key}")
    base = CategoryImport(
        ncm=cat.sh6,
        ncm_label=f"SH6 {cat.sh6}",
        status=fetched.status if fetched else "unavailable",
    )
    if fetched is None or not fetched.ok:
        return base

    months = (fetched.payload or {}).get("months") or []
    if not months:
        return base

    last = months[-1]
    base.usd_per_kg = round(last["usd_per_kg"], 2)
    base.period = last["period"]
    base.status = fetched.status

    if len(months) > 12:
        prev = months[-13]["usd_per_kg"]
        if prev:
            base.usd_per_kg_change_12m_pct = round(
                (last["usd_per_kg"] / prev - 1.0) * 100.0, 2
            )
    base.fob_usd_12m = round(sum(m["fob_usd"] for m in months[-12:]), 2)
    return base


def _contributions(cat: Category, by_key: dict[str, Driver]) -> list[DriverContribution]:
    out: list[DriverContribution] = []
    for dk, beta in cat.betas.items():
        drv = by_key.get(dk)
        if drv is None:
            continue
        # Contribuição em pontos percentuais do projetado global.
        contrib = beta * (drv.score - 50.0) / 50.0 * cat.sensitivity_pct
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
    if brazil.usd_brl_change_90d_pct is not None:
        parts.append(
            f"O dólar variou {brazil.usd_brl_change_90d_pct:+.1f}% em 90 dias, "
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
    fx_90 = brazil.usd_brl_change_90d_pct or 0.0
    fx_effect = fx_90 * brazil.fx_passthrough

    items: list[RankingItem] = []
    for cat in CATEGORIES:
        # Pressão global: exclui o vetor Brasil e renormaliza os betas restantes.
        global_betas = {k: v for k, v in cat.betas.items() if k != "cambio_br"}
        total_gb = sum(global_betas.values()) or 1.0
        dev_global = sum(
            (beta / total_gb) * (by_key[dk].score - 50.0) / 50.0
            for dk, beta in global_betas.items()
            if dk in by_key
        )
        proj_global = dev_global * cat.sensitivity_pct

        # Composição correta: preço em US$ x câmbio.
        proj_brazil = (
            (1.0 + proj_global / 100.0) * (1.0 + fx_effect / 100.0) - 1.0
        ) * 100.0

        # Pressão 0-100 usando o vetor completo, inclusive câmbio.
        pressure = 50.0 + 50.0 * sum(
            beta * (by_key[dk].score - 50.0) / 50.0
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
            projected_global_90d_pct=round(proj_global, 2),
            projected_brazil_90d_pct=round(proj_brazil, 2),
            observed_br=_observed_br(cat, collected),
            imports=_imports(cat, collected),
            tax_multiplier=cat.tax_multiplier,
            tax_note=cat.tax_note,
            brl_impact_per_100usd=brl_impact,
            top_drivers=_contributions(cat, by_key),
        )
        item.narrative = _narrative(cat, item, brazil)
        items.append(item)

    items.sort(key=lambda i: i.projected_brazil_90d_pct, reverse=True)
    for idx, item in enumerate(items, start=1):
        item.rank = idx
    return items
