"""KaBuM — preço cheio dos modelos da cesta, 1 busca por modelo (T35).

Política de coleta (`docs/agentes/seguranca.md` §T26, regras K3–K21, com a K5
trocada na T35 com aprovação do usuário), toda aplicada aqui e não no cliente
HTTP compartilhado:

* só `GET /busca/<termo>` no ciclo, com o termo limpo da cesta
  (`domain.prices.BASKET`): sem "?", sem ordenação, sem página 2 — o robots
  permite o caminho limpo e proíbe os parâmetros (K5, T35);
* `robots.txt` relido a cada coleta, antes de qualquer busca (K6): 4xx →
  pode coletar; 5xx, timeout ou desafio → não coleta; caminho proibido ou
  bloco anti-IA → a fonte para (RFC 9309);
* em série, 3–5 s entre pedidos, sem retentativa (K4), sem seguir
  redirecionamento (K20) e sem cookies (K21). O teto de pedidos por coleta é
  `MAX_REQUESTS` (K3: 40/dia até a T33b; a rodada da T35 liberou a cesta
  inteira de uma vez, e a divisão em vários dias fica para depois);
* corpo até 5 MB, `__NEXT_DATA__` até 4 MB, extraído com `html.parser` (K11,
  K12); JSON sem NaN/Infinity, com `RecursionError` tratado (K10); cada nível
  do JSON conferido por tipo (K13); preço só número ou texto `1234.56` (K14a);
  nome e vendedor sem caracteres de controle/bidi, até 160 caracteres (K15).
* o payload guarda só o necessário (K8): por modelo, os anúncios cujo nome
  casa com o modelo, com code, preços, disponibilidade, vendedor e nome
  curto. O link é montado depois a partir do `code` (K16).

Desafio antirrobô (K19): status 403/429/503 com HTML, `cf-mitigated:
challenge` ou título "Just a moment"/"Attention Required". Uma página 200 sem
`__NEXT_DATA__` é "layout mudou", não desafio. Nos dois casos a coleta para.

Preço cheio na busca: `price` (igual ao `oldPrice` da página de produto em
oferta). A regra mora em `domain.prices.listing_from_prices`.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import unicodedata
import urllib.robotparser
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

import httpx

from ..cache import Fetched
from ..config import settings
from ..domain import prices as P
from ..http import FetchError, ResponseTooLarge, _send_capped, parse_retry_after

BASE = "https://www.kabum.com.br"
# K3: teto de buscas por coleta. A T35 liberou a cesta inteira nesta rodada.
MAX_REQUESTS = 140
MAX_ITEMS_PER_PAGE = 120  # itens lidos por busca (a página traz ~60)
# Buscas seguidas sem lista que indicam layout mudado, não falta de anúncio.
MAX_EMPTY_IN_A_ROW = 3
SPACING_S = (3.0, 5.0)  # K3: pausa entre pedidos, sorteada no intervalo
MAX_PAGE_BYTES = 5 * 1024 * 1024  # K11
MAX_NEXT_DATA_CHARS = 4 * 1024 * 1024  # K11
MAX_ROBOTS_BYTES = 512 * 1024
TIMEOUT_S = 20.0
TOTAL_TIMEOUT_S = 40.0
NAME_MAX = 160  # K15

_CODE_RE = re.compile(r"^\d{1,10}$")
_PRICE_TEXT_RE = re.compile(r"^\d{1,6}(\.\d{1,2})?$")
# K6(b): grupo de robots que nomeia agente de IA indica que o site não quer
# coleta automatizada desse tipo; a fonte para e o painel avisa.
_AI_AGENTS = ("gptbot", "chatgpt-user", "claudebot", "claude-user", "anthropic-ai", "perplexitybot")


class StoreBlocked(FetchError):
    """Desafio, bloqueio, robots proibindo ou layout mudado: a coleta para."""


# --- texto e números (K10, K13, K14a, K15) ----------------------------------------


def clean_text(value: Any, limit: int = NAME_MAX) -> str | None:
    """Sem `Cc`/`Cf` (inclui bidi), espaços compactados, até `limit` caracteres."""
    if not isinstance(value, str):
        return None
    kept = "".join(" " if ch.isspace() else ch for ch in value
                   if ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf"))
    kept = " ".join(kept.split())
    return kept[:limit] or None


def parse_price(value: Any) -> float | None:
    """Número finito > 0 (sem `bool`) ou texto `1234.56`; nunca "1.199,00"."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and _PRICE_TEXT_RE.match(value.strip()):
        try:
            number = float(Decimal(value.strip()))
        except InvalidOperation:
            return None
    else:
        return None
    return number if number > 0 and number == number and number != float("inf") else None


def _reject_constant(name: str) -> None:
    raise ValueError(f"constante JSON não aceita: {name}")


