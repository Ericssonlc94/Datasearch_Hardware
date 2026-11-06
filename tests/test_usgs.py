"""USGS — terremotos perto dos polos de chips, testes offline, sem rede.

O filtro de magnitude (≥ 5,5) e de raio (150 km) é feito pela API; aqui
conferimos que o pedido sai com esses limites para cada polo, que o pico do
dia é a maior magnitude, que dia sem evento vale 0 e que o mesmo evento
visto por dois polos conta uma vez.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import usgs  # noqa: E402


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _feature(eid, mag, when, place="near Hualien"):
    return {"id": eid, "properties": {"mag": mag, "time": _ms(when), "place": place}}


def test_limites_publicados():
    assert usgs.MIN_MAGNITUDE == 5.5
    assert usgs.RADIUS_KM == 150


def test_pico_do_dia_e_zero_sem_evento():
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 4, 23, tzinfo=timezone.utc)
    events = [
        {"mag": 5.6, "time": datetime(2026, 4, 2, 1, tzinfo=timezone.utc)},
        {"mag": 7.4, "time": datetime(2026, 4, 2, 23, tzinfo=timezone.utc)},
        {"mag": 6.0, "time": datetime(2026, 4, 2, 12, tzinfo=timezone.utc)},
        {"mag": 6.1, "time": datetime(2026, 3, 20, tzinfo=timezone.utc)},  # fora
    ]
    pts = usgs.daily_max_series(events, start, end)
    assert pts == [
        ("2026-04-01", 0.0),
        ("2026-04-02", 7.4),
        ("2026-04-03", 0.0),
        ("2026-04-04", 0.0),
    ]


def test_parse_ignora_evento_sem_magnitude_ou_hora():
    when = datetime(2026, 4, 2, 23, 58, tzinfo=timezone.utc)
    data = {
        "features": [
            _feature("us1", 7.4, when),
            {"id": "us2", "properties": {"mag": None, "time": _ms(when)}},
            {"id": "us3", "properties": {"mag": 6.0}},
        ]
    }
    events = usgs._parse_events(data, "Hsinchu")
    assert len(events) == 1
    assert events[0]["mag"] == 7.4 and events[0]["time"] == when
    assert events[0]["site"] == "Hsinchu"
    assert usgs._parse_events(None, "x") == []


def test_coleta_pede_limites_por_polo_e_deduplica(monkeypatch):
    now = datetime.now(timezone.utc)
    big = now - timedelta(days=3)
    small = now - timedelta(days=10)
    calls: list[dict] = []

    async def fake_get_json(url, **kw):
        params = kw["params"]
        calls.append(params)
        if params["latitude"] == str(usgs.SITES[0][1]):  # Hsinchu
            return {"features": [_feature("us7", 7.4, big), _feature("us6", 5.8, small)]}
        if params["latitude"] == str(usgs.SITES[1][1]):  # Tainan vê o mesmo evento
            return {"features": [_feature("us7", 7.4, big)]}
        return {"features": []}

    monkeypatch.setattr(usgs, "get_json", fake_get_json)
    fetched = asyncio.run(usgs.fetch_fab_quakes())

    assert len(calls) == len(usgs.SITES)
    for params in calls:
        assert params["minmagnitude"] == "5.5"
        assert params["maxradiuskm"] == "150"
        assert params["format"] == "geojson"

    assert len(fetched.payload["events"]) == 2  # us7 contado uma vez
    assert "2 evento(s)" in fetched.note
    by_day = dict(fetched.payload["points"])
    assert by_day[big.date().isoformat()] == 7.4
    assert by_day[small.date().isoformat()] == 5.8
    assert sum(1 for _, v in fetched.payload["points"] if v == 0.0) == len(by_day) - 2
    assert fetched.payload["events"][0]["mag"] == 7.4  # mais recente primeiro
