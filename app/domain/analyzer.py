"""Cálculo do Índice de Pressão de Hardware (IPH) e do contexto Brasil.

Método, em uma frase: cada sinal vira uma pressão 0-100 via tanh da sua
variação percentual; sinais viram drivers por média ponderada; drivers viram
o IPH por média ponderada. Onde falta dado, o peso é redistribuído entre os
sinais presentes e a `coverage` cai — nunca preenchemos buraco com chute.
"""

from __future__ import annotations

from ..cache import Fetched
from ..schemas import (
    BrazilContext,
    Driver,
    IndexSummary,
    Signal,
    SourceStatus,
)
from ..series_utils import (
    Point,
    clamp,
    compound,
    pct_change,
    pressure_score,
    to_points,
    weighted_mean,
)
from .drivers import DRIVERS, DriverSpec, SignalSpec

# Repasse cambial assumido para hardware importado: 85% da variação do dólar
# chega ao preço de prateleira dentro de um trimestre. Hardware é quase todo
# importado e o estoque em reais gira rápido, então o repasse é alto.
FX_PASSTHROUGH = 0.85


def _series_from(fetched: Fetched | None, path: str) -> list[Point]:
    if fetched is None or not fetched.ok or not isinstance(fetched.payload, dict):
        return []
    raw = fetched.payload.get(path) or []
    out: list[Point] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((str(item[0]), float(item[1])))
    return out


def build_signal(spec: SignalSpec, collected: dict[str, Fetched]) -> Signal:
    fetched = collected.get(spec.source)
    status: SourceStatus = fetched.status if fetched else "unavailable"
    points = _series_from(fetched, spec.path)

    change = pct_change(points, spec.window_days) if points else None
    if change is not None and spec.invert:
        change = -change
    score = pressure_score(change, spec.scale)

    return Signal(
        key=spec.key,
        label=spec.label,
        unit=spec.unit,
        latest=points[-1][1] if points else None,
        change_pct=round(change, 2) if change is not None else None,
        window=f"{spec.window_days}d",
        score=round(score, 1) if score is not None else None,
        weight=spec.weight,
        source_key=spec.source,
        status=status,
        series=to_points(points, limit=180),
    )


def build_driver(spec: DriverSpec, collected: dict[str, Fetched]) -> Driver:
    signals = [build_signal(s, collected) for s in spec.signals]
    scored = [(s.score, s.weight) for s in signals if s.score is not None]
    score = weighted_mean(scored)
    coverage = (
        sum(w for _, w in scored) / sum(s.weight for s in spec.signals)
        if spec.signals
        else 0.0
    )

    # Sem nenhum sinal, o driver fica neutro e a coverage denuncia isso.
    final = clamp(score) if score is not None else 50.0
    trend = "alta" if final > 55 else "baixa" if final < 45 else "estavel"

    return Driver(
        key=spec.key,
        label=spec.label,
        thesis=spec.thesis,
        score=round(final, 1),
        weight=spec.weight,
        coverage=round(coverage, 3),
        signals=signals,
        trend=trend,
    )


def build_drivers(collected: dict[str, Fetched]) -> list[Driver]:
    return [build_driver(spec, collected) for spec in DRIVERS]


def _iph_label(iph: float) -> str:
    if iph >= 72:
        return "Pressão severa"
    if iph >= 60:
        return "Pressão alta"
    if iph >= 53:
        return "Pressão moderada"
    if iph >= 47:
        return "Neutro"
    if iph >= 40:
        return "Alívio moderado"
    return "Alívio"


def _interpretation(iph: float, iph_br: float, top: Driver | None) -> str:
    gap = iph_br - iph
    base = (
        f"O IPH global está em {iph:.0f}/100 ({_iph_label(iph).lower()}). "
        f"Ajustado pela camada Brasil — câmbio, juro e carga de importação — "
        f"vai a {iph_br:.0f}/100."
    )
    if top is not None:
        base += f" O vetor dominante hoje é '{top.label}' ({top.score:.0f}/100)."
    if gap >= 6:
        base += (
            " A diferença mostra que o consumidor brasileiro absorve um choque"
            " maior do que o mercado global médio."
        )
    elif gap <= -6:
        base += (
            " Neste momento a camada local amortece parte da pressão externa."
        )
    return base


def build_summary(drivers: list[Driver], brazil: BrazilContext) -> IndexSummary:
    iph = weighted_mean([(d.score, d.weight) for d in drivers]) or 50.0

    # IPH-Brasil: reponderamos dando peso extra ao vetor local, que é o canal
    # de transmissão mais rápido para o preço de prateleira aqui.
    br_weights = {d.key: d.weight for d in drivers}
    br_weights["cambio_br"] = br_weights.get("cambio_br", 0.20) * 1.6
    iph_br = (
        weighted_mean([(d.score, br_weights[d.key]) for d in drivers]) or iph
    )

    total_w = sum(d.weight for d in drivers) or 1.0
    coverage = sum(d.coverage * d.weight for d in drivers) / total_w
    top = max(drivers, key=lambda d: d.score * d.weight, default=None)

    return IndexSummary(
        iph=round(clamp(iph), 1),
        iph_label=_iph_label(iph),
        iph_brazil=round(clamp(iph_br), 1),
        coverage=round(coverage, 3),
        interpretation=_interpretation(iph, iph_br, top),
    )


def build_brazil(collected: dict[str, Fetched]) -> BrazilContext:
    ptax = _series_from(collected.get("bcb.ptax_usd"), "points")
    if not ptax:
        ptax = _series_from(collected.get("market.usd_brl"), "points")
    ipca = _series_from(collected.get("bcb.ipca"), "points")
    igpm = _series_from(collected.get("bcb.igpm"), "points")
    selic = _series_from(collected.get("bcb.selic_meta"), "points")

    def _r(v: float | None, nd: int = 2) -> float | None:
        return round(v, nd) if v is not None else None

    return BrazilContext(
        usd_brl=_r(ptax[-1][1], 4) if ptax else None,
        usd_brl_change_30d_pct=_r(pct_change(ptax, 30)),
        usd_brl_change_90d_pct=_r(pct_change(ptax, 90)),
        usd_brl_change_12m_pct=_r(pct_change(ptax, 365)),
        selic=_r(selic[-1][1]) if selic else None,
        ipca_12m=_r(compound(ipca, 12)),
        igpm_12m=_r(compound(igpm, 12)),
        ipca_series=to_points(ipca, limit=24),
        usd_brl_series=to_points(ptax, limit=180),
        fx_passthrough=FX_PASSTHROUGH,
    )
