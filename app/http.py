"""Cliente HTTP compartilhado com retry e tratamento uniforme de erro."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.user_agent,
        "Accept": "application/json, text/csv, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout),
            headers=_headers(),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class FetchError(RuntimeError):
    """Falha definitiva ao buscar um recurso externo."""


_limiters: dict[str, asyncio.Semaphore] = {}


def limiter(name: str, concurrency: int) -> asyncio.Semaphore:
    """Semáforo nomeado para não estourar o limite de taxa de um provedor.

    Comex Stat e UN Comtrade devolvem 429 quando recebem uma rajada paralela.
    Coletar essas fontes em fila é mais rápido do que apanhar do rate limit.
    """
    sem = _limiters.get(name)
    if sem is None or sem._value > concurrency:  # noqa: SLF001
        sem = asyncio.Semaphore(concurrency)
        _limiters[name] = sem
    return sem


@dataclass
class _Breaker:
    fails: int = 0
    open_until: float = 0.0


_breakers: dict[str, _Breaker] = {}


def breaker_guard(name: str) -> None:
    """Levanta FetchError se o disjuntor do provedor estiver aberto.

    Quando um provedor bloqueia a rede inteira (WAF respondendo 429 a tudo),
    insistir em cada categoria custa dezenas de segundos por ciclo e não muda
    o resultado. Depois de N falhas seguidas, paramos de tentar por um tempo.
    """
    b = _breakers.get(name)
    if b and b.open_until > time.monotonic():
        restante = int(b.open_until - time.monotonic())
        raise FetchError(
            f"disjuntor aberto para '{name}' apos {b.fails} falhas seguidas; "
            f"nova tentativa em ~{restante}s"
        )


def breaker_record(name: str, ok: bool, *, threshold: int = 3, cooldown: float = 900.0) -> None:
    b = _breakers.setdefault(name, _Breaker())
    if ok:
        b.fails, b.open_until = 0, 0.0
        return
    b.fails += 1
    if b.fails >= threshold:
        b.open_until = time.monotonic() + cooldown


def _retry_after(resp: httpx.Response, fallback: float) -> float:
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return min(float(raw), 30.0)
        except ValueError:
            pass
    return fallback


# Insistir em 429 só piora: o provedor já disse que estamos rápido demais.
# Uma retentativa e seguimos — o cache serve o último valor bom enquanto isso.
_MAX_429_RETRIES = 1


async def _request(method: str, url: str, **kw: Any) -> httpx.Response:
    client = await get_client()
    last: Exception | None = None
    seen_429 = 0
    for attempt in range(settings.http_retries + 1):
        try:
            resp = await client.request(method, url, **kw)
            # 4xx não melhora com retry — exceto 429, que só pede paciência.
            if resp.status_code == 429:
                seen_429 += 1
                if seen_429 <= _MAX_429_RETRIES and attempt < settings.http_retries:
                    await asyncio.sleep(_retry_after(resp, 2.0))
                    continue
                raise httpx.HTTPStatusError(
                    "HTTP 429", request=resp.request, response=resp
                )
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last = exc
            status = exc.response.status_code
            # 429 já dormiu acima; demais 4xx são definitivos.
            if 400 <= status < 500 and status != 429:
                break
            if attempt < settings.http_retries and status != 429:
                await asyncio.sleep(0.6 * (2**attempt))
        except Exception as exc:  # noqa: BLE001 — convertido em FetchError abaixo
            last = exc
            if attempt < settings.http_retries:
                await asyncio.sleep(0.6 * (2**attempt))
    raise FetchError(f"{method} {url}: {type(last).__name__}: {last}") from last


async def get_json(url: str, **kw: Any) -> Any:
    resp = await _request("GET", url, **kw)
    try:
        return resp.json()
    except ValueError as exc:
        snippet = resp.text[:160].replace("\n", " ")
        raise FetchError(f"resposta nao-JSON de {url}: {snippet!r}") from exc


async def post_json(url: str, payload: Any, **kw: Any) -> Any:
    resp = await _request("POST", url, json=payload, **kw)
    try:
        return resp.json()
    except ValueError as exc:
        snippet = resp.text[:160].replace("\n", " ")
        raise FetchError(f"resposta nao-JSON de {url}: {snippet!r}") from exc


async def get_text(url: str, **kw: Any) -> str:
    resp = await _request("GET", url, **kw)
    return resp.text
