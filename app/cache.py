"""Cache com TTL e degradação para 'stale' em vez de erro.

Se uma fonte cai, preferimos servir o último valor bom marcado como `stale`
a devolver nada — mas nunca escondemos que o dado envelheceu.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

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


@dataclass
class _Entry:
    value: Fetched
    expires_at: float
    stored_at: float = field(default_factory=time.monotonic)


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

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
    ) -> Fetched:
        """Retorna do cache ou executa `fetcher`.

        Em caso de falha, devolve o último valor bom marcado como `stale`;
        se nunca houve valor bom, devolve `unavailable` com a mensagem de erro.
        """
        now = time.monotonic()
        entry = self._data.get(key)
        if not force and entry and entry.expires_at > now:
            return entry.value

        async with self._lock(key):
            # Outra corrotina pode ter preenchido enquanto esperávamos o lock.
            entry = self._data.get(key)
            now = time.monotonic()
            if not force and entry and entry.expires_at > now:
                return entry.value

            try:
                result = await fetcher()
                result.fetched_at = datetime.now(timezone.utc)
                self._data[key] = _Entry(value=result, expires_at=now + ttl)
                return result
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                log.warning("fonte '%s' falhou: %s", key, msg)
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
                    # Tenta de novo mais cedo do que o TTL normal.
                    self._data[key] = _Entry(value=stale, expires_at=now + min(ttl, 300))
                    return stale
                return Fetched(
                    key=key,
                    label=key,
                    provider="?",
                    url="",
                    status="unavailable",
                    error=msg,
                )


cache = TTLCache()