def loads_strict(text: str) -> Any:
    """`json.loads` sem NaN/Infinity; erro de parse vira `StoreBlocked`."""
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise StoreBlocked(f"JSON da página ilegível: {type(exc).__name__}") from exc


def get_path(obj: Any, *keys: str) -> Any:
    """Desce `obj` pelas chaves conferindo `dict` a cada passo; `None` se faltar."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


# --- HTML (K12) -----------------------------------------------------------------


class _ScriptGrabber(HTMLParser):
    """Guarda o conteúdo de `<script id="__NEXT_DATA__">`, e só ele."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.next_data: str | None = None
        self.title = ""
        self._in_next = False
        self._in_title = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__" and self.next_data is None:
            self._in_next, self._chunks = True, []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_next:
            self._in_next = False
            self.next_data = "".join(self._chunks)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_next:
            self._chunks.append(data)
            if sum(len(c) for c in self._chunks) > MAX_NEXT_DATA_CHARS:
                raise StoreBlocked("__NEXT_DATA__ acima de 4 MB")
        elif self._in_title and len(self.title) < 200:
            self.title += data


def extract_next_data(html: str) -> tuple[str | None, str]:
    grabber = _ScriptGrabber()
    grabber.feed(html)
    grabber.close()
    return grabber.next_data, grabber.title.strip().lower()


def is_challenge(resp: httpx.Response, title: str = "") -> bool:
    """K19: desafio só por status+HTML, header do Cloudflare ou título conhecido."""
    html = "text/html" in resp.headers.get("content-type", "").lower()
    if resp.status_code in (403, 429, 503) and html:
        return True
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    return title.startswith(("just a moment", "attention required"))


# --- página de busca -------------------------------------------------------------------


def parse_search(html: str, model: "P.BasketModel", day: Any) -> tuple[int | None, list[dict]]:
    """(itens na página, anúncios cujo nome casa com o modelo) da `/busca`.

    Página com `__NEXT_DATA__` mas sem `catalogServer.data` é busca sem
    resultado (T35c): devolve `(None, [])` e a coleta segue. Sem
    `__NEXT_DATA__` nenhum, o layout mudou e a coleta para.
    """
    next_data, _ = extract_next_data(html)
    if next_data is None:
        raise StoreBlocked(f"busca {model.term}: página sem __NEXT_DATA__ (layout mudou)")
    data = loads_strict(next_data)
    items = get_path(data, "props", "pageProps", "data", "catalogServer", "data")
    if items is None:
        return None, []
    if not isinstance(items, list):
        raise StoreBlocked(f"busca {model.term}: catalogServer.data não é lista (layout mudou)")
    rows: list[dict] = []
    for item in items[:MAX_ITEMS_PER_PAGE]:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        code = str(code) if isinstance(code, (int, str)) and not isinstance(code, bool) else ""
        name = clean_text(item.get("name"))
        if not _CODE_RE.match(code) or not P.match_name(model, name):
            continue
        offer = item.get("offer")
        listing = P.listing_from_prices(
            code, day, {k: v for k in ("price", "oldPrice", "priceWithDiscount")
                        if (v := parse_price(item.get(k))) is not None},
            flash_offer=bool(offer) and isinstance(offer, (bool, dict)),
            available=item.get("available") is True,
            seller=clean_text(item.get("sellerName"), 60),
            name=name,
        )
        rows.append({
            "code": code,
            "name": name,
            "price_full": listing.price_full,
            "price_cash": listing.price_cash,
            "flash_offer": listing.flash_offer,
            "flash_price": listing.flash_price,
            "available": listing.available,
            "seller": listing.seller,
        })
    return len(items), rows


# --- coleta ------------------------------------------------------------------------------


async def _get(client: httpx.AsyncClient, url: str, max_bytes: int) -> httpx.Response:
    """Um pedido, sem retentativa, sem redirect seguido e sem guardar cookie."""
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_S):
            resp = await _send_capped(client, "GET", url, max_bytes)
    except ResponseTooLarge:
        raise
    except TimeoutError as exc:
        raise FetchError(f"GET {url}: tempo total de {TOTAL_TIMEOUT_S:.0f}s esgotado") from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"GET {url}: {type(exc).__name__}") from exc
    finally:
        client.cookies.clear()
    return resp


def _blocked(resp: httpx.Response, url: str, what: str) -> StoreBlocked:
    wait = parse_retry_after(resp.headers.get("Retry-After"))
    return StoreBlocked(f"{what}: HTTP {resp.status_code} em {url}", status_code=resp.status_code, retry_after=wait)


