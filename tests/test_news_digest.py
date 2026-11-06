"""Digest de notícias — testes offline, sem rede.

O objetivo do módulo não é "detectar fake news" (isso não existe), e sim:
descartar release/agregador, deduplicar republicação, contar corroboração por
domínio distinto e fechar o conjunto com um digest auditável.
"""

from __future__ import annotations

import asyncio

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import news  # noqa: E402


def _art(
    title: str,
    url: str,
    domain: str,
    seen: str = "2026-11-03T12:00:00+00:00",
    language: str | None = "en",
) -> dict:
    return {"title": title, "url": url, "domain": domain, "seen_at": seen,
            "country": "US", "language": language}


def test_base_domain_e_tier():
    assert news.base_domain("WWW.Reuters.com.") == "reuters.com"
    assert news.domain_tier("www.reuters.com") == "wire"
    assert news.domain_tier("apnews.com") == "wire"
    assert news.domain_tier("valor.globo.com") == "br"
    assert news.domain_tier("tomshardware.com") == "trade"
    assert news.domain_tier("prnewswire.com") == "blocked"
    assert news.domain_tier("news.google.com") == "blocked"
    assert news.domain_tier("blog-exemplo.xyz") == "unknown"


def test_normaliza_idioma_para_en_pt_es():
    assert news.language_code("English") == "en"
    assert news.language_code("en-US") == "en"
    assert news.language_code("Portuguese") == "pt"
    assert news.language_code("pt_BR") == "pt"
    assert news.language_code("Spanish") == "es"
    assert news.language_code("es-419") == "es"
    assert news.language_code("French") is None
    assert news.language_code("") is None
    assert news.language_code(None) is None


def test_descarta_noticia_fora_de_ingles_portugues_espanhol():
    items, _, stats = news.build_digest([
        _art("Nvidia GPU prices climb", "https://a.com/1", "a.com", language="en"),
        _art("Preços de GPU sobem no Brasil", "https://b.com/2", "b.com", language="pt-BR"),
        _art("Precios de GPU suben en España", "https://c.com/3", "c.com", language="Spanish"),
        _art("Les prix des GPU augmentent", "https://d.com/4", "d.com", language="fr"),
        _art("GPU-Preise steigen", "https://e.com/5", "e.com", language=None),
    ])
    assert {item["language"] for item in items} == {"en", "pt", "es"}
    assert stats["language"] == 2
    assert stats["kept"] == 3


def test_canonical_url_remove_rastreio_e_fragmento():
    a = news.canonical_url("https://www.reuters.com/tech/chips/?utm_source=x&id=1#top")
    b = news.canonical_url("https://reuters.com/tech/chips?id=1")
    assert a == b == "https://reuters.com/tech/chips?id=1"


def test_deduplica_mesma_url_com_rastreio_diferente():
    items, digest, stats = news.build_digest([
        _art("Chip shortage hits GPU prices", "https://exemplo.com/a?utm_source=x", "exemplo.com"),
        _art("Chip shortage hits GPU prices", "https://www.exemplo.com/a/", "exemplo.com"),
    ])
    assert len(items) == 1
    assert stats["duplicate"] == 1
    assert digest


def test_agrupa_mesma_historia_em_veiculos_distintos_e_corrobora():
    items, _, stats = news.build_digest([
        _art("China tightens rare earth export controls",
             "https://reuters.com/a", "reuters.com"),
        _art("China tightens export controls on rare earths",
             "https://ft.com/b", "ft.com"),
        _art("Nvidia raises GPU prices as memory costs climb",
             "https://cnbc.com/c", "cnbc.com"),
    ])
    assert stats["kept"] == 2
    rare = next(i for i in items if "rare earth" in i["title"].lower())
    assert rare["corroboration"] == 2
    assert rare["confidence"] == "corroborated"
    assert rare["sources"] == ["ft.com", "reuters.com"]
    nvidia = next(i for i in items if "nvidia" in i["title"].lower())
    assert nvidia["confidence"] == "single-source"


def test_descarta_release_e_agregador():
    items, _, stats = news.build_digest([
        _art("Company announces new fab", "https://prnewswire.com/x", "prnewswire.com"),
        _art("Chip news roundup", "https://news.google.com/y", "news.google.com"),
        _art("Memory chip prices surge on AI demand", "https://reuters.com/z", "reuters.com"),
    ])
    assert [i["domain"] for i in items] == ["reuters.com"]
    assert stats["blocked"] == 2


def test_digest_estavel_para_o_mesmo_conjunto_em_ordem_diferente():
    a = _art("Rare earth prices climb", "https://reuters.com/a", "reuters.com")
    b = _art("Copper hits record high", "https://ft.com/b", "ft.com")
    c = _art("Helium supply tightens", "https://cnbc.com/c", "cnbc.com")
    _, d1, _ = news.build_digest([a, b, c])
    _, d2, _ = news.build_digest([c, a, b])
    assert d1 == d2


def test_digest_muda_quando_o_conjunto_muda():
    a = _art("Rare earth prices climb", "https://reuters.com/a", "reuters.com")
    _, d1, _ = news.build_digest([a])
    _, d2, _ = news.build_digest([{**a, "url": "https://reuters.com/outra"}])
    assert d1 != d2


def test_respeita_limite():
    arts = [
        _art(f"GPU prices rise alpha{i} bravo{i} charlie{i} delta{i}",
             f"https://site{i}.com/{i}", f"site{i}.com")
        for i in range(20)
    ]
    items, _, stats = news.build_digest(arts, limit=5)
    assert len(items) == 5
    assert stats["kept"] == 5


