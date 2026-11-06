"""USGS — terremotos perto dos polos de fabricação de chips.

API pública do Serviço Geológico dos EUA, sem chave:

    https://earthquake.usgs.gov/fdsnws/event/1/query
        ?format=geojson&starttime=...&minmagnitude=5.5
        &latitude=...&longitude=...&maxradiuskm=150

Por que importa para preço: fábrica de chip para a linha com tremor forte e
perde wafers em processo; foi o que suspendeu cotações de DRAM depois do
terremoto de Taiwan em abril de 2024. Medimos o evento físico, não a
cobertura jornalística dele.

A série é diária: maior magnitude registrada no dia num raio de 150 km de
qualquer polo. Dia sem evento ≥ 5,5 vale 0 — é observação real ("nenhum
evento registrado"), não lacuna preenchida.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..cache import Fetched
from ..http import get_json
from ..series_utils import Point

BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MIN_MAGNITUDE = 5.5
RADIUS_KM = 150
HISTORY_DAYS = 400

# (nome, latitude, longitude) — polos de wafer, memória e encapsulamento.
SITES: tuple[tuple[str, float, float], ...] = (
    ("Hsinchu, Taiwan (TSMC)", 24.78, 120.99),
    ("Tainan, Taiwan (TSMC)", 23.10, 120.29),
    ("Kumamoto, Japão (TSMC/JASM, Sony)", 32.88, 130.84),
    ("Kitakami, Japão (Kioxia)", 39.29, 141.11),
    ("Yokkaichi, Japão (Kioxia)", 34.97, 136.62),
    ("Pyeongtaek/Icheon, Coreia (Samsung, SK hynix)", 37.10, 127.25),
)


def daily_max_series(
    events: list[dict], start: datetime, end: datetime
) -> list[Point]:
    """Série diária com a maior magnitude do dia (0 sem evento)."""
    by_day: dict[str, float] = {}
    for ev in events:
        day = ev["time"].date().isoformat()
        by_day[day] = max(by_day.get(day, 0.0), float(ev["mag"]))
    out: list[Point] = []
    day = start.date()
    while day <= end.date():
        key = day.isoformat()
        out.append((key, by_day.get(key, 0.0)))
        day += timedelta(days=1)
    return out


def _parse_events(data: dict, site: str) -> list[dict]:
    events = []
    for feature in (data or {}).get("features") or []:
        props = feature.get("properties") or {}
        mag, ms = props.get("mag"), props.get("time")
        if mag is None or ms is None:
            continue
        events.append(
            {
                "id": feature.get("id"),
                "mag": float(mag),
                "time": datetime.fromtimestamp(ms / 1000, tz=timezone.utc),
                "place": props.get("place") or "",
                "site": site,
            }
        )
    return events


async def fetch_fab_quakes() -> Fetched:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=HISTORY_DAYS)
    events: dict[str, dict] = {}
    for site, lat, lon in SITES:
        data = await get_json(
            BASE,
            params={
                "format": "geojson",
                "starttime": start.date().isoformat(),
                "minmagnitude": str(MIN_MAGNITUDE),
                "latitude": str(lat),
                "longitude": str(lon),
                "maxradiuskm": str(RADIUS_KM),
                "orderby": "time",
            },
        )
        # O mesmo evento pode cair no raio de dois polos: conta uma vez.
        for ev in _parse_events(data, site):
            events.setdefault(ev["id"] or f"{ev['time']}-{ev['mag']}", ev)

    points = daily_max_series(list(events.values()), start, end)
    recent = sorted(events.values(), key=lambda e: e["time"], reverse=True)[:10]
    return Fetched(
        key="usgs.fab_quakes",
        label=f"USGS — terremotos ≥ {MIN_MAGNITUDE} a até {RADIUS_KM} km de polos de chips",
        provider="U.S. Geological Survey (FDSN Event API)",
        url="https://earthquake.usgs.gov/earthquakes/search/",
        status="ok",
        payload={
            "points": points,
            "events": [
                {
                    "mag": e["mag"],
                    "time": e["time"].isoformat(),
                    "place": e["place"],
                    "site": e["site"],
                }
                for e in recent
            ],
            "sites": [s[0] for s in SITES],
        },
        as_of=end,
        note=(
            f"{len(events)} evento(s) ≥ {MIN_MAGNITUDE} em {HISTORY_DAYS} dias perto de "
            f"{len(SITES)} polos (Taiwan, Japão, Coreia). Dia sem evento vale 0."
        ),
    )
