"""Cliente HTTP compartilhado com retry e tratamento uniforme de erro."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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


# Teto do corpo já descomprimido. A maior resposta legítima do projeto (SEC
# companyconcept, CSV longo do FRED) fica bem abaixo; um feed invadido ou um
# redirecionamento para um arquivo enorme não chega a esgotar a memória.
MAX_BODY_BYTES = 20 * 1024 * 1024

# As URLs são fixas; mais do que isso é laço ou desvio, não fonte legítima.
_MAX_REDIRECTS = 5


def build_client(**kw: Any) -> httpx.AsyncClient:
    """Cliente com as defesas do projeto; `kw` permite um transporte de teste."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout),
        headers=_headers(),
        follow_redirects=True,
        max_redirects=_MAX_REDIRECTS,
        event_hooks={"response": [check_redirect]},
        limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        **kw,
    )


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = build_client()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class FetchError(RuntimeError):
    """Falha definitiva ao buscar um recurso externo.

    A mensagem leva só método, URL, status e tipo do erro, porque chega ao
    painel e ao `/api/health`. O trecho do corpo da resposta é conteúdo de
    terceiro: fica em `body_snippet`, para log e depuração, fora da mensagem.
    """

    def __init__(
        self,
        message: str,
        *,
        body_snippet: str = "",
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.body_snippet = body_snippet
        # Status HTTP final e `Retry-After` sem teto: o provider decide se é
        # cota esgotada e por quanto tempo parar (ver comtrade.py).
        self.status_code = status_code
        self.retry_after = retry_after


class RedirectRefused(FetchError):
    """Redirecionamento para fora de `https` ou para a rede interna."""


class ResponseTooLarge(FetchError):
    """Corpo da resposta acima do teto: falha visível, nada vai para o cache."""


class ChallengeDetected(FetchError):
    """A fonte respondeu com interstitial anti-bot (captcha ou JS challenge).

    Política do projeto: não contornamos. Detectar é o comportamento correto —
    o provider falha, o cache serve `stale` e a fonte aparece degradada.
    """


# Marcadores vistos em páginas de bloqueio. Comparados em minúsculas contra o
# início do corpo — não vale a pena varrer megabytes de HTML legítimo.
_CHALLENGE_MARKERS = (
    "captcha",
    "just a moment",
    "cf-chl",
    "requires javascript",
    "attention required",
    "checking your browser",
    "enable javascript and cookies",
    "access denied",
)

_CHALLENGE_SCAN = 4096


def reject_challenge(text: str, *, url: str = "") -> None:
    """Levanta `ChallengeDetected` se o corpo parecer uma página anti-bot."""
    sample = (text or "")[:_CHALLENGE_SCAN].lower()
    for marker in _CHALLENGE_MARKERS:
        if marker in sample:
            where = url or "resposta"
            raise ChallengeDetected(f"desafio anti-bot em {where} (marcador {marker!r})")


def _looks_html(resp: httpx.Response) -> bool:
    return "text/html" in resp.headers.get("content-type", "").lower()


def _is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _host_is_internal(host: str) -> bool:
    try:
        return _is_internal_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except OSError:
        # Não resolve: a própria conexão vai falhar, e a falha já é visível.
        return False
    return any(_is_internal_ip(ipaddress.ip_address(info[4][0])) for info in infos)


async def check_redirect(resp: httpx.Response) -> None:
    """Hook de resposta: só segue redirecionamento para `https` público.

    As URLs das fontes são fixas, então um desvio para `http://` ou para
    127.0.0.1, 192.168.x ou 169.254.169.254 só acontece com a fonte
    comprometida — e aí o app não deve consultar a rede interna por ela.
    """
    if not resp.has_redirect_location:
        return
    target = resp.request.url.join(resp.headers["location"])
    origin = resp.request.url.host
    if target.scheme != "https":
        raise RedirectRefused(
            f"redirecionamento recusado: {origin} -> {target.scheme}://{target.host}"
        )
    if await _host_is_internal(target.host):
        raise RedirectRefused(
            f"redirecionamento recusado: {origin} -> {target.host} (rede interna)"
        )


_limiters: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]] = {}


def limiter(name: str, concurrency: int) -> asyncio.Semaphore:
    """Semáforo nomeado para não estourar o limite de taxa de um provedor.

    Comex Stat e UN Comtrade devolvem 429 quando recebem uma rajada paralela.
    Coletar essas fontes em fila é mais rápido do que apanhar do rate limit.

    O semáforo fica preso ao event loop que o criou: `asyncio.Semaphore`
    levanta `RuntimeError` se for disputado a partir de outro loop. Por isso
    um loop novo (um `asyncio.run` por teste, por exemplo) ganha semáforo
    novo em vez de herdar um que já não pode ser usado.
    """
    loop = asyncio.get_running_loop()
    current = _limiters.get(name)
    if current is not None and current[0] is loop:
        sem = current[1]
        if sem._value <= concurrency:  # noqa: SLF001
            return sem
    sem = asyncio.Semaphore(concurrency)
    _limiters[name] = (loop, sem)
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
        restante = int(max(0.0, b.open_until - time.monotonic()))
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
        # Prazo infinito ou NaN deixaria o disjuntor aberto até reiniciar.
        if not math.isfinite(cooldown) or cooldown < 0:
            cooldown = 900.0
        b.open_until = time.monotonic() + cooldown


# Teto de qualquer `Retry-After` que o app aceite obedecer.
RETRY_AFTER_MAX_S = 6 * 60 * 60