async def read_robots(client: httpx.AsyncClient) -> urllib.robotparser.RobotFileParser:
    """K6 / RFC 9309: 4xx libera, 5xx/timeout/desafio bloqueia o dia."""
    url = BASE + "/robots.txt"
    resp = await _get(client, url, MAX_ROBOTS_BYTES)
    rp = urllib.robotparser.RobotFileParser()
    if is_challenge(resp) or resp.status_code >= 500:
        raise _blocked(resp, url, "robots.txt indisponível ou com desafio")
    if 300 <= resp.status_code < 400:
        raise StoreBlocked(f"robots.txt redirecionado para {clean_text(resp.headers.get('location'), 120)}")
    if 400 <= resp.status_code < 500:
        rp.parse([])  # robots ausente: tudo permitido
        return rp
    lines = resp.text.splitlines()
    agents = {line.split(":", 1)[1].strip().lower() for line in lines if line.lower().startswith("user-agent:")}
    if agents & set(_AI_AGENTS):
        raise StoreBlocked("robots.txt passou a ter bloco anti-IA; fonte desligada até revisão (K6)")
    rp.parse(lines)
    if not rp.can_fetch(settings.user_agent, BASE + "/busca/x"):
        raise StoreBlocked("robots.txt passou a proibir /busca/ (K6)")
    return rp


def search_url(model: "P.BasketModel") -> str:
    """`/busca/<termo>` limpo; termo fora do formato não vira pedido."""
    if not P._TERM_RE.match(model.term):
        raise ValueError(f"termo fora do formato: {model.key}")
    return f"{BASE}/busca/{model.term}"


async def fetch_basket(*, basket: list | None = None, sleep=asyncio.sleep) -> Fetched:
    """Coleta a cesta inteira: robots e depois uma busca por modelo, em série."""
    models = list(basket if basket is not None else P.BASKET)[:MAX_REQUESTS]
    day = datetime.now(timezone.utc).date()
    rows: list[dict] = []
    stopped: str | None = None
    empty_run = 0
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html", "Accept-Language": "pt-BR"}
    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT_S, follow_redirects=False) as client:
        robots = await read_robots(client)
        for model in models:
            base = {"key": model.key, "term": model.term, "day": day.isoformat(),
                    "category": model.category, "band": model.band}
            if stopped:
                rows.append({**base, "status": "not_run", "reason": "coleta parada antes"})
                continue
            url = search_url(model)
            if not robots.can_fetch(settings.user_agent, url):
                rows.append({**base, "status": "robots", "reason": "robots proíbe"})
                continue
            await sleep(random.uniform(*SPACING_S))
            try:
                resp = await _get(client, url, MAX_PAGE_BYTES)
                if 300 <= resp.status_code < 400:
                    rows.append({**base, "status": "redirect",
                                 "reason": f"redirecionado (HTTP {resp.status_code}), não seguido"})
                    continue
                if resp.status_code == 404:
                    rows.append({**base, "status": "not_found", "reason": "busca não encontrada (404)"})
                    continue
                _, title = extract_next_data(resp.text[:8192]) if resp.status_code != 200 else ("", "")
                if is_challenge(resp, title) or resp.status_code != 200:
                    raise _blocked(resp, url, "bloqueio ou desafio")
                total, items = parse_search(resp.text, model, day)
                if total is None:
                    empty_run += 1
                    if empty_run >= MAX_EMPTY_IN_A_ROW:
                        raise StoreBlocked(f"{empty_run} buscas seguidas sem lista (layout mudou?)")
                    rows.append({**base, "status": "empty", "reason": "busca sem lista de anúncios"})
                    continue
                empty_run = 0
            except StoreBlocked as exc:
                stopped = str(exc)
                if not any(r["status"] == "ok" for r in rows):
                    raise
                rows.append({**base, "status": "not_run", "reason": "coleta parada aqui"})
                continue
            except FetchError as exc:  # rede/timeout de uma busca: segue sem repetir
                rows.append({**base, "status": "error", "reason": str(exc)[:160]})
                continue
            rows.append({**base, "status": "ok", "page_items": total, "items": items})
    ok = sum(1 for r in rows if r["status"] == "ok")
    if not ok:
        first = next((r.get("reason") for r in rows if r.get("reason")), None)
        raise FetchError("KaBuM: nenhuma busca lida" + (f" ({first})" if first else ""))
    note = f"{ok} de {len(models)} buscas lidas; só /busca limpa, em série, sem retentativa."
    if stopped:
        note += f" Coleta parada no 1º bloqueio: {stopped}"
    return Fetched(
        key="kabum.basket",
        label="KaBuM — preço cheio dos modelos da cesta",
        provider="KaBuM (busca pública)",
        url=BASE,
        status="ok",
        payload={
            # Cesta nova = coleta vencida (T35): o cache e o domínio conferem.
            "cache_version": P.BASKET_VERSION,
            "models": rows,
            "stopped": stopped,
        },
        as_of=datetime.now(timezone.utc),
        note=note,
    )
