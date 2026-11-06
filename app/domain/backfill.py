"""Reconstrução diária do IPH com as séries que o painel já coleta.

O histórico gravado nasce no primeiro ciclo do app; sem isto, a aba Evolução
só teria horas de IPH. Mas quase todo sinal do índice já chega com meses de
série (mercado, câmbio, FRED, terremotos do USGS). Para cada dia passado, cortamos
as séries naquele dia e rodamos exatamente o mesmo cálculo do ciclo ao vivo.

Isto é recálculo, não interpolação: cada ponto usa só observações com data até
o dia reconstruído. Limite declarado: séries mensais e anuais entram pela data
de referência, não pela data em que foram publicadas, e revisões posteriores
já estão embutidas. Por isso o ponto sai marcado como `reconstructed`.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date

from ..cache import Fetched
from .analyzer import (
    FX_PASSTHROUGH,
    FX_PASSTHROUGH_DAYS,
    build_brazil,
    build_drivers,
    build_summary,
)
from .catalog import CATEGORIES
from .drivers import DRIVERS
from .ranking import HORIZON_DAYS, build_ranking
from .supply_fronts import EXPOSURE, FRONT_SIGNALS, FRONT_SOURCES, FRONTS_ENABLED, cut_front_as_of

FRONT_KEYS = {source for source, _ in FRONT_SOURCES.values()}

# Rodar o mesmo cálculo com o mesmo insumo precisa dar a mesma série; mudar o
# modelo (pesos, janelas, sinais, betas, repasse cambial) invalida o que foi
# reconstruído antes.
MODEL_VERSION = hashlib.sha256(
    repr((
        DRIVERS, CATEGORIES, HORIZON_DAYS, FX_PASSTHROUGH, FX_PASSTHROUGH_DAYS,
        FRONTS_ENABLED, sorted(FRONT_SIGNALS.items()), sorted(EXPOSURE.items()),
    )).encode("utf-8")
).hexdigest()[:12]


def _known_on(t: str, day: date) -> bool:
    """True se a observação com data `t` já existia no fim de `day`.

    Ano isolado ("2025") é dado anual: só conta depois que o ano fechou.
    Demais formatos comparam pela data de referência (YYYY-MM[-DD]).
    """
    raw = str(t).strip()
    if len(raw) == 4 and raw.isdigit():
        return int(raw) < day.year
    stamp = raw[:10]
    if len(stamp) == 7:  # YYYY-MM
        stamp += "-01"
    return stamp <= day.isoformat()


def _is_series(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], str)
            for item in value
        )
    )


def collected_as_of(collected: dict[str, Fetched], day: date) -> dict[str, Fetched]:
    """Cópia das coletas com toda série cortada no fim de `day`."""
    out: dict[str, Fetched] = {}
    for key, fetched in collected.items():
        payload = fetched.payload
        if not fetched.ok or not isinstance(payload, dict):
            out[key] = fetched
            continue
        if key in FRONT_KEYS:
            out[key] = cut_front_as_of(fetched, day)
            continue
        cut = {
            name: [p for p in value if _known_on(p[0], day)] if _is_series(value) else value
            for name, value in payload.items()
        }
        out[key] = replace(fetched, payload=cut)
    return out


def reconstruct_day(
    collected: dict[str, Fetched], day: date
) -> list[tuple[str, float]]:
    """(chave, valor) do índice, dos fatores e dos produtos naquele dia."""
    snap_in = collected_as_of(collected, day)
    drivers = build_drivers(snap_in)
    brazil = build_brazil(snap_in)
    summary = build_summary(drivers, brazil)
    ranking = build_ranking(drivers, brazil, snap_in)

    rows: list[tuple[str, float]] = [
        ("iph", summary.iph),
        ("iph_br", summary.iph_brazil),
        ("coverage", summary.coverage * 100.0),
    ]
    rows.extend((f"driver.{d.key}", d.score) for d in drivers)
    for item in ranking:
        rows.extend(
            [
                (f"cat.{item.key}.pressure", item.pressure_score),
                (f"cat.{item.key}.proj30_global", item.projected_global_30d_pct),
                (f"cat.{item.key}.proj30_br", item.projected_brazil_30d_pct),
            ]
        )
    return [(key, float(value)) for key, value in rows]


def reconstruct(
    collected: dict[str, Fetched], days: list[date]
) -> dict[date, list[tuple[str, float]]]:
    return {day: reconstruct_day(collected, day) for day in days}
