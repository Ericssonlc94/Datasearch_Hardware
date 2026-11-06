"""Testes offline da T35 (prices.py + kabum.py): cesta por modelo, sem rede.

Substitui `test_prices_t29.py` (cesta de URLs fixas, K14d por URL).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.cache import Fetched, TTLCache
from app.domain import prices as P
from app.providers import kabum as K

D0 = date(2026, 11, 5)
RTX3050 = P.BASKET_BY_KEY["gpu-rtx-3050"]


def L(code: str, price, **kw) -> P.Listing:
    kw.setdefault("name", "Placa de Vídeo MSI RTX 3050 6GB")
    return P.Listing(code=code, day=D0, price_full=price, **kw)


# --- cesta -----------------------------------------------------------------------


def test_cesta_valida_de_3_a_5_modelos_por_faixa():
    assert P.validate_basket() == []
    for cat in P.BAND_RANGES:
        for band in P.BANDS:
            assert 3 <= len(P.models_for(cat, band)) <= 5, (cat, band)


def test_faixas_exibidas_contiguas_e_abaixo_do_teto():
    for cat, bands in P.BAND_RANGES.items():
        seq = [bands[b] for b in P.BANDS]
        assert all(a[1] == b[0] for a, b in zip(seq, seq[1:])), cat
        assert seq[-1][1] <= P.INCOME_CEILING_BRL


def test_termo_de_busca_limpo():
    for m in P.BASKET:
        url = K.search_url(m)
        assert url.startswith("https://www.kabum.com.br/busca/") and "?" not in url and "&" not in url


def test_termo_fora_do_formato_nao_vira_pedido():
    bad = P.BasketModel("x-baixo-y", "gpu", "baixo", "—", "y", "rtx 3050?sort=1", ("rtx",))
    with pytest.raises(ValueError):
        K.search_url(bad)


def test_rotulo_conta_modelos():
    assert P.PRICE_LABEL == "Preço na KaBuM (preço cheio)"
    assert "110 modelos" in P.PRICE_NOTE.format(models=110)


# --- nome -------------------------------------------------------------------------


@pytest.mark.parametrize("key,name,ok", [
    ("gpu-rtx-3050", "Placa de Vídeo Galax GeForce RTX 3050 EX V2, 6GB", True),
    ("gpu-rtx-3050", "PC Gamer Ryzen 5 5500, RTX 3050, 16gb", False),
    ("gpu-rtx-3050", "Notebook Gamer Lenovo LOQ RTX 3050", False),
    ("gpu-rtx-5060", "Placa de Vídeo Gigabyte RTX5060 Windforce 8G", True),
    ("gpu-rtx-5060", "Placa de Vídeo ASUS RTX 5060 Ti 8GB", False),
    ("gpu-rx-9070", "Placa de Vídeo Sapphire RX 9070 XT 16GB", False),
    ("cpu-r5-5600", "Processador AMD Ryzen 5 5600X", False),
    ("cpu-r5-5600", "Processador AMD Ryzen 5 5600, 3.5GHz", True),
    ("cpu-r7-5700x", "Placa-Mãe MSI B550M + Processador AMD Ryzen 7 5700X", False),
    ("ram-fury-ddr4-8", "Memória RAM Kingston Fury Beast, 8 GB, 3200MHz, DDR4", True),
    ("ram-fury-ddr4-8", "Memória RAM Para Notebook Kingston Fury Beast 8GB DDR4", False),
    ("ram-fury-ddr5-16", "Kit Memória Kingston Fury Beast 16GB DDR5", False),
    ("ram-fury-ddr5-32", "Memória RAM Kingston Fury Beast, 32GB (2x16GB), DDR5, Kit", True),
    ("console-ps5-disco", "Console Sony PlayStation 5 Slim, Leitor de Disco, 1TB", True),
    ("console-ps5-disco", "Tampa para Console PlayStation 5 Slim", False),
    ("console-ps5-disco", "Console PlayStation 5 Slim Edição Digital", False),
    ("motherboard-b650", "Kit Upgrade Ryzen 5 8600G Placa Mãe B650", False),
    ("monitor-27-qhd-165", 'Monitor Gamer Samsung Odyssey G5 27", QHD, 165Hz', True),
    ("monitor-27-qhd-165", 'Monitor Gamer ASUS TUF 27", QHD, 210Hz', False),
    ("smartphone-a07", "Smartphone Samsung Galaxy A07 128GB usado", False),
])
def test_nome_do_anuncio(key, name, ok):
    assert P.match_name(P.BASKET_BY_KEY[key], name) is ok


def test_normaliza_acento_unidade_e_pontuacao():
    assert P.normalize_name("Memória 8 GB, 3200 MHz — Placa-Mãe") == "memoria 8gb 3200mhz placa mae"


# --- anúncio e modelo ------------------------------------------------------------------


def test_preco_cheio_na_busca_e_no_produto():
    busca = P.listing_from_prices("1", D0, {"price": 1111.1, "oldPrice": 1111.1, "priceWithDiscount": 999.99},
                                  flash_offer=True)
    assert busca.price_full == 1111.1 and busca.price_cash is None and busca.flash_price == 999.99
    sem = P.listing_from_prices("1", D0, {"price": 777.77, "priceWithDiscount": 699.99}, flash_offer=False)
    assert sem.price_full == 777.77 and sem.price_cash == 699.99
    produto = P.listing_from_prices("1", D0, {"price": 511.1, "oldPrice": 777.77, "priceWithDiscount": 459.99},
                                    flash_offer=True, page="product")
    assert produto.price_full == 777.77


@pytest.mark.parametrize("listing,reason", [
    (L("1", 2000.0, available=False), "unavailable"),
    (L("1", 2000.0, seller="Loja X"), "seller"),
    (L("1", float("nan")), "invalid"),
    (L("1", 2000.0, price_cash=2500.0), "invalid"),
    (L("1", 9000.0), "out_of_range"),  # acima de 2.500 × 1,25 no baixo da GPU
    (L("1", 1100.0), "out_of_range"),  # abaixo de 1.500 ÷ 1,25
    (L("1", 3100.0), None),
])
def test_anuncio_valido_no_dia(listing, reason):
    assert P.screen_listing(listing, "gpu", band="baixo") == reason


def test_mediana_do_modelo_e_referencias_perto_dela():
    md = P.model_day(RTX3050, [L("1", 1900.0), L("2", 2000.0), L("3", 2100.0), L("4", 2300.0),
                               L("5", 2050.0)], D0)
    assert md.price == 2050.0 and len(md.valid) == 5
    assert [r.code for r in md.refs] == ["5", "2", "3"]  # distância à mediana, depois o code


def test_anormal_sai_da_mediana_nos_dois_sentidos():
    md = P.model_day(RTX3050, [L("1", 1900.0), L("2", 1950.0), L("3", 2000.0), L("4", 3100.0),
                               L("5", 1250.0)], D0)
    assert md.excluded == {"abnormal": 2} and md.price == 1950.0


def test_marketplace_so_sem_kabum_valida():
    kab = P.model_day(RTX3050, [L("1", 2000.0), L("2", 1600.0, seller="Loja X")], D0)
    assert kab.price == 2000.0 and not kab.marketplace and kab.excluded == {"seller": 1}
    mkt = P.model_day(RTX3050, [L("1", 2000.0, available=False), L("2", 1600.0, seller="Loja X")], D0)
    assert mkt.price == 1600.0 and mkt.marketplace


def test_codigo_repetido_conta_uma_vez():
    md = P.model_day(RTX3050, [L("1", 2000.0), L("1", 2000.0), L("2", 2200.0)], D0)
    assert len(md.valid) == 2 and md.price == 2100.0


def test_relampago_e_so_selo():
    md = P.model_day(RTX3050, [L("1", 2000.0, flash_offer=True, flash_price=1700.0)], D0)
    assert md.price == 2000.0 and md.flash and md.cash is None


# --- faixa, variação e categoria -----------------------------------------------------------


def test_faixa_e_media_simples_dos_modelos():
    assert P.band_price({"a": 1000.0, "b": 2000.0, "c": 3000.0}) == 2000.0
    assert P.band_price({}) is None


def test_variacao_pareada_por_modelo():
    hist = {"a": [(D0 - timedelta(days=31), 100.0)], "b": [(D0 - timedelta(days=40), 200.0)],
            "c": [(D0 - timedelta(days=5), 50.0)]}
    # c não tem preço de 30 dias atrás; d é novo. Só a e b entram.
    got = P.band_change({"a": 110.0, "b": 180.0, "c": 60.0, "d": 999.0}, hist, D0)
    assert got == pytest.approx(0.0)  # a +10%, b −10%


def test_variacao_precisa_de_30_dias():
    hist = {"a": [(D0 - timedelta(days=10), 100.0)]}
    assert P.band_change({"a": 120.0}, hist, D0) is None


def test_categoria_so_publica_com_2_de_3_faixas():
    assert P.category_day("gpu", D0, {"baixo": 1.0, "medio": None, "alto": None}).published is False
    assert P.category_day("gpu", D0, {"baixo": 1.0, "medio": 2.0, "alto": None}).published is True


# --- visão --------------------------------------------------------------------------


def _fetched(models, version=P.BASKET_VERSION, day=D0, status="ok"):
    payload = {"cache_version": version, "models": [
        {"key": k, "day": day.isoformat(), "status": "ok", "items": items} for k, items in models.items()]}
    return Fetched(key="kabum.basket", label="", provider="", url="", status=status, payload=payload,
                   as_of=datetime(2026, 11, 5, tzinfo=timezone.utc))


def _row(code, price, name, seller="KaBuM!"):
    return {"code": code, "name": name, "price_full": price, "price_cash": price * 0.9,
            "flash_offer": False, "flash_price": None, "available": True, "seller": seller}


def test_visao_por_modelo_com_referencias_e_link_pelo_code():
    f = _fetched({
        "gpu-rtx-3050": [_row("11", 2000.0, "Placa de Vídeo RTX 3050"), _row("12", 2100.0, "Placa de Vídeo RTX 3050")],
        "gpu-rx-6600": [_row("21", 2400.0, "Placa de Vídeo RX 6600 8GB")],
        "gpu-rtx-5060": [_row("31", 3000.0, "Placa de Vídeo RTX 5060")],
    })
    view = P.build_prices_view({"kabum.basket": f}, {}, D0)
    gpu = view["categories"][0]
    baixo = gpu["tiers"][0]
    assert baixo["price_full_brl"] == pytest.approx((2050.0 + 2400.0) / 2)
    assert baixo["listings"] == {"tracked": 4, "valid": 2, "unit": "models"}
    assert {"code": "partial", "text": "2 de 4 modelos"} in baixo["warnings"]
    m = next(x for x in baixo["models"] if x["key"] == "gpu-rtx-3050")
    assert m["price_full_brl"] == 2050.0 and m["listings"] == {"found": 2, "valid": 2}
    assert all(r["url"] == f"https://www.kabum.com.br/produto/{r['code']}" for r in m["refs"])
    assert gpu["published"] is True
    bv = view["brand_view"]["tiers"][0]
    assert bv["nvidia"]["price_full_brl"] == 2050.0 and bv["amd"]["price_full_brl"] == 2400.0
    assert view["series_values"]["kabum_model.gpu-rtx-3050"] == 2050.0


def test_nome_errado_no_payload_nao_entra():
    f = _fetched({"gpu-rtx-3050": [_row("11", 2000.0, "PC Gamer RTX 3050")]})
    tier = P.build_prices_view({"kabum.basket": f}, {}, D0)["categories"][0]["tiers"][0]
    assert tier["price_full_brl"] is None


def test_coleta_de_outra_cesta_ou_outro_dia_nao_vira_preco():
    old = _fetched({"gpu-rtx-3050": [_row("11", 2000.0, "Placa de Vídeo RTX 3050")]}, version="t33")
    view = P.build_prices_view({"kabum.basket": old}, {}, D0)
    assert view["categories"][0]["tiers"][0]["price_full_brl"] is None
    assert "outra versão" in view["source"]["status_reason"]
    velha = _fetched({"gpu-rtx-3050": [_row("11", 2000.0, "Placa de Vídeo RTX 3050")]},
                     day=D0 - timedelta(days=9))
    assert P.build_prices_view({"kabum.basket": velha}, {}, D0)["categories"][0]["tiers"][0]["price_full_brl"] is None
    stale = _fetched({"gpu-rtx-3050": [_row("11", 2000.0, "Placa de Vídeo RTX 3050")]}, status="stale")
    assert P.build_prices_view({"kabum.basket": stale}, {}, D0)["categories"][0]["tiers"][0]["price_full_brl"] is None


def test_coleta_da_semana_vale_e_busca_vazia_e_sem_preco():
    f = _fetched({"gpu-rtx-3050": [_row("11", 2000.0, "Placa de Vídeo RTX 3050")]}, day=D0 - timedelta(days=6))
    f.payload["models"].append({"key": "gpu-rx-6600", "day": D0.isoformat(), "status": "empty"})
    tier = P.build_prices_view({"kabum.basket": f}, {}, D0)["categories"][0]["tiers"][0]
    assert tier["price_full_brl"] == 2000.0
    assert next(m for m in tier["models"] if m["key"] == "gpu-rx-6600")["status"] == "no_price"


def test_variacao_na_visao_usa_o_historico_do_modelo():
    f = _fetched({"gpu-rtx-3050": [_row("11", 2200.0, "Placa de Vídeo RTX 3050")]})
    hist = {"kabum_model.gpu-rtx-3050": [(D0 - timedelta(days=30), 2000.0)]}
    tier = P.build_prices_view({"kabum.basket": f}, {}, D0, model_history=hist)["categories"][0]["tiers"][0]
    assert tier["change_30d_pct"] == pytest.approx(10.0)


# --- cache ----------------------------------------------------------------------------


def test_cache_com_outra_versao_conta_como_vencido():
    cache = TTLCache()
    calls = []

    async def fetch(version):
        calls.append(version)
        return Fetched(key="k", label="", provider="", url="", status="ok", payload={"cache_version": version})

    async def run():
        await cache.get_or_fetch("k", 3600, lambda: fetch("v1"), version="v1")
        await cache.get_or_fetch("k", 3600, lambda: fetch("v1"), version="v1")
        await cache.get_or_fetch("k", 3600, lambda: fetch("v2"), version="v2")

    asyncio.run(run())
    assert calls == ["v1", "v2"]


# --- provider (sem rede) ------------------------------------------------------------------


def _search_html(items):
    data = {"props": {"pageProps": {"data": {"catalogServer": {"data": items}}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_busca_le_itens_e_filtra_pelo_nome():
    items = [
        {"code": 1, "name": "Placa de Vídeo MSI RTX 3050 6GB", "sellerName": "KaBuM!", "price": 2000.0,
         "priceWithDiscount": 1800.0, "available": True, "offer": False},
        {"code": 2, "name": "PC Gamer RTX 3050", "sellerName": "KaBuM!", "price": 5000.0, "available": True},
        {"code": True, "name": "Placa de Vídeo RTX 3050", "price": 1.0},
        "lixo",
    ]
    total, rows = K.parse_search(_search_html(items), RTX3050, D0)
    assert total == 4 and [r["code"] for r in rows] == ["1"]
    assert rows[0]["price_full"] == 2000.0 and rows[0]["price_cash"] == 1800.0


EMPTY_HTML = '<html><script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {}}}</script></html>'


def test_busca_sem_lista_e_sem_anuncio_e_sem_next_data_e_layout_mudou():
    assert K.parse_search(EMPTY_HTML, RTX3050, D0) == (None, [])
    with pytest.raises(K.StoreBlocked):
        K.parse_search("<html></html>", RTX3050, D0)
    with pytest.raises(K.StoreBlocked):  # lista que não é lista
        K.parse_search(_search_html({"x": 1}), RTX3050, D0)


def test_coleta_nao_segue_redirect_e_para_no_desafio(monkeypatch):
    robots = "User-agent: *\nAllow: /busca/\nDisallow: /*?\n"
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if request.url.path.endswith("rtx-3050"):
            return httpx.Response(200, html=_search_html([
                {"code": 1, "name": "Placa de Vídeo RTX 3050", "sellerName": "KaBuM!", "price": 2000.0,
                 "available": True}]))
        if request.url.path.endswith("rx-6600"):
            return httpx.Response(308, headers={"location": "/hardware"})
        if request.url.path.endswith("rtx-3060"):
            return httpx.Response(200, html=EMPTY_HTML)
        return httpx.Response(403, html="<title>Just a moment...</title>")

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(K.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))

    async def no_sleep(_):
        return None

    basket = P.models_for("gpu", "baixo")[:3] + P.models_for("gpu", "medio")[:2]
    got = asyncio.run(K.fetch_basket(basket=basket, sleep=no_sleep))
    status = [r["status"] for r in got.payload["models"]]
    assert status == ["ok", "redirect", "empty", "not_run", "not_run"]
    assert got.payload["cache_version"] == P.BASKET_VERSION and got.payload["stopped"]
    assert seen == ["/robots.txt", "/busca/rtx-3050", "/busca/rx-6600", "/busca/rtx-3060",
                    "/busca/rtx-5060"]


def test_tres_buscas_seguidas_sem_lista_param_a_coleta(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, html=EMPTY_HTML)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(K.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))

    async def no_sleep(_):
        return None

    with pytest.raises(K.StoreBlocked):
        asyncio.run(K.fetch_basket(basket=P.models_for("gpu", "medio")[:4], sleep=no_sleep))
