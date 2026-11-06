"""Cache com TTL e degradação para 'stale' em vez de erro.

Se uma fonte cai, preferimos servir o último valor bom marcado como `stale`
a devolver nada — mas nunca escondemos que o dado envelheceu.

O cache pode ser gravado num SQLite próprio (`save`/`load`), separado do
histórico, para que reiniciar o app não refaça buscas que ainda estão no
prazo. Entrada vencida volta já vencida: serve só de `stale` se a nova busca
falhar, nunca como dado fresco.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, get_args

from .schemas import SourceInfo, SourceStatus

log = logging.getLogger(__name__)


@dataclass
class Fetched:
    """Resultado de uma coleta, com proveniência anexada."""

    key: str
    label: str
    provider: str
    url: str
    status: SourceStatus
    payload: Any = None
    as_of: datetime | None = None
    fetched_at: datetime | None = None
    error: str | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "stale") and self.payload is not None

    def to_source_info(self) -> SourceInfo:
        return SourceInfo(
            key=self.key,
            label=self.label,
            provider=self.provider,
            url=self.url,
            status=self.status,
            as_of=self.as_of,
            fetched_at=self.fetched_at,
            error=self.error,
            note=self.note,
        )


# ---------------------------------------------------------------------------
# Payload <-> JSON sem perder tipo
# ---------------------------------------------------------------------------
#
# Os builders desempacotam séries como tuplas `(período, valor)` e a igualdade
# de `Fetched` compara tipos; por isso o que o JSON não tem nativamente vai
# marcado como {"__t": tipo, "v": valor}. Tipo fora desta lista não é
# persistido — a entrada inteira fica de fora, com aviso no log.

_TAG = "__t"


class _Unserializable(TypeError):
    pass


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # NaN/inf não existem em JSON estrito.
        return value if math.isfinite(value) else {_TAG: "float", "v": repr(value)}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, tuple):
        return {_TAG: "tuple", "v": [_encode(v) for v in value]}
    if isinstance(value, datetime):
        return {_TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {_TAG: "date", "v": value.isoformat()}
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value) and _TAG not in value:
            return {k: _encode(v) for k, v in value.items()}
        # Chave não-texto (ou que colide com a marcação): lista de pares.
        return {_TAG: "dict", "v": [[_encode(k), _encode(v)] for k, v in value.items()]}
    raise _Unserializable(type(value).__name__)


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if not isinstance(value, dict):
        return value
    tag = value.get(_TAG)
    if tag is None:
        return {k: _decode(v) for k, v in value.items()}
    raw = value["v"]
    if tag == "tuple":
        return tuple(_decode(v) for v in raw)
    if tag == "float":
        return float(raw)
    if tag == "datetime":
        return datetime.fromisoformat(raw)
    if tag == "date":
        return date.fromisoformat(raw)
    if tag == "dict":
        return {_decode(k): _decode(v) for k, v in raw}
    raise ValueError(f"marcação desconhecida no cache: {tag!r}")


def _iso(when: datetime | None) -> str | None:
    return when.isoformat() if when is not None else None


def _from_iso(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


# Muda quando a tabela ou a codificação do payload mudar; linha de outra
# versão é ignorada no load e sobrescrita no próximo save.
CACHE_FORMAT_VERSION = 1

_VALID_STATUS = frozenset(get_args(SourceStatus))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key            TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    provider       TEXT NOT NULL,
    url            TEXT NOT NULL,
    status         TEXT NOT NULL,
    as_of          TEXT,
    fetched_at     TEXT,
    expires_at     REAL NOT NULL,
    error          TEXT,
    note           TEXT,
    payload        TEXT NOT NULL,
    format_version INTEGER NOT NULL
)
"""

_UPSERT = """
INSERT INTO cache_entries
    (key, label, provider, url, status, as_of, fetched_at, expires_at,
     error, note, payload, format_version)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(key) DO UPDATE SET
    label = excluded.label, provider = excluded.provider, url = excluded.url,
    status = excluded.status, as_of = excluded.as_of,
    fetched_at = excluded.fetched_at, expires_at = excluded.expires_at,
    error = excluded.error, note = excluded.note, payload = excluded.payload,
    format_version = excluded.format_version
"""


@dataclass
class _Entry:
    value: Fetched
    expires_at: float
    stored_at: float = field(default_factory=time.monotonic)


# Prazo de uma falha guardada. Sem isso, cada start do app repetia todas as
# fontes que tinham acabado de falhar (o Comtrade, mês a mês, custava 60–90 s).
DEFAULT_FAILURE_TTL = 30 * 60


def _fresh(entry: _Entry | None, now: float, version: str | None) -> bool:
    """No prazo e, se pedida, da mesma `cache_version` do payload."""
    if entry is None or entry.expires_at <= now:
        return False
    if version is None:
        return True
    payload = entry.value.payload
    return isinstance(payload, dict) and payload.get("cache_version") == version


