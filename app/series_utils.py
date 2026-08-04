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