def parse_retry_after(raw: str | None) -> float | None:
    """`Retry-After` em segundos, finito e em [0, 6 h]; `None` se ilegível.

    Aceita os dois formatos da RFC 9110 (segundos ou data HTTP). O valor vem
    de terceiro: "inf", "1e400" ou "nan" virariam disjuntor aberto para sempre
    ou um timer com prazo indefinido no event loop.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
    if not math.isfinite(seconds):
        return None
    return min(max(seconds, 0.0), float(RETRY_AFTER_MAX_S))


def _retry_after(resp: httpx.Response, fallback: float) -> float:
    seconds = parse_retry_after(resp.headers.get("Retry-After"))
    return fallback if seconds is None else min(seconds, 30.0)


# Insistir em 429 só piora: o provedor já disse que estamos rápido demais.
# Uma retentativa e seguimos — o cache serve o último valor bom enquanto isso.
_MAX_429_RETRIES = 1


async def _read_capped(resp: httpx.Response, max_bytes: int) -> httpx.Response:
    """Lê o corpo em pedaços e aborta acima de `max_bytes`."""
    where = resp.request.url.copy_with(query=None)
    declared = resp.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise ResponseTooLarge(f"{where}: Content-Length {declared} acima do teto de {max_bytes} bytes")
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLarge(f"{where}: corpo acima do teto de {max_bytes} bytes")
        chunks.append(chunk)
    # O corpo já saiu descomprimido; os cabeçalhos de codificação e tamanho
    # descreviam o original e fariam o httpx tentar descomprimir de novo.
    headers = [
        (k, v)
        for k, v in resp.headers.multi_items()
        if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
    ]
    return httpx.Response(
        resp.status_code,
        headers=headers,
        content=b"".join(chunks),
        request=resp.request,
        history=resp.history,
    )


async def _send_capped(
    client: httpx.AsyncClient, method: str, url: str, max_bytes: int, **kw: Any
) -> httpx.Response:
    request = client.build_request(method, url, **kw)
    resp = await client.send(request, stream=True)
    try:
        return await _read_capped(resp, max_bytes)
    finally:
        await resp.aclose()


def _total_timeout(kw: dict[str, Any]) -> float:
    """Teto do pedido inteiro: o `httpx.Timeout` limita cada fase, não a soma.

    Sem isso, um servidor que manda um byte a cada 19 s prende a conexão
    indefinidamente, ocupando vaga do pool e do semáforo da fonte.
    """
    phase = kw.get("timeout")
    if not isinstance(phase, (int, float)):
        phase = settings.http_timeout
    return 2.0 * float(phase)


async def _request(
    method: str,
    url: str,
    *,
    max_bytes: int = MAX_BODY_BYTES,
    provider: str | None = None,
    **kw: Any,
) -> httpx.Response:
    """`provider` escolhe o teto de tempo e se tempo esgotado merece retry.

    Fonte lenta e de cota curta (Comtrade: ~18 s por pedido) ganha teto maior
    e nenhuma repetição em tempo esgotado: repetir só gastaria mais cota e
    seguraria a vaga do semáforo por minutos (T43b, config `DSH_HTTP_*`).
    """
    if provider is not None and "timeout" not in kw:
        kw["timeout"] = settings.http_timeout_for(provider)
    retry_on_timeout = provider is None or settings.retries_on_timeout_for(provider)
    client = await get_client()
    total = _total_timeout(kw)
    last: Exception | None = None
    seen_429 = 0
    for attempt in range(settings.http_retries + 1):
        try:
            async with asyncio.timeout(total):
                resp = await _send_capped(client, method, url, max_bytes, **kw)
            # Bloqueio anti-bot: não é erro transitório, não adianta repetir.
            if resp.status_code in (403, 429, 503) and _looks_html(resp):
                reject_challenge(resp.text, url=url)
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
        except (ChallengeDetected, RedirectRefused, ResponseTooLarge):
            # Definitivos: repetir traria o mesmo bloqueio, desvio ou arquivo.
            raise
        except TimeoutError:
            last = TimeoutError(f"tempo total de {total:.0f}s esgotado")
            if not retry_on_timeout:
                break
            if attempt < settings.http_retries:
                await asyncio.sleep(0.6 * (2**attempt))
        except httpx.TimeoutException as exc:
            # Tempo esgotado numa fase (conexão, leitura): mesma regra acima.
            last = exc
            if not retry_on_timeout:
                break
            if attempt < settings.http_retries:
                await asyncio.sleep(0.6 * (2**attempt))
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
    status_code = retry_after = None
    if isinstance(last, httpx.HTTPStatusError):
        status_code = last.response.status_code
        retry_after = parse_retry_after(last.response.headers.get("Retry-After"))
    raise FetchError(
        f"{method} {url}: {type(last).__name__}: {last}",
        status_code=status_code,
        retry_after=retry_after,
    ) from last


def _decode_json(resp: httpx.Response, url: str) -> Any:
    # HTML onde se esperava JSON é quase sempre página de bloqueio — e mesmo
    # quando não é, gravar HTML no cache como dado seria pior do que falhar.
    if _looks_html(resp):
        reject_challenge(resp.text, url=url)
        raise FetchError(
            f"resposta HTML onde se esperava JSON de {url} (HTTP {resp.status_code})",
            body_snippet=resp.text[:160],
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise FetchError(
            f"resposta nao-JSON de {url} (HTTP {resp.status_code})",
            body_snippet=resp.text[:160],
        ) from exc


async def get_json(url: str, **kw: Any) -> Any:
    resp = await _request("GET", url, **kw)
    return _decode_json(resp, url)


async def post_json(url: str, payload: Any, **kw: Any) -> Any:
    resp = await _request("POST", url, json=payload, **kw)
    return _decode_json(resp, url)


async def get_text(url: str, *, max_bytes: int = MAX_BODY_BYTES, **kw: Any) -> str:
    resp = await _request("GET", url, max_bytes=max_bytes, **kw)
    reject_challenge(resp.text, url=url)
    return resp.text
