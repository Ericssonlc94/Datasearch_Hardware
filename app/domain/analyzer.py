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
    peak_score,
    pressure_score,
    ratio_series,
    to_points,
    trailing_mean,
    weighted_mean,
    window_peak,
    window_sum,
)
from .drivers import DRIVERS, DriverSpec, SignalSpec
from .supply_fronts import FRONTS_ENABLED, read_front

# Repasse cambial assumido para hardware importado: 85% da variação do dólar
# chega ao preço de prateleira dentro de um trimestre. Hardware é quase todo
# importado e o estoque em reais gira rápido, então o repasse é alto.
FX_PASSTHROUGH = 0.85
# O trimestre acima vira prazo explícito: no horizonte exibido (30 dias) chega
# só a fração proporcional do repasse. Até 04/11/2026 os 85% entravam inteiros
# em 30 dias, e a projeção Brasil ficava em ~9% num mês em que o IPCA de
# computador, celular e console nunca passou de ~3% em 24 meses (T07).
FX_PASSTHROUGH_DAYS = 90
FX_HORIZON_DAYS = 30


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
    """Monta um sinal; a reserva só entra se a fonte primária não tiver série.

    `fallback_source` aceita uma cadeia separada por vírgula. A primeira fonte
    com série vence e as demais são ignoradas — o mesmo choque nunca é somado
    duas vezes, que era o defeito de Brent/cobre/PTAX antes desta fase.
    """
    if spec.mode == "front":
        return _front_signal(spec, collected)

    candidates = [spec.source]
    if spec.fallback_source:
        candidates += [s.strip() for s in spec.fallback_source.split(",") if s.strip()]

    fetched: Fetched | None = None
    used = spec.source
    points: list[Point] = []
    for candidate in candidates:
        candidate_fetched = collected.get(candidate)
        candidate_points = _series_from(candidate_fetched, spec.path)
        if candidate_points:
            fetched, used, points = candidate_fetched, candidate, candidate_points
            break
        if fetched is None:
            fetched = candidate_fetched

    status: SourceStatus = fetched.status if fetched else "unavailable"

    if spec.relative_to and points:
        # Sem a série de referência não existe razão: o sinal fica vazio em
        # vez de cair para a série absoluta, que mediria outra coisa.
        points = ratio_series(points, _series_from(collected.get(spec.relative_to), "points"))

    latest = points[-1][1] if points else None
    if spec.mode == "peak":
        change = None
        latest = window_peak(points, spec.window_days)
        score = peak_score(latest, spec.threshold, spec.scale)
    elif spec.mode == "sum":
        # Contagem líquida de eventos na janela: positivo pressiona, negativo
        # alivia, zero (nenhum evento) é neutro.
        change = None
        latest = window_sum(points, spec.window_days)
        score = pressure_score(latest, spec.scale)
    else:
        basis = trailing_mean(points, spec.smooth_days) if spec.smooth_days else points
        change = pct_change(basis, spec.window_days) if basis else None
        if change is not None and spec.invert:
            change = -change
        score = pressure_score(change, spec.scale)

    return Signal(
        key=spec.key,
        label=spec.label,
        unit=spec.unit,
        latest=latest,
        change_pct=round(change, 2) if change is not None else None,
        window=f"{spec.window_days}d",
        score=round(score, 1) if score is not None else None,
        weight=spec.weight,
        source_key=spec.source,
        fallback_source=spec.fallback_source,
        used_source=used,
        status=status,
        series=to_points(points, limit=180),
    )


def _front_signal(spec: SignalSpec, collected: dict[str, Fetched]) -> Signal:
    """Sinal de frente de oferta (§T24c): nota pelo z, não pela variação %."""
    fetched = collected.get(spec.source)
    reading = read_front(spec.key, collected) if FRONTS_ENABLED else None
    score = reading.pressure if reading else None
    return Signal(
        key=spec.key,
        label=spec.label,
        unit=spec.unit,
        latest=round(reading.value, 2) if reading and reading.value is not None else None,
        change_pct=None,
        window=(reading.period or "") if reading else "",
        score=round(score, 1) if score is not None else None,
        weight=spec.weight,
        source_key=spec.source,
        fallback_source=None,
        used_source=spec.source,
        status=fetched.status if fetched else "unavailable",
        series=to_points(reading.series, limit=180) if reading else [],
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


def fx_price_effect(
    fx_change_pct: float | None, horizon_days: int = FX_HORIZON_DAYS
) -> float | None:
    """Quanto a variação do dólar acrescenta ao preço do importado em `horizon_days`, em %.

    O repasse total (85%) leva um trimestre; dentro do horizonte entra a
    fração linear `horizon_days / 90`, a mesma regra que converte a
    sensibilidade de 90 para 30 dias no ranking.
    """
    if fx_change_pct is None:
        return None
    share = min(1.0, horizon_days / FX_PASSTHROUGH_DAYS)
    return fx_change_pct * FX_PASSTHROUGH * share


def build_brazil(collected: dict[str, Fetched]) -> BrazilContext:
    # Cadeia explicitamente ordenada: PTAX oficial → spot → H.10 do Fed.
    ptax: list[Point] = []
    for key in ("bcb.ptax_usd", "market.usd_brl", "fred.usd_brl_fed"):
        ptax = _series_from(collected.get(key), "points")
        if ptax:
            break
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
        # Síntese da alta do dólar: a mesma conta que o ranking usa por produto.
        fx_price_effect_30d_pct=_r(fx_price_effect(pct_change(ptax, 30))),
    )
