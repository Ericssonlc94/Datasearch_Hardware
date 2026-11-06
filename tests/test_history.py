"""Histórico SQLite — testes offline (tmp_path, sem rede)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import Fetched  # noqa: E402
from app.services import history  # noqa: E402
from app.services.collector import build_snapshot  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return history.init_db(tmp_path / "historico.db")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ramp(start: float, end: float, days: int = 400) -> list[tuple[str, float]]:
    base = datetime(2025, 6, 1, tzinfo=timezone.utc)
    return [
        (_iso(base + timedelta(days=i)), start + (end - start) * i / (days - 1))
        for i in range(days)
    ]


def _fetched(key: str, points: list[tuple[str, float]]) -> Fetched:
    return Fetched(
        key=key,
        label=key,
        provider="teste",
        url="",
        status="ok",
        payload={"points": points},
        as_of=NOW,
    )


# ---------------- timestamp ----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-03", "2026-11-03T00:00:00Z"),
        ("2026-11", "2026-11-01T00:00:00Z"),
        ("202611", "2026-11-01T00:00:00Z"),
        ("2026-11-03T12:34:56Z", "2026-11-03T12:34:56Z"),
        ("2026-11-03T09:34:56-03:00", "2026-11-03T12:34:56Z"),
    ],
)
def test_normalize_ts(raw: str, expected: str):
    assert history.normalize_ts(raw) == expected


def test_normalize_ts_rejeita_lixo():
    assert history.normalize_ts("ontem") is None
    assert history.normalize_ts("") is None
    assert history.normalize_ts(None) is None


# ---------------- gravação e consulta ----------------


def test_record_e_query_preserva_timestamps(db: Path):
    history.record_points("sinal.x", [("2026-10-01", 10.0), ("2026-10-02", 11.0)])
    out = history.query(
        ["sinal.x"],
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert out["sinal.x"] == [
        ("2026-10-01T00:00:00Z", 10.0),
        ("2026-10-02T00:00:00Z", 11.0),
    ]


def test_regravar_o_mesmo_ponto_nao_duplica(db: Path):
    history.record_points("sinal.x", [("2026-10-01", 10.0)])
    history.record_points("sinal.x", [("2026-10-01", 12.0)])
    out = history.query(
        ["sinal.x"],
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert out["sinal.x"] == [("2026-10-01T00:00:00Z", 12.0)]


def test_bucket_deixa_lacuna_explicita(db: Path):
    """Buraco de 3 horas vira `None` — nunca interpolação."""
    history.record_points(
        "sinal.x",
        [
            ("2026-10-01T00:00:00Z", 1.0),
            ("2026-10-01T04:00:00Z", 2.0),
        ],
    )
    out = history.query(
        ["sinal.x"],
        datetime(2026, 10, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 4, tzinfo=timezone.utc),
        bucket_seconds=3600,
        max_raw_points=1,
    )
    valores = [v for _, v in out["sinal.x"]]
    assert valores[0] == 1.0 and valores[-1] == 2.0
    assert valores[1:4] == [None, None, None]


def test_bucket_nao_inventa_ponto_fora_da_janela(db: Path):
    history.record_points("sinal.x", [("2026-10-01T00:00:00Z", 1.0)])
    out = history.query(
        ["sinal.x"],
        datetime(2026, 10, 1, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
        bucket_seconds=3600,
        max_raw_points=0,
    )
    assert out["sinal.x"] == []


def test_serie_pequena_nao_e_bucketizada(db: Path):
    """Mensal em janela de 90 dias tem 3 pontos: devolver cru é mais honesto."""
    history.record_points(
        "obs.gpu.ipca",
        [("2026-08", 1.0), ("2026-09", 2.0), ("2026-10", 3.0)],
    )
    out = history.query(
        ["obs.gpu.ipca"],
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 1, tzinfo=timezone.utc),
        bucket_seconds=86_400,
        max_raw_points=600,
    )
    assert len(out["obs.gpu.ipca"]) == 3


def test_bounds_e_primeiro_ponto_orientam_os_periodos_da_ui(db: Path):
    history.record_points(
        "iph",
        [("2026-10-01T00:00:00Z", 50.0), ("2026-10-03T00:00:00Z", 55.0)],
    )
    history.record_points("signal.x", [("2026-10-02T00:00:00Z", 1.0)])

    bounds = history.available_bounds()
    assert bounds["iph"] == {
        "points": 2,
        "first": "2026-10-01T00:00:00Z",
        "last": "2026-10-03T00:00:00Z",
    }
    assert bounds["signal.x"]["points"] == 1
    assert history.first_ts(["iph"]) == "2026-10-01T00:00:00Z"
    assert history.first_ts(["signal.x"]) == "2026-10-02T00:00:00Z"
    assert history.first_ts() == "2026-10-01T00:00:00Z"
    assert history.last_ts() == "2026-10-03T00:00:00Z"


# ---------------- snapshot completo ----------------


def test_record_snapshot_grava_agregados_e_fontes(db: Path):
    collected = {
        "market.micron": _fetched("market.micron", _ramp(80, 150)),
        "market.soxx": _fetched("market.soxx", _ramp(200, 280)),
        "bcb.ptax_usd": _fetched("bcb.ptax_usd", _ramp(5.0, 5.6)),
    }
    snap = build_snapshot(collected)
    snap.generated_at = NOW
    history.record_snapshot(snap)

    keys = history.available_keys()
    for expected in (
        "iph",
        "iph_br",
        "coverage",
        "driver.alocacao_chips",
        "signal.micron",
        "cat.gpu.pressure",
        "cat.gpu.proj30_global",
        "cat.gpu.proj30_br",
    ):
        assert keys.get(expected, 0) > 0, f"chave {expected} não foi gravada"

    # O agregado usa o instante do snapshot…
    iph = history.query(
        ["iph"], NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)
    )["iph"]
    assert iph == [("2026-11-03T12:00:00Z", snap.summary.iph)]
    # …e a série de fonte mantém a data real (diária), não a da coleta.
    micron = history.query(
        ["signal.micron"],
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        NOW,
    )["signal.micron"]
    # O analyzer expõe os últimos 180 pontos de cada sinal.
    assert len(micron) == 180
    assert micron[0][0].endswith("T00:00:00Z")


# ---------------- retenção ----------------


def test_purge_compacta_em_duas_camadas(db: Path):
    antigo = NOW - timedelta(days=400)
    expirado = NOW - timedelta(days=800)
    history.record_points(
        "sinal.x",
        [
            (_iso(antigo), 1.0),
            (_iso(antigo + timedelta(hours=2)), 2.0),
            (_iso(antigo + timedelta(hours=4)), 3.0),
            (_iso(expirado), 9.0),
        ],
    )

    removidos, compactados = history.purge(now=NOW)
    assert removidos == 1
    assert compactados == 2

    restante = history.query(
        ["sinal.x"],
        NOW - timedelta(days=900),
        NOW,
        max_raw_points=10_000,
    )["sinal.x"]
    assert restante == [(_iso(antigo + timedelta(hours=4)), 3.0)]


def test_purge_nao_toca_no_historico_recente(db: Path):
    history.record_points(
        "sinal.x",
        [(_iso(NOW - timedelta(days=1)), 1.0), (_iso(NOW - timedelta(hours=1)), 2.0)],
    )
    removidos, compactados = history.purge(now=NOW)
    assert (removidos, compactados) == (0, 0)
    assert len(history.query(["sinal.x"], NOW - timedelta(days=2), NOW)["sinal.x"]) == 2


def test_conexao_sobrevive_a_falha_transitoria_do_wal(monkeypatch):
    """Num mount de rede o PRAGMA WAL pode falhar; leitura não pode cair."""

    class FakeConn:
        def __init__(self):
            self.sql: list[str] = []

        def execute(self, sql: str, *args):
            self.sql.append(sql)
            if "journal_mode" in sql:
                raise history.sqlite3.OperationalError("disk I/O error")
            return self

    fake = FakeConn()
    monkeypatch.setattr(history.sqlite3, "connect", lambda *a, **k: fake)
    assert history._connect() is fake
    assert any("busy_timeout" in s for s in fake.sql)
    assert any("journal_mode" in s for s in fake.sql)
    assert any("synchronous" in s for s in fake.sql)
