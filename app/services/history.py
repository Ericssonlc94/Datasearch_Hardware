"""Histórico em SQLite: uma linha por (timestamp, métrica).

Três regras que valem mais que a performance:

1. **Nada é interpolado.** Bucket sem observação vira `None` no payload e o
   frontend quebra a linha. Preencher buraco seria inventar dado.
2. **Timestamp é o da observação, não o da coleta.** Série diária do Yahoo
   entra com a data do pregão; mensal do IPCA com o primeiro dia do mês. Só
   os agregados calculados (`iph`, `driver.*`, `cat.*`) usam o instante do
   snapshot, porque eles realmente são recalculados a cada ciclo.
3. **Retenção em duas camadas.** 30 dias em alta frequência para o gráfico
   de curto prazo; depois disso, uma linha por dia por métrica, por 2 anos.
4. **Reconstruído é marcado.** Dias anteriores ao primeiro ciclo ao vivo podem
   receber um ponto diário recalculado (`kind='reconstructed'`, ver
   `domain/backfill.py`). Ele nunca substitui um ponto medido ao vivo.

O banco fica em `data/history.db` (ignorado pelo git). Escrita e leitura
rodam em thread separada (`asyncio.to_thread`) porque o driver `sqlite3` é
bloqueante.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from ..config import settings
from ..domain import series as series_catalog
from ..domain.prices import KABUM_SELLER

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _PROJECT_ROOT / p


_db_path: Path = _resolve(settings.history_path)

# Abaixo disso, devolver os pontos originais é mais útil (e mais honesto) do
# que jogar tudo em um bucket diário. O limite também evita payload gigante.
MAX_RAW_POINTS = 600


def init_db(path: str | Path | None = None) -> Path:
    """Cria o arquivo e o schema. Idempotente."""
    global _db_path
    if path is not None:
        _db_path = _resolve(path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metric (
                ts    TEXT NOT NULL,
                key   TEXT NOT NULL,
                value REAL NOT NULL,
                kind  TEXT NOT NULL DEFAULT 'observed',
                PRIMARY KEY (ts, key)
            );
            CREATE INDEX IF NOT EXISTS idx_metric_key_ts ON metric (key, ts);
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            -- Marco da fila gravado pela T10b com chaves próprias: passa para o
            -- formato por série sem perder o instante já registrado.
            INSERT OR IGNORE INTO meta (key, value)
                SELECT 'model.supply.queue', value FROM meta WHERE key = 'queue_model';
            INSERT OR IGNORE INTO meta (key, value)
                SELECT 'model_since.supply.queue', value FROM meta
                WHERE key = 'queue_model_since';
            """
        )
    log.info("histórico em %s", _db_path)
    return _db_path


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(_resolve(path) if path else _db_path), timeout=15.0)
    conn.execute("PRAGMA busy_timeout=15000")
    # WAL é persistente no arquivo; repetir o pragma a cada conexão só cria
    # mais uma chance de falhar em filesystem de rede (ntfs-3g, FUSE). Se o
    # modo já estiver gravado, seguir sem ele é seguro para leitura.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        log.warning("não foi possível confirmar o modo WAL; seguindo", exc_info=True)
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def _db(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre, comita e **fecha** a conexão (o `with` do sqlite3 não fecha)."""
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------- timestamp ----------------


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_ts(raw: str) -> str | None:
    """Aceita `YYYY-MM-DD`, `YYYY-MM`, `YYYYMM` e ISO completo. Devolve UTC."""
    if raw is None:
        return None
    t = str(raw).strip()
    if not t:
        return None
    if len(t) >= 19:
        try:
            return _iso(datetime.fromisoformat(t.replace("Z", "+00:00")))
        except ValueError:
            return None
    fmt = {10: "%Y-%m-%d", 7: "%Y-%m", 6: "%Y%m", 8: "%Y%m%d"}.get(len(t))
    if fmt is None:
        return None
    try:
        return _iso(datetime.strptime(t, fmt))
    except ValueError:
        return None


# ---------------- escrita ----------------


def _upsert(conn: sqlite3.Connection, rows: Iterable[tuple[str, str, float, str]]) -> int:
    # Chave duplicada no mesmo lote: o último valor vence.
    unique: dict[tuple[str, str], tuple[str, str, float, str]] = {}
    for row in rows:
        unique[(row[0], row[1])] = row
    if not unique:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO metric (ts, key, value, kind) VALUES (?, ?, ?, ?)",
        list(unique.values()),
    )
    return len(unique)


def record_points(
    key: str,
    points: Sequence[tuple[str, float]],
    *,
    kind: str = "observed",
    path: str | Path | None = None,
) -> int:
    """Grava pontos crus de uma série (timestamps originais preservados)."""
    rows = []
    for raw_ts, value in points:
        ts = normalize_ts(raw_ts)
        if ts is None or value is None:
            continue
        rows.append((ts, key, float(value), kind))
    with _db(path) as conn:
        return _upsert(conn, rows)


def _signal_points(signal) -> list[tuple[str, float]]:
    return [(p.t, p.v) for p in (signal.series or []) if p.v is not None]


def record_snapshot(snap, *, path: str | Path | None = None) -> int:
    """Extrai do Snapshot tudo que o gráfico de tendência pode pedir.

    Agregados calculados usam o instante do snapshot; séries de fonte mantêm a
    data real de cada observação. Reexecutar o mesmo snapshot é idempotente.
    """
    ts = _iso(snap.generated_at)
    rows: list[tuple[str, str, float, str]] = [
        (ts, "iph", float(snap.summary.iph), "modeled"),
        (ts, "iph_br", float(snap.summary.iph_brazil), "modeled"),
        (ts, "coverage", float(snap.summary.coverage) * 100.0, "modeled"),
    ]

    for driver in snap.drivers:
        rows.append((ts, f"driver.{driver.key}", float(driver.score), "modeled"))
        for signal in driver.signals:
            rows.extend(
                (norm, f"signal.{signal.key}", float(v), signal.kind)
                for raw_ts, v in _signal_points(signal)
                if (norm := normalize_ts(raw_ts)) is not None
            )

    supply = getattr(snap, "supply", None)
    if supply is not None:
        for key, value, kind in (
            ("supply.queue", supply.queue_pressure, "modeled"),
            ("supply.capex_ttm", supply.capex_ttm_usd, "observed"),
            ("supply.inventory_ratio", supply.inventory_ratio, "observed"),
            ("supply.diversion", supply.diversion_index, "modeled"),
            ("supply.comtrade_volume", supply.comtrade_volume_usd, "observed"),
        ):
            if value is not None:
                rows.append((ts, key, float(value), kind))

    for item in snap.ranking:
        rows.extend(
            [
                (ts, f"cat.{item.key}.pressure", float(item.pressure_score), "modeled"),
                (ts, f"cat.{item.key}.proj30_global", float(item.projected_global_30d_pct), "modeled"),
                (ts, f"cat.{item.key}.proj30_br", float(item.projected_brazil_30d_pct), "modeled"),
            ]
        )
        obs = item.observed_br
        if obs is not None:
            rows.extend(
                (norm, f"obs.{item.key}.ipca", float(p.v), "observed")
                for p in (obs.series or [])
                if p.v is not None and (norm := normalize_ts(p.t)) is not None
            )
        imp = item.imports
        if imp is not None and imp.usd_per_kg is not None and imp.period:
            obs_ts = normalize_ts(imp.period)
            if obs_ts:
                rows.append((obs_ts, f"obs.{item.key}.usd_kg", float(imp.usd_per_kg), "observed"))

    rows.extend(_price_rows(ts, getattr(snap, "prices", None)))

    with _db(path) as conn:
        _mark_models(conn, ts, {key for _, key, _, _ in rows})
        return _upsert(conn, rows)


RECONSTRUCTED = "reconstructed"


def _price_rows(ts: str, view: dict | None) -> list[tuple[str, str, float, str]]:
    """Séries `price.*` do catálogo (preço cheio da faixa e visão por marca)."""
    if not isinstance(view, dict) or (view.get("source") or {}).get("status") == "disabled":
        return []
    rows: list[tuple[str, str, float, str]] = []

    def add(key: str | None, value) -> None:
        if key and isinstance(value, (int, float)) and not isinstance(value, bool):
            rows.append((ts, key, float(value), "observed"))

    for cat in view.get("categories") or []:
        for tier in cat.get("tiers") or []:
            add(tier.get("series"), tier.get("price_full_brl"))
    for tier in (view.get("brand_view") or {}).get("tiers") or []:
        for brand in ("nvidia", "amd"):
            cell = tier.get(brand) or {}
            add(cell.get("series"), cell.get("price_full_brl"))
        add(tier.get("diff_series"), tier.get("diff_amd_pct"))
    return rows


# ---------------- URLs da loja ----------------
#
# Uma linha por dia por URL: `kabum.<code>.full`, `.cash` e `.avail` (1/0).
# Séries internas, fora do catálogo público: servem ao domínio de preço
# (salto K14d e variação de 30 dias), que recebe os últimos dias por `code`.

_LISTING_FIELDS = ("full", "cash", "avail")


def record_listings(listings: Sequence[dict], *, path: str | Path | None = None) -> int:
    """Grava as observações do dia.

    Preço só conta se vendido pelo vendedor fixado na curadoria
    (`seller_expected`, T33); sem ele, pela própria loja.
    """
    rows: list[tuple[str, str, float, str]] = []
    for item in listings:
        code, day = str(item.get("code") or ""), item.get("day")
        if not code.isdigit() or not day or (ts := normalize_ts(str(day))) is None:
            continue
        own = item.get("seller") in (None, item.get("seller_expected") or KABUM_SELLER)
        available = bool(item.get("available")) and own
        rows.append((ts, f"kabum.{code}.avail", 1.0 if available else 0.0, "observed"))
        for name, field_ in (("full", "price_full"), ("cash", "price_cash")):
            value = item.get(field_)
            if available and isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                rows.append((ts, f"kabum.{code}.{name}", float(value), "observed"))
    with _db(path) as conn:
        return _upsert(conn, rows)


def listing_history(
    codes: Sequence[str], *, days: int = 60, path: str | Path | None = None
) -> dict[str, list[dict]]:
    """`code` → [{day, full, cash, avail}] em ordem de data, dos últimos `days`."""
    keys = [f"kabum.{c}.{f}" for c in codes for f in _LISTING_FIELDS]
    if not keys:
        return {}
    start = _iso(datetime.now(timezone.utc) - timedelta(days=days))
    marks = ",".join("?" for _ in keys)
    with _db(path) as conn:
        rows = conn.execute(
            f"SELECT ts, key, value FROM metric WHERE key IN ({marks}) AND ts >= ? ORDER BY ts",
            (*keys, start),
        ).fetchall()
    by_day: dict[tuple[str, str], dict] = {}
    for ts, key, value in rows:
        _, code, name = key.split(".")
        day = by_day.setdefault((code, ts[:10]), {"day": ts[:10], "full": None, "cash": None, "avail": 0})
        day[name] = int(value) if name == "avail" else value
    out: dict[str, list[dict]] = {}
    for (code, _), day in sorted(by_day.items(), key=lambda kv: kv[0][1]):
        out.setdefault(code, []).append(day)
    return out


# ---------------- Modelos da cesta (T35) ----------------
#
# Uma série interna `kabum_model.<key>` por modelo, um ponto por dia, fora do
# catálogo público. Serve à variação pareada de 30 dias do domínio.

_MODEL_PREFIX = "kabum_model."


def record_model_prices(
    values: dict, day: date, *, path: str | Path | None = None
) -> int:
    """Grava o preço do dia de cada `kabum_model.*`; ignora as outras chaves."""
    ts = normalize_ts(day.isoformat())
    rows = [
        (ts, key, float(value), "observed")
        for key, value in (values or {}).items()
        if isinstance(key, str) and key.startswith(_MODEL_PREFIX)
        and isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    ]
    if not rows or ts is None:
        return 0
    with _db(path) as conn:
        return _upsert(conn, rows)


def model_price_history(
    keys: Sequence[str], *, days: int = 60, path: str | Path | None = None
) -> dict[str, list[tuple[date, float]]]:
    """`kabum_model.<key>` → [(dia, preço)] dos últimos `days`, em ordem de data."""
    keys = [k for k in keys if k.startswith(_MODEL_PREFIX)]
    if not keys:
        return {}
    start = _iso(datetime.now(timezone.utc) - timedelta(days=days))
    marks = ",".join("?" for _ in keys)
    with _db(path) as conn:
        rows = conn.execute(
            f"SELECT ts, key, value FROM metric WHERE key IN ({marks}) AND ts >= ? ORDER BY ts",
            (*keys, start),
        ).fetchall()
    out: dict[str, list[tuple[date, float]]] = {}
    for ts, key, value in rows:
        out.setdefault(key, []).append((date.fromisoformat(ts[:10]), value))
    return out

# Versão da conta da fila gravada em `supply.queue`. Pontos anteriores ao
# marco usavam o estoque em % bruto (fila presa em 100, T06).
QUEUE_MODEL_VERSION = "zscore-2026-11-04"


def model_versions() -> dict[str, str]:
    """Série → versão da conta que a gera.

    A chave é o nome exato da série ou um prefixo terminado em "." (`cat.`
    cobre `cat.gpu.pressure` etc.). Na 1ª gravação com uma versão nova, o
    instante do snapshot vira o `model_since` da série: os pontos anteriores
    ficam no banco, só sinalizados, porque apagar histórico é decisão do
    usuário. Série sem versão declarada não tem marco. O Modelo declara as
    próprias em `domain.series.MODEL_VERSIONS`, que valem por cima destas.
    """
    return {
        "supply.queue": QUEUE_MODEL_VERSION,
        **getattr(series_catalog, "MODEL_VERSIONS", {}),
    }


def _matches(key: str, pattern: str) -> bool:
    return key.startswith(pattern) if pattern.endswith(".") else key == pattern


def _mark_models(conn: sqlite3.Connection, ts: str, keys: set[str]) -> None:
    for pattern, version in model_versions().items():
        if not any(_matches(k, pattern) for k in keys):
            continue
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (f"model.{pattern}",)
        ).fetchone()
        if row is None or row[0] != version:
            conn.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                [(f"model.{pattern}", version), (f"model_since.{pattern}", ts)],
            )
            log.info("histórico: conta de %s mudou para %s em %s", pattern, version, ts)


def model_breaks(*, path: str | Path | None = None) -> dict[str, str]:
    """Série (ou prefixo) → instante a partir do qual a conta atual vale."""
    with _db(path) as conn:
        rows = conn.execute(
            "SELECT substr(key, 13), value FROM meta WHERE substr(key, 1, 12) = 'model_since.'"
        ).fetchall()
    return dict(rows)


def model_since_for(key: str, breaks: dict[str, str]) -> str | None:
    """Marco que vale para `key`: o nome exato ganha do prefixo mais longo."""
    if key in breaks:
        return breaks[key]
    prefixes = [p for p in breaks if p.endswith(".") and key.startswith(p)]
    return breaks[max(prefixes, key=len)] if prefixes else None


def record_reconstruction(
    days: dict,
    model_version: str,
    *,
    path: str | Path | None = None,
) -> int:
    """Grava o IPH reconstruído por dia (fim do dia, UTC).

    Regras: só dias **anteriores ao primeiro IPH medido ao vivo** — buraco
    entre ciclos ao vivo (app desligado) continua lacuna, e o trecho
    reconstruído fica sempre à esquerda da medição; ponto reconstruído já
    gravado com a mesma versão do modelo não é refeito (a série fica estável
    entre ciclos); versão nova do modelo apaga a reconstrução anterior.
    """
    with _db(path) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'reconstruction_model'"
        ).fetchone()
        if row is None or row[0] != model_version:
            removed = conn.execute(
                "DELETE FROM metric WHERE kind = ?", (RECONSTRUCTED,)
            ).rowcount
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('reconstruction_model', ?)",
                (model_version,),
            )
            if removed:
                log.info("reconstrução: modelo mudou, %d ponto(s) refeito(s)", removed)

        first_live = conn.execute(
            "SELECT MIN(substr(ts, 1, 10)) FROM metric WHERE key = 'iph' AND kind != ?",
            (RECONSTRUCTED,),
        ).fetchone()[0]
        rows = [
            (f"{day.isoformat()}T23:59:59Z", key, float(value), RECONSTRUCTED)
            for day, values in days.items()
            if first_live is None or day.isoformat() < first_live
            for key, value in values
        ]
        if not rows:
            return 0
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO metric (ts, key, value, kind) VALUES (?, ?, ?, ?)",
            rows,
        )
        return conn.total_changes - before


def reconstructed_until(
    keys: Sequence[str], path: str | Path | None = None
) -> dict[str, str]:
    """Último instante reconstruído por chave (chaves sem reconstrução ficam fora)."""
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    with _db(path) as conn:
        rows = conn.execute(
            f"SELECT key, MAX(ts) FROM metric WHERE kind = ? AND key IN ({placeholders}) "
            "GROUP BY key",
            (RECONSTRUCTED, *keys),
        ).fetchall()
    return {key: ts for key, ts in rows if ts}


# ---------------- leitura ----------------


def query(
    keys: Sequence[str],
    start: datetime,
    end: datetime,
    *,
    bucket_seconds: int | None = None,
    max_raw_points: int = MAX_RAW_POINTS,
    path: str | Path | None = None,
) -> dict[str, list[tuple[str, float | None]]]:
    """Séries do intervalo, opcionalmente reduzidas a buckets.

    Bucket guarda o **último** valor observado dentro da janela — nunca a média,
    que inventaria um ponto que não existe. Buckets vazios viram `None`.
    """
    if not keys:
        return {}

    start_iso, end_iso = _iso(start), _iso(end)
    placeholders = ",".join("?" for _ in keys)
    sql = (
        f"SELECT key, ts, value FROM metric "
        f"WHERE key IN ({placeholders}) AND ts >= ? AND ts <= ? "
        f"ORDER BY key, ts"
    )
    with _db(path) as conn:
        rows = conn.execute(sql, (*keys, start_iso, end_iso)).fetchall()

    raw: dict[str, list[tuple[str, float]]] = {k: [] for k in keys}
    for key, ts, value in rows:
        raw.setdefault(key, []).append((ts, float(value)))

    out: dict[str, list[tuple[str, float | None]]] = {}
    for key, points in raw.items():
        if not bucket_seconds or len(points) <= max_raw_points:
            out[key] = [(ts, v) for ts, v in points]
            continue
        out[key] = _bucketize(points, start, end, bucket_seconds)
    return out


def _bucketize(
    points: list[tuple[str, float]],
    start: datetime,
    end: datetime,
    bucket_seconds: int,
) -> list[tuple[str, float | None]]:
    slots: dict[int, float] = {}
    for ts, value in points:
        epoch = int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
        slots[epoch // bucket_seconds] = value  # pontos ordenados: último vence

    first = int(start.timestamp()) // bucket_seconds
    last = int(end.timestamp()) // bucket_seconds
    grid: list[tuple[str, float | None]] = []
    for slot in range(first, last + 1):
        ts = _iso(datetime.fromtimestamp(slot * bucket_seconds, tz=timezone.utc))
        grid.append((ts, slots.get(slot)))

    # Remove nulos nas pontas; os internos são lacunas reais e ficam.
    while grid and grid[0][1] is None:
        grid.pop(0)
    while grid and grid[-1][1] is None:
        grid.pop()
    return grid


def available_keys(path: str | Path | None = None) -> dict[str, int]:
    """Quantas observações existem por chave — usado pelo catálogo da UI."""
    with _db(path) as conn:
        rows = conn.execute("SELECT key, COUNT(*) FROM metric GROUP BY key").fetchall()
    return {key: int(count) for key, count in rows}


def available_bounds(
    path: str | Path | None = None,
) -> dict[str, dict[str, int | str | None]]:
    """Pontos e extremos por chave.

    O frontend usa os extremos para oferecer só períodos que o banco realmente
    cobre. Assim um botão de 30 dias não fica clicável quando só existem horas
    de histórico.
    """
    with _db(path) as conn:
        rows = conn.execute(
            "SELECT key, COUNT(*), MIN(ts), MAX(ts) FROM metric GROUP BY key"
        ).fetchall()
    return {
        key: {
            "points": int(count),
            "first": first,
            "last": last,
        }
        for key, count, first, last in rows
    }


def first_ts(
    keys: Sequence[str] | None = None,
    path: str | Path | None = None,
) -> str | None:
    """Primeira observação (de todas as chaves ou de um subconjunto)."""
    with _db(path) as conn:
        if keys:
            placeholders = ",".join("?" for _ in keys)
            row = conn.execute(
                f"SELECT MIN(ts) FROM metric WHERE key IN ({placeholders})",
                tuple(keys),
            ).fetchone()
        else:
            row = conn.execute("SELECT MIN(ts) FROM metric").fetchone()
    return row[0] if row else None


def last_ts(path: str | Path | None = None) -> str | None:
    with _db(path) as conn:
        row = conn.execute("SELECT MAX(ts) FROM metric").fetchone()
    return row[0] if row else None


# ---------------- retenção ----------------


def purge(
    now: datetime | None = None,
    *,
    path: str | Path | None = None,
) -> tuple[int, int]:
    """Aplica a retenção em duas camadas. Devolve (removidos_antigos, compactados)."""
    now = now or datetime.now(timezone.utc)
    daily_cut = _iso(now - timedelta(days=settings.history_daily_retention_days))
    hot_cut = _iso(now - timedelta(days=settings.history_retention_days))

    with _db(path) as conn:
        old = conn.execute("DELETE FROM metric WHERE ts < ?", (daily_cut,)).rowcount
        # Entre 30 dias e 2 anos: mantém só a última linha de cada dia por métrica.
        compacted = conn.execute(
            """
            DELETE FROM metric
            WHERE ts < ?
              AND rowid NOT IN (
                  SELECT MAX(rowid) FROM metric
                  WHERE ts < ? AND ts >= ?
                  GROUP BY key, substr(ts, 1, 10)
              )
            """,
            (hot_cut, hot_cut, daily_cut),
        ).rowcount
    if old or compacted:
        log.info("retenção: %d linha(s) expirada(s), %d compactada(s)", old, compacted)
    return old, compacted
