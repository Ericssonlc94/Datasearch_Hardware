"""Oferta por frente (memória, lógica, demanda) e exposição por categoria.

Desenho aprovado em `docs/agentes/modelo.md` §T24c, ligado na T30
(05/11/2026) num passo só: `drivers`/`analyzer` (sinais `mode="front"`),
`ranking` (nota do vetor por exposição), `supply` (fila só de demanda) e
`series.MODEL_VERSIONS`. `FRONTS_ENABLED = False` volta à conta antiga.

Três ideias:

* **Dias de estoque (DIO)** normalizados pela duração real do trimestre:
  `estoque ÷ (CPV ÷ dias)`. O Q4 FY2026 da Micron tem 98 dias e inflaria o
  número em ~7% com um divisor fixo.
* **Todo sinal em z-score contra a própria história**, convertido em pressão
  por `50 + 50·tanh(±z/1,5)`. Dias, % a/a e US$ não se misturam em unidade
  bruta (lição da T06).
* **A categoria pesa os sinais pela exposição** à frente de cada um:
  `nota_c = Σ w·e·nota / Σ w·e`, só com os sinais disponíveis. Exposição 1
  em tudo devolve a nota global do vetor, que é a que o IPH usa.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import quantiles

from ..cache import Fetched
from ..series_utils import Point

FRONTS_ENABLED = True

FRONTS = ("memoria", "logica", "demanda")
# z que leva a pressão a ~12/88, como a escala dos outros sinais.
Z_SCALE = 1.5
# "O normal": P25–P75 dos últimos 5 anos.
NORMAL_QUARTERS = 20
NORMAL_MONTHS = 60
# Validade depois do fim do período de referência.
MAX_AGE_DAYS = {"monthly": 75, "quarterly": 150}


# --- pesos e exposição -----------------------------------------------------------

# Pesos dentro do vetor `alocacao_chips` (§T24c; somam 1,00). `None` = geral,
# vale para todas as categorias com exposição 1.
FRONT_SIGNALS: dict[str, tuple[str | None, float]] = {
    "capex_hyperscaler": ("demanda", 0.20),
    "tsmc_revenue": ("demanda", 0.13),
    "dio_memory": ("memoria", 0.15),
    "comtrade_memory": ("memoria", 0.06),
    "micron": ("memoria", 0.08),
    "dio_logic": ("logica", 0.12),
    "comtrade_processors": ("logica", 0.05),
    "nvda": ("logica", 0.05),
    "tsmc": ("logica", 0.03),
    "ppi_semis": (None, 0.10),
    "soxx": (None, 0.03),
}

# Exposição 0–1 por frente (§T24 com o ajuste da T24c: TSMC em demanda sobe
# celular, console e notebook nessa frente). Heurística, como os betas.
EXPOSURE: dict[str, dict[str, float]] = {
    "ram": {"memoria": 1.0, "logica": 0.2, "demanda": 1.0},
    "storage": {"memoria": 1.0, "logica": 0.2, "demanda": 0.6},
    "gpu": {"memoria": 0.6, "logica": 1.0, "demanda": 1.0},
    "cpu": {"memoria": 0.2, "logica": 1.0, "demanda": 0.6},
    "smartphone": {"memoria": 0.7, "logica": 0.8, "demanda": 0.5},
    "notebook": {"memoria": 0.7, "logica": 0.8, "demanda": 0.6},
    "console": {"memoria": 0.6, "logica": 0.9, "demanda": 0.6},
    "motherboard": {"memoria": 0.2, "logica": 0.6, "demanda": 0.3},
    "monitor": {"memoria": 0.1, "logica": 0.4, "demanda": 0.2},
    "psu": {"memoria": 0.0, "logica": 0.4, "demanda": 0.2},
}


def validate_fronts() -> list[str]:
    """Pesos somam 1, frentes conhecidas, exposição para cada categoria."""
    from .catalog import CATEGORIES_BY_KEY

    problems: list[str] = []
    total = sum(w for _, w in FRONT_SIGNALS.values())
    if abs(total - 1.0) > 1e-6:
        problems.append(f"pesos das frentes somam {total:.4f}, esperado 1.0")
    for key, (front, _) in FRONT_SIGNALS.items():
        if front is not None and front not in FRONTS:
            problems.append(f"{key}: frente desconhecida '{front}'")
    for key in CATEGORIES_BY_KEY:
        exposure = EXPOSURE.get(key)
        if exposure is None:
            problems.append(f"{key}: sem exposição por frente")
            continue
        for front in FRONTS:
            value = exposure.get(front)
            if value is None or not 0.0 <= value <= 1.0:
                problems.append(f"{key}: exposição '{front}' fora de 0–1")
    return problems


def front_score(
    signal_scores: dict[str, float | None], category: str | None = None
) -> float | None:
    """Nota 0–100 do vetor para a categoria (ou global, com `category=None`).

    Só entram sinais com nota; os pesos se renormalizam entre eles. Sem
    nenhum, `None` — nunca 50 inventado.
    """
    exposure = EXPOSURE.get(category, {}) if category else {}
    num = den = 0.0
    for key, (front, weight) in FRONT_SIGNALS.items():
        score = signal_scores.get(key)
        if score is None or not math.isfinite(score):
            continue
        e = 1.0 if front is None or category is None else exposure.get(front, 0.0)
        num += weight * e * score
        den += weight * e
    return num / den if den > 0 else None


# --- z-score, pressão e faixa normal ------------------------------------------


def z_against(history: list[float], value: float) -> float | None:
    """z de `value` contra `history` (que não inclui o próprio valor).

    Menos de 3 pontos ou desvio zero devolve `None` em vez de um extremo.
    """
    values = [v for v in history if math.isfinite(v)]
    if len(values) < 3 or not math.isfinite(value):
        return None
    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    if std <= 1e-9:
        return None
    return (value - mean) / std


def z_pressure(z: float | None, invert: bool = False) -> float | None:
    """`50 + 50·tanh(±z/1,5)`; `invert` para estoque (queda = pressão)."""
    if z is None:
        return None
    return 50.0 + 50.0 * math.tanh((-z if invert else z) / Z_SCALE)


def normal_range(values: list[float]) -> tuple[float, float] | None:
    """P25–P75 (método inclusivo) — "o normal é X a Y" no card."""
    finite = [v for v in values if math.isfinite(v)]
    if len(finite) < 4:
        return None
    q = quantiles(finite, n=4, method="inclusive")
    return q[0], q[2]


# --- dias de estoque (DIO) ---------------------------------------------------


@dataclass(frozen=True)
class Quarter:
    """Um trimestre de uma empresa, como a SEC devolve depois do Dados."""

    end: date
    days: int  # duração real do trimestre fiscal
    inventory: float
    cogs: float  # CPV do trimestre (não acumulado no ano)
    filed: date | None = None  # publicação, para reconstrução sem adiantar


def dio(q: Quarter) -> float | None:
    """Dias de estoque: estoque ÷ CPV diário do trimestre."""
    if q.days <= 0 or q.cogs <= 0 or q.inventory < 0:
        return None
    return q.inventory / (q.cogs / q.days)


def aggregate_dio(quarters: list[Quarter]) -> float | None:
    """DIO de um grupo: Σ estoque ÷ Σ CPV diário (o card da frente)."""
    valid = [q for q in quarters if dio(q) is not None]
    if not valid:
        return None
    return sum(q.inventory for q in valid) / sum(q.cogs / q.days for q in valid)


@dataclass
class DioReading:
    days: float | None
    normal: tuple[float, float] | None
    z: float | None
    pressure: float | None


def company_dio(quarters: list[Quarter]) -> DioReading:
    """Último DIO da empresa contra os 20 trimestres anteriores."""
    series = [(q.end, d) for q in sorted(quarters, key=lambda x: x.end)
              if (d := dio(q)) is not None]
    if not series:
        return DioReading(None, None, None, None)
    last = series[-1][1]
    history = [v for _, v in series[:-1]][-NORMAL_QUARTERS:]
    z = z_against(history, last)
    return DioReading(last, normal_range(history), z, z_pressure(z, invert=True))


def calendar_quarter(end: date) -> date:
    """Fim do trimestre civil mais próximo de `end` (31/03, 30/06, 30/09, 31/12)."""
    candidates = [
        date(year, month, calendar.monthrange(year, month)[1])
        for year in (end.year - 1, end.year)
        for month in (3, 6, 9, 12)
    ]
    return min(candidates, key=lambda c: abs((c - end).days))


def group_dio(by_company: dict[str, list[Quarter]]) -> DioReading:
    """Frente com várias empresas: z por empresa (média simples) e card agregado.

    O z é por empresa porque a AMD tem DIO estruturalmente maior: agregar
    antes de padronizar faria a mistura de empresas parecer movimento. O
    número e "o normal" do card são do agregado Σ estoque ÷ Σ CPV diário, nos
    trimestres que todas as empresas presentes têm.
    """
    readings = {name: company_dio(qs) for name, qs in by_company.items()}
    zs = [r.z for r in readings.values() if r.z is not None]
    z = sum(zs) / len(zs) if zs else None

    aggregated = dio_series(by_company)
    days = aggregated[-1][1] if aggregated else None
    history = [v for _, v in aggregated[:-1]][-NORMAL_QUARTERS:]
    return DioReading(days, normal_range(history), z, z_pressure(z, invert=True))


# --- TSMC: variação a/a da soma de 3 meses -----------------------------------


def _shift_month(period: str, months: int) -> str:
    year, month = (int(x) for x in period.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def rolling_3m_yoy(monthly: list[Point]) -> list[Point]:
    """Variação % a/a da soma de 3 meses, só com os 6 meses presentes.

    Os meses são achados pelo `AAAA-MM`, sem supor série contínua: mês
    faltando derruba o ponto em vez de comparar com o mês errado.
    """
    by_period = {p: v for p, v in monthly if math.isfinite(v)}
    out: list[Point] = []
    for period in sorted(by_period):
        try:
            now = [_shift_month(period, -i) for i in range(3)]
            before = [_shift_month(p, -12) for p in now]
        except ValueError:
            continue
        if not all(p in by_period for p in now + before):
            continue
        base = sum(by_period[p] for p in before)
        if base > 0:
            out.append((period, (sum(by_period[p] for p in now) / base - 1.0) * 100.0))
    return out


@dataclass
class GrowthReading:
    yoy_pct: float | None
    normal: tuple[float, float] | None
    z: float | None
    pressure: float | None
    period: str | None


def tsmc_growth(monthly: list[Point]) -> GrowthReading:
    """Receita da TSMC: último a/a de 3 meses contra os 60 meses anteriores."""
    yoy = rolling_3m_yoy(monthly)
    if not yoy:
        return GrowthReading(None, None, None, None, None)
    period, last = yoy[-1]
    history = [v for _, v in yoy[:-1]][-NORMAL_MONTHS:]
    z = z_against(history, last)
    return GrowthReading(last, normal_range(history), z, z_pressure(z), period)


# --- validade --------------------------------------------------------------------


def period_end(period: str) -> date | None:
    """Fim do período: `AAAA-MM` → último dia do mês; `AAAA-MM-DD` → o dia."""
    try:
        if len(period) == 7:
            year, month = (int(x) for x in period.split("-"))
            return date(year, month, calendar.monthrange(year, month)[1])
        return date.fromisoformat(period[:10])
    except ValueError:
        return None


def is_fresh(period: str | date, frequency: str, today: date) -> bool:
    """Se o dado ainda vale: mensal até 75 dias, trimestral até 150 dias."""
    end = period if isinstance(period, date) else period_end(period)
    if end is None:
        return False
    return today - end <= timedelta(days=MAX_AGE_DAYS[frequency])


def demand_queue(z_capex: float | None, z_revenue: float | None, a: float = 0.25) -> float | None:
    """Fila só de demanda (§T24c): o estoque da Micron vai para a frente memória."""
    components = [z for z in (z_capex, z_revenue) if z is not None]
    if not components:
        return None
    return 50.0 + 50.0 * math.tanh(a * sum(components))


# --- leitura das coletas e cards ------------------------------------------------

# Sinal da frente → (coleta, frequência). Os três entram no vetor
# `alocacao_chips` com `SignalSpec(mode="front")`.
FRONT_SOURCES: dict[str, tuple[str, str]] = {
    "dio_memory": ("sec.memory_quarters", "quarterly"),
    "dio_logic": ("sec.logic_quarters", "quarterly"),
    "tsmc_revenue": ("tsmc.monthly_revenue", "monthly"),
}


def _payload(fetched: Fetched | None) -> dict:
    if fetched is None or not fetched.ok or not isinstance(fetched.payload, dict):
        return {}
    return fetched.payload


def _date(raw: object) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw) if math.isfinite(raw) else None


def quarters_from(fetched: Fetched | None) -> dict[str, list[Quarter]]:
    """`{"by_company": {ticker: [{end, days, inventory, cogs, filed}]}}` → Quarter."""
    out: dict[str, list[Quarter]] = {}
    by_company = _payload(fetched).get("by_company")
    for ticker, rows in (by_company or {}).items() if isinstance(by_company, dict) else []:
        quarters = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            end, days = _date(row.get("end")), row.get("days")
            inventory, cogs = _number(row.get("inventory")), _number(row.get("cogs"))
            if end is None or not isinstance(days, int) or inventory is None or cogs is None:
                continue
            quarters.append(Quarter(end, days, inventory, cogs, _date(row.get("filed"))))
        if quarters:
            out[str(ticker)] = quarters
    return out


def monthly_from(fetched: Fetched | None) -> list[Point]:
    points = []
    for item in _payload(fetched).get("points") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            value = _number(item[1])
            if value is not None and isinstance(item[0], str):
                points.append((item[0], value))
    return points


def dio_series(by_company: dict[str, list[Quarter]]) -> list[Point]:
    """DIO agregado por trimestre civil (só os que têm todas as empresas).

    Os anos fiscais não fecham no mesmo dia (NVIDIA no fim de jul/out/jan/abr,
    AMD e Intel no fim do trimestre civil): o agrupamento é pelo trimestre
    civil mais próximo do fim, senão nenhum trimestre teria todas as empresas.
    """
    by_end: dict[date, list[Quarter]] = {}
    for qs in by_company.values():
        seen: set[date] = set()
        for q in sorted(qs, key=lambda x: x.end, reverse=True):
            key = calendar_quarter(q.end)
            if key not in seen:
                seen.add(key)
                by_end.setdefault(key, []).append(q)
    companies = sum(1 for qs in by_company.values() if qs)
    return [
        (end.isoformat(), value)
        for end, qs in sorted(by_end.items())
        if len(qs) == companies and (value := aggregate_dio(qs)) is not None
    ]


@dataclass
class FrontReading:
    """Leitura de um sinal de frente, pronta para o sinal e para o card."""

    value: float | None
    normal: tuple[float, float] | None
    z: float | None
    pressure: float | None  # já zerado para `None` quando vencido
    period: str | None
    fresh: bool
    series: list[Point]


def read_front(key: str, collected: dict[str, Fetched], today: date | None = None) -> FrontReading:
    """Lê `dio_memory`, `dio_logic` ou `tsmc_revenue` das coletas.

    Dado vencido (mensal > 75 dias, trimestral > 150) fica no card com o
    período, mas sai da nota: o vetor não usa número velho como se fosse atual.
    """
    source, frequency = FRONT_SOURCES[key]
    fetched = collected.get(source)
    # Na reconstrução, `backfill.collected_as_of` põe o dia em `fetched_at`.
    if today is None:
        stamp = fetched.fetched_at if fetched is not None else None
        today = stamp.date() if stamp else datetime.now(timezone.utc).date()
    if key == "tsmc_revenue":
        monthly = monthly_from(fetched)
        g = tsmc_growth(monthly)
        value, normal, z, pressure, period = g.yoy_pct, g.normal, g.z, g.pressure, g.period
        series = rolling_3m_yoy(monthly)
    else:
        by_company = quarters_from(fetched)
        r = group_dio(by_company)
        value, normal, z, pressure = r.days, r.normal, r.z, r.pressure
        series = dio_series(by_company)
        period = series[-1][0] if series else None
    fresh = period is not None and is_fresh(period, frequency, today)
    return FrontReading(value, normal, z, pressure if fresh else None, period, fresh, series)


FRONT_CARDS = (
    ("memoria", "Memória", "dio_memory", "dias",
     "Dias de estoque da Micron (estoque ÷ CPV diário do trimestre)"),
    ("logica", "Chips", "dio_logic", "dias",
     "Dias de estoque de NVIDIA, AMD e Intel (agregado)"),
    ("demanda", "Demanda", "tsmc_revenue", "% a/a",
     "Receita da TSMC, soma de 3 meses contra o mesmo período do ano anterior"),
)


def build_fronts(collected: dict[str, Fetched], today: date | None = None) -> list[dict]:
    """Os 3 cards de oferta (contrato combinado com Backend/Frontend na T32)."""
    cards = []
    for key, label, signal, unit, source in FRONT_CARDS:
        r = read_front(signal, collected, today)
        if r.value is None:
            status = "unavailable"
        else:
            status = "ok" if r.fresh else "stale"
        cards.append({
            "key": key,
            "label": label,
            "value": round(r.value, 1) if r.value is not None else None,
            "unit": unit,
            "normal": [round(r.normal[0], 1), round(r.normal[1], 1)] if r.normal else None,
            "period": r.period,
            "source": source,
            "status": status,
            "pressure": round(r.pressure, 1) if r.pressure is not None else None,
            "z": round(r.z, 2) if r.z is not None else None,
        })
    return cards


def cut_front_as_of(fetched: Fetched, day: date) -> Fetched:
    """Coleta de frente como era conhecida no fim de `day` (reconstrução).

    O corte é pela publicação, não pelo período: o mês da TSMC só existe a
    partir de `released` (dia 10 do mês seguinte, ou a data real da TWSE) e o
    trimestre da SEC a partir do `filed`. Sem data de publicação, fica de fora.
    """
    from dataclasses import replace

    payload = _payload(fetched)
    if not payload:
        return fetched
    stamp = datetime(day.year, day.month, day.day, 23, 59, tzinfo=timezone.utc)
    if fetched.key == "tsmc.monthly_revenue":
        released = payload.get("released") if isinstance(payload.get("released"), dict) else {}
        points = [
            p for p in payload.get("points") or []
            if isinstance(p, (list, tuple)) and p and (r := _date(released.get(p[0]))) and r <= day
        ]
        return replace(fetched, payload={**payload, "points": points}, fetched_at=stamp)
    by_company = payload.get("by_company") if isinstance(payload.get("by_company"), dict) else {}
    cut = {
        ticker: [q for q in rows if isinstance(q, dict) and (f := _date(q.get("filed"))) and f <= day]
        for ticker, rows in by_company.items() if isinstance(rows, list)
    }
    return replace(fetched, payload={**payload, "by_company": cut}, fetched_at=stamp)