class TTLCache:
    def __init__(self, failure_ttl: int = DEFAULT_FAILURE_TTL) -> None:
        self.failure_ttl = failure_ttl
        self._data: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def save(self, path: str | os.PathLike[str]) -> int:
        """Grava todas as entradas em `path` (SQLite) numa transação.

        O prazo vai em epoch UTC, porque o relógio monotônico recomeça a cada
        processo. Devolve quantas entradas gravou. Falha de disco ou de banco
        só vai para o log: perder o cache nunca derruba a coleta.
        """
        now_mono, now_wall = time.monotonic(), time.time()
        rows = []
        for key, entry in list(self._data.items()):
            v = entry.value
            try:
                payload = json.dumps(_encode(v.payload), ensure_ascii=False, allow_nan=False)
            except (_Unserializable, ValueError) as exc:
                log.warning("cache: '%s' não persistido (tipo %s)", key, exc)
                continue
            rows.append(
                (
                    key, v.label, v.provider, v.url, v.status,
                    _iso(v.as_of), _iso(v.fetched_at),
                    now_wall + (entry.expires_at - now_mono),
                    v.error, v.note, payload, CACHE_FORMAT_VERSION,
                )
            )
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            try:
                with conn:
                    conn.execute(_SCHEMA)
                    conn.executemany(_UPSERT, rows)
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            log.warning("cache: não foi possível gravar em %s: %s", path, exc)
            return 0
        return len(rows)

    def load(self, path: str | os.PathLike[str]) -> int:
        """Carrega as entradas de `path`; devolve quantas entraram.

        Entrada no prazo vale como cache normal; vencida entra já vencida e só
        serve de `stale`. Banco ausente começa vazio. Banco ilegível é movido
        para `<path>.corrompido-<epoch>` (fica como evidência e deixa o próximo
        `save` recriar o arquivo). Linha de outra versão ou inválida é
        ignorada. Nada disso derruba o app; tudo vai para o log.
        """
        db = Path(path)
        if not db.exists():
            log.info("cache: %s ausente; começando vazio", db)
            return 0
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT key, label, provider, url, status, as_of, fetched_at,"
                    " expires_at, error, note, payload, format_version FROM cache_entries"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            aside = db.with_name(f"{db.name}.corrompido-{int(time.time())}")
            log.warning("cache: %s ilegível (%s); movido para %s, começando vazio", db, exc, aside)
            try:
                os.replace(db, aside)
            except OSError as move_exc:
                log.warning("cache: não foi possível mover %s: %s", db, move_exc)
            return 0

        now_mono, now_wall = time.monotonic(), time.time()
        loaded = skipped = 0
        for (key, label, provider, url, status, as_of, fetched_at,
             expires_at, error, note, payload, version) in rows:
            if version != CACHE_FORMAT_VERSION or status not in _VALID_STATUS:
                skipped += 1
                continue
            if key in self._data:  # o que já está em memória é mais novo
                continue
            try:
                value = Fetched(
                    key=key, label=label, provider=provider, url=url, status=status,
                    payload=_decode(json.loads(payload)),
                    as_of=_from_iso(as_of), fetched_at=_from_iso(fetched_at),
                    error=error, note=note,
                )
            except (ValueError, TypeError, KeyError) as exc:
                log.warning("cache: linha '%s' ilegível (%s); ignorada", key, exc)
                skipped += 1
                continue
            self._data[key] = _Entry(
                value=value, expires_at=now_mono + (float(expires_at) - now_wall)
            )
            loaded += 1
        if skipped:
            log.warning("cache: %d linhas de %s ignoradas (versão ou conteúdo)", skipped, db)
        log.info("cache: %d entradas carregadas de %s", loaded, db)
        return loaded

    def peek(self, key: str) -> Fetched | None:
        entry = self._data.get(key)
        return entry.value if entry else None

    async def get_or_fetch(
        self,
        key: str,
        ttl: int,
        fetcher: Callable[[], Awaitable[Fetched]],
        *,
        force: bool = False,
        failure_ttl: int | None = None,
        version: str | None = None,
    ) -> Fetched:
        """Retorna do cache ou executa `fetcher`.

        Em caso de falha, devolve o último valor bom marcado como `stale`;
        se nunca houve valor bom, devolve `unavailable` com a mensagem de erro.
        As duas saídas ficam guardadas por `min(ttl, failure_ttl)`: dentro
        desse prazo a fonte não é consultada de novo (salvo `force=True`), e
        a entrada vai para o `save` como qualquer outra. `failure_ttl` troca
        esse prazo para uma fonte só (loja: 24 h, K2 da T26).

        `version` (T35): entrada guardada com outro `payload["cache_version"]`
        conta como vencida, para a cesta nova da loja não esperar o prazo da
        antiga. A falha da coleta nova ainda devolve o valor antigo como
        `stale`; quem lê confere a versão.
        """
        now = time.monotonic()
        entry = self._data.get(key)
        if not force and _fresh(entry, now, version):
            return entry.value

        async with self._lock(key):
            # Outra corrotina pode ter preenchido enquanto esperávamos o lock.
            entry = self._data.get(key)
            now = time.monotonic()
            if not force and _fresh(entry, now, version):
                return entry.value

            try:
                result = await fetcher()
                result.fetched_at = datetime.now(timezone.utc)
                self._data[key] = _Entry(value=result, expires_at=now + ttl)
                return result
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                log.warning("fonte '%s' falhou: %s", key, msg)
                retry_at = now + (
                    failure_ttl if failure_ttl is not None else min(ttl, self.failure_ttl)
                )
                if entry is not None and entry.value.payload is not None:
                    stale = Fetched(
                        key=entry.value.key,
                        label=entry.value.label,
                        provider=entry.value.provider,
                        url=entry.value.url,
                        status="stale",
                        payload=entry.value.payload,
                        as_of=entry.value.as_of,
                        fetched_at=entry.value.fetched_at,
                        error=msg,
                        note="valor anterior reaproveitado; nova coleta falhou",
                    )
                    # O payload é o último valor bom: uma falha nunca o apaga.
                    self._data[key] = _Entry(value=stale, expires_at=retry_at)
                    return stale
                missing = Fetched(
                    key=key,
                    label=key,
                    provider="?",
                    url="",
                    status="unavailable",
                    error=msg,
                )
                self._data[key] = _Entry(value=missing, expires_at=retry_at)
                return missing


cache = TTLCache()
