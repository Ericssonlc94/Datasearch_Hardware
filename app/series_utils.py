"""Utilidades de série temporal usadas por providers e analyzer."""

from __future__ import annotations

import math
from datetime import date, datetime

from .schemas import SeriesPoint

Point = tuple[str, float]


def to_points(pairs: list[Point], limit: int | None = None) -> list[SeriesPoint]:
    pts = [SeriesPoint(t=t, v=v) for t, v in pairs]
    return pts[-limit:] if limit else pts


def latest(pairs: list[Point]) -> float | None:
    return pairs[-1][1] if pairs else None


def _parse_t(t: str) -> date | None:
    """Aceita YYYY-MM-DD, YYYY-MM e YYYYMM."""
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y%m"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def value_n_days_ago(pairs: list[Point], days: int) -> float | None:
    """Valor mais próximo de `days` atrás, ancorado no último ponto da série."""
    if not pairs:
        return None
    end = _parse_t(pairs[-1][0])
    if end is None:
        # Sem data parseável, cai para posição na lista.
        idx = max(0, len(pairs) - 1 - days)
        return pairs[idx][1]
    target = end.toordinal() - days
    best: tuple[int, float] | None = None
    for t, v in pairs:
        d = _parse_t(t)
        if d is None:
            continue
        dist = abs(d.toordinal() - target)
        if best is None or dist < best[0]:
            best = (dist, v)
    return best[1] if best else None


def trailing_mean(pairs: list[Point], days: int) -> list[Point]:
    """Média dos últimos `days` dias corridos em cada ponto (inclusive).

    Para contagem diária de notícias: um dia isolado com pauta forte ou fraca
    não deve mover o sinal sozinho. Pontos sem data parseável passam intactos.
    """
    if days <= 1 or not pairs:
        return list(pairs)
    dated = [(_parse_t(t), t, v) for t, v in pairs]
    if any(d is None for d, _, _ in dated):
        return list(pairs)
    out: list[Point] = []
    start = 0
    total = 0.0
    for i, (d, t, v) in enumerate(dated):
        total += v
        while dated[start][0].toordinal() <= d.toordinal() - days:
            total -= dated[start][2]
            start += 1
        out.append((t, total / (i - start + 1)))
    return out


def ratio_series(num: list[Point], den: list[Point]) -> list[Point]:
    """Razão ponto a ponto nas datas presentes nas duas séries."""
    by_date = {t[:10]: v for t, v in den if v}
    return [(t, v / by_date[t[:10]]) for t, v in num if t[:10] in by_date]


def window_peak(pairs: list[Point], days: int) -> float | None:
    """Maior valor nos últimos `days` dias, ancorado no último ponto."""
    if not pairs:
        return None
    end = _parse_t(pairs[-1][0][:10])
    if end is None:
        return max(v for _, v in pairs[-days:])
    floor = end.toordinal() - days
    values = [
        v for t, v in pairs
        if (d := _parse_t(t[:10])) is not None and d.toordinal() > floor
    ]
    return max(values) if values else None


def window_sum(pairs: list[Point], days: int) -> float | None:
    """Soma dos valores nos últimos `days` dias, ancorada no último ponto."""
    if not pairs:
        return None
    end = _parse_t(pairs[-1][0][:10])
    if end is None:
        return sum(v for _, v in pairs[-days:])
    floor = end.toordinal() - days
    return sum(
        v for t, v in pairs
        if (d := _parse_t(t[:10])) is not None and d.toordinal() > floor
    )


def peak_score(peak: float | None, threshold: float, scale: float) -> float | None:
    """Pressão 50-100 pelo quanto o pico passou do limiar (nunca alívio)."""
    if peak is None or not math.isfinite(peak):
        return None
    if scale <= 0:
        return 50.0
    return 50.0 + 50.0 * math.tanh(max(0.0, peak - threshold) / scale)


def pct_change(pairs: list[Point], days: int) -> float | None:
    """Variação percentual na janela de `days` dias corridos."""
    if len(pairs) < 2:
        return None
    now = pairs[-1][1]
    then = value_n_days_ago(pairs, days)
    if then is None or then == 0 or now is None:
        return None
    return (now / then - 1.0) * 100.0


def pct_change_n(pairs: list[Point], n: int) -> float | None:
    """Variação percentual sobre os últimos `n` pontos (para séries mensais)."""
    if len(pairs) <= n:
        return None
    now, then = pairs[-1][1], pairs[-1 - n][1]
    if then == 0:
        return None
    return (now / then - 1.0) * 100.0


def compound(pairs: list[Point], n: int) -> float | None:
    """Acumula `n` variações percentuais mensais (ex.: IPCA 12 meses)."""
    if len(pairs) < n:
        return None
    acc = 1.0
    for _, v in pairs[-n:]:
        acc *= 1.0 + v / 100.0
    return (acc - 1.0) * 100.0


def pressure_score(change_pct: float | None, scale: float) -> float | None:
    """Converte variação percentual em pressão 0-100 (50 = neutro).

    Usa tanh para saturar suavemente: uma alta de `scale`% mapeia para ~88,
    o que evita que um único choque domine o índice inteiro.
    """
    if change_pct is None or not math.isfinite(change_pct):
        return None
    if scale <= 0:
        return 50.0
    return 50.0 + 50.0 * math.tanh(change_pct / scale)


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    """`pairs` = [(valor, peso)]. Renormaliza sobre os pesos presentes."""
    usable = [(v, w) for v, w in pairs if v is not None and w > 0]
    if not usable:
        return None
    total_w = sum(w for _, w in usable)
    if total_w == 0:
        return None
    return sum(v * w for v, w in usable) / total_w