def test_corroborado_vem_antes_de_fonte_unica():
    items, _, _ = news.build_digest([
        _art("Historia isolada sobre GPU", "https://a.com/1", "a.com",
             "2026-11-03T18:00:00+00:00"),
        _art("Rare earth export controls tighten", "https://reuters.com/2", "reuters.com",
             "2026-11-02T10:00:00+00:00"),
        _art("Rare earth export controls are tightening", "https://ft.com/3", "ft.com",
             "2026-11-02T11:00:00+00:00"),
    ])
    assert items[0]["confidence"] == "corroborated"


def test_digest_nao_e_serializado_no_snapshot():
    from app.schemas import Snapshot

    assert "headlines_digest" not in Snapshot.model_fields
    assert "headlines_stats" not in Snapshot.model_fields


# ---------------- relevância e variedade ----------------


@pytest.mark.parametrize(
    "title",
    [
        "Apple warns of 'unprecedented' rise in memory chip prices",
        "NVIDIA GeForce RTX 50-Series Scheduled for up to $500 Price Hike This Week",
        "Motherboard and GPU Prices Could Rise Further as PCB Shortages Extend to 2030",
        "Intel Diverts 18A Capacity From Panther Lake to Meet Xeon Demand",
        "Chips para notebooks baratos estão esgotados, revela Intel",
        "Preço da memória RAM dispara com demanda de data centers",
        "China tightens rare earth export controls",
        "Tensão no Estreito de Taiwan preocupa fabricantes",
    ],
)
def test_aceita_noticia_ligada_a_preco(title):
    assert news.is_price_relevant(title)


@pytest.mark.parametrize(
    "title",
    [
        "The Legend of Zelda: Ocarina of Time Review – A Tantalizing Tune-Up",
        "Review The Legend of Zelda: Ocarina of Time | Uma obra-prima atemporal",
        "Netflix lança aba com IA que recomenda filmes e séries pelo seu humor",
        "Save $300 on this 1440p gaming PC with a 9800X3D and RTX 5070 right now",
        "Black November: Galaxy S25 Ultra (512 GB) despenca de preço na Amazon",
        "TV LG OLED 55″ recebe oferta histórica em até 12x na Amazon",
        "(PR) ASUS Republic of Gamers Announces ROG XG Station 3 With Thunderbolt 5",
        "GIGABYTE AORUS and Capcom Team Up for Resident Evil-Themed PC Giveaway",
        "Windows fica até 40% mais rápido em PCs com 8 GB de RAM",
        "Intel 14A moves closer to production as PDK 0.9 becomes available",
        "Putin demands Russian data centers supply capacity to the state",
        "Minister said again the budget is final",
    ],
)
def test_rejeita_noticia_sem_relacao_com_preco(title):
    assert not news.is_price_relevant(title)


def test_digest_descarta_irrelevante_de_qualquer_fonte():
    items, _, stats = news.build_digest([
        _art("Zelda remake review", "https://reuters.com/a", "reuters.com"),
        _art("Netflix adds AI tab", "https://bbc.co.uk/b", "bbc.co.uk"),
        _art("DRAM prices surge as AI demand drains supply", "https://ft.com/c", "ft.com"),
    ])
    assert [i["domain"] for i in items] == ["ft.com"]
    assert stats["irrelevant"] == 2


def test_variedade_de_fontes_no_maximo_duas_por_veiculo():
    arts = [
        _art(f"GPU prices rise alpha{i} bravo{i} charlie{i}",
             f"https://techpowerup.com/{i}", "techpowerup.com",
             f"2026-11-03T{10 + i:02d}:00:00+00:00")
        for i in range(6)
    ] + [
        _art("DRAM shortage worsens", "https://theregister.com/x", "theregister.com",
             "2026-11-01T10:00:00+00:00"),
        _art("Memory chip prices climb", "https://theguardian.com/y", "theguardian.com",
             "2026-11-01T09:00:00+00:00"),
    ]
    items, _, _ = news.build_digest(arts, limit=15)
    domains = [i["domain"] for i in items]
    assert domains.count("techpowerup.com") == 2
    # A primeira rodada traz um item de cada veículo antes de repetir.
    assert len(set(domains[:3])) == 3


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Dólar alto encarece celulares importados", True),
        ("Remessa Conforme: imposto de importação sobe para eletrônicos", True),
        ("Ukraine neon gas supply threatens chipmakers", True),
        ("Amazon's Ohio data center plan faces new hurdle as voters approve ban", False),
        ("Dólar sobe 2% com tensão fiscal", False),
    ],
)
def test_impacto_no_preco_no_brasil(title, expected):
    assert news.is_price_relevant(title) is expected


def test_analise_tem_vagas_proprias_depois_da_primeira_pagina():
    arts = [
        _art(f"GPU prices rise alpha{i} bravo{i} charlie{i}",
             f"https://site{i}.com/{i}", f"site{i}.com",
             f"2026-11-03T{10 + i:02d}:00:00+00:00")
        for i in range(12)
    ] + [
        {**_art(f"Why DRAM shortages persist delta{i} echo{i}",
                f"https://analise{i}.org/{i}", f"analise{i}.org",
                "2026-10-15T10:00:00+00:00"), "kind": "analysis"}
        for i in range(5)
    ]
    items, _, stats = news.build_digest(arts, limit=15)
    kinds = [i.get("kind", "news") for i in items]
    assert len(items) == 15
    assert kinds[:5] == ["news"] * 5
    assert kinds.count("analysis") == 3 == stats["analysis"]
