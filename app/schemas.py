"""Schemas de saída da API.

Regra de ouro deste projeto: todo número exposto carrega a sua origem.
`kind="observed"` é dado medido por uma fonte oficial; `kind="modeled"` é
resultado do nosso modelo heurístico e não deve ser lido como previsão validada.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceStatus = Literal["ok", "stale", "unavailable", "disabled"]
ValueKind = Literal["observed", "modeled"]


class SourceInfo(BaseModel):
    """Proveniência de uma coleta."""

    key: str
    label: str
    provider: str
    url: str
    status: SourceStatus
    as_of: datetime | None = None
    fetched_at: datetime | None = None
    error: str | None = None
    note: str | None = None


class SeriesPoint(BaseModel):
    t: str  # ISO date ou período (YYYY-MM)
    v: float


class Signal(BaseModel):
    """Um sinal bruto normalizado que alimenta um driver."""

    key: str
    label: str
    unit: str
    kind: ValueKind = "observed"
    latest: float | None = None
    change_pct: float | None = Field(
        default=None, description="Variação percentual na janela do sinal"
    )
    window: str = ""
    score: float | None = Field(
        default=None, description="Pressão normalizada 0-100 (50 = neutro)"
    )
    weight: float = 1.0
    source_key: str = ""
    status: SourceStatus = "ok"
    series: list[SeriesPoint] = Field(default_factory=list)


class Driver(BaseModel):
    """Um vetor geopolítico/econômico de pressão sobre preços."""

    key: str
    label: str
    thesis: str
    score: float = Field(description="0-100, 50 = neutro, >50 = pressão de alta")
    weight: float
    coverage: float = Field(description="Fração dos sinais que retornaram dados")
    signals: list[Signal] = Field(default_factory=list)
    trend: Literal["alta", "estavel", "baixa"] = "estavel"


class BrazilContext(BaseModel):
    """Camada Brasil: câmbio, juro, inflação e carga tributária de importação."""

    usd_brl: float | None = None
    usd_brl_change_30d_pct: float | None = None
    usd_brl_change_90d_pct: float | None = None
    usd_brl_change_12m_pct: float | None = None
    selic: float | None = None
    ipca_12m: float | None = None
    igpm_12m: float | None = None
    ipca_series: list[SeriesPoint] = Field(default_factory=list)
    usd_brl_series: list[SeriesPoint] = Field(default_factory=list)
    fx_passthrough: float = Field(
        description="Repasse assumido do câmbio ao preço final de hardware importado"
    )


class CategoryImport(BaseModel):
    """Dado real de importação (Comex Stat) para a categoria."""

    ncm: str
    ncm_label: str
    usd_per_kg: float | None = None
    usd_per_kg_change_12m_pct: float | None = None
    fob_usd_12m: float | None = None
    period: str | None = None
    status: SourceStatus = "unavailable"


class CategoryObservedBR(BaseModel):
    """Dado real de preço ao consumidor brasileiro (IPCA/IBGE)."""

    subitem_code: str
    subitem_label: str
    var_month_pct: float | None = None
    var_12m_pct: float | None = None
    period: str | None = None
    series: list[SeriesPoint] = Field(default_factory=list)
    status: SourceStatus = "unavailable"


class DriverContribution(BaseModel):
    driver_key: str
    driver_label: str
    beta: float
    contribution_pct: float


class RankingItem(BaseModel):
    """Uma categoria de hardware no ranking."""

    key: str
    label: str
    icon: str
    rank: int

    # --- modelado ---
    pressure_score: float = Field(description="0-100, exposição ponderada aos drivers")
    projected_global_90d_pct: float
    projected_brazil_90d_pct: float
    kind: ValueKind = "modeled"

    # --- observado ---
    observed_br: CategoryObservedBR | None = None
    imports: CategoryImport | None = None

    # --- explicação ---
    tax_multiplier: float
    tax_note: str
    brl_impact_per_100usd: float | None = Field(
        default=None,
        description=(
            "Quantos reais o consumidor paga a mais para cada US$100 de aumento "
            "no custo global: câmbio x carga de desembarque estimada."
        ),
    )
    top_drivers: list[DriverContribution] = Field(default_factory=list)
    narrative: str = ""


class IndexSummary(BaseModel):
    iph: float = Field(description="Indice de Pressao de Hardware, 0-100")
    iph_label: str
    iph_brazil: float = Field(description="IPH ajustado pela camada Brasil")
    coverage: float
    kind: ValueKind = "modeled"
    interpretation: str


class Snapshot(BaseModel):
    """Payload completo consumido pelo frontend."""

    generated_at: datetime
    next_refresh_at: datetime
    refresh_seconds: int
    summary: IndexSummary
    drivers: list[Driver]
    brazil: BrazilContext
    ranking: list[RankingItem]
    sources: list[SourceInfo]
    degraded: list[str] = Field(default_factory=list)
    headlines: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str
