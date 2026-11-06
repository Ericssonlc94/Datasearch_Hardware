"""Notícias em en/pt/es agrupadas por entidades (T14) — testes offline, sem rede.

A mesma história em outro idioma quase não divide palavras com o original,
mas divide empresas, países e temas. Os testes travam as duas direções:
juntar o que é a mesma história (selo "confirmada" = `corroborated`) e não
juntar o que não é, para não dar "confirmada" a uma notícia de fonte única
(`single-source`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import news  # noqa: E402

APPLE_EN = "Apple warns of unprecedented rise in memory chip prices"
APPLE_PT = "Apple alerta para alta sem precedentes no preço de chips de memória"
APPLE_ES = "Apple advierte un alza sin precedentes en el precio de los chips de memoria"
HBM_EN = "Decoy processors carry Korean HBM past US export controls into China"
HBM_PT = ("Contrabandistas levam HBM da Coreia para a China driblando controles "
          "de exportação dos EUA")


def _art(title: str, domain: str, language: str = "en",
         seen: str | None = "2026-11-03T12:00:00+00:00") -> dict:
    return {"title": title, "url": f"https://{domain}/{abs(hash(title))}",
            "domain": domain, "seen_at": seen, "language": language}


def _mesma(a: str, b: str) -> bool:
    return news.same_story_by_keys(news.story_keys(a), news.story_keys(b))


# ---------------- caso 9 ----------------


def test_mesma_historia_em_tres_idiomas_tem_as_mesmas_chaves():
    chaves = [news.story_keys(t) for t in (APPLE_EN, APPLE_PT, APPLE_ES)]
    assert chaves[0] == chaves[1] == chaves[2]
    assert chaves[0]["companies"] == {"apple"}


def test_mesma_historia_em_tres_idiomas_forma_um_grupo_confirmado():
    items, _, stats = news.build_digest([
        _art(APPLE_EN, "reuters.com", "en"),
        _art(APPLE_PT, "valor.globo.com", "pt"),
        _art(APPLE_ES, "elpais.com", "es"),
    ])
    assert len(items) == 1
    item = items[0]
    assert item["corroboration"] == 3
    assert item["confidence"] == "corroborated"
    assert item["sources"] == ["elpais.com", "reuters.com", "valor.globo.com"]
    assert stats["merged_by_keys"] == 2
    assert stats["cross_language"] == 2
    assert stats["corroborated"] == 1 and stats["single_source"] == 0


# ---------------- caso 10 ----------------


def test_paises_sem_empresa_juntam_a_mesma_historia():
    a, b = news.story_keys(HBM_EN), news.story_keys(HBM_PT)
    assert not a["companies"] and not b["companies"]
    assert {"korea", "china", "usa"} <= a["countries"] & b["countries"]
    assert news.same_story_by_keys(a, b)

    items, _, stats = news.build_digest([
        _art(HBM_EN, "tomshardware.com", "en"),
        _art(HBM_PT, "tecmundo.com.br", "pt"),
    ])
    assert len(items) == 1
    assert items[0]["confidence"] == "corroborated"
    assert stats["cross_language"] == 1


# ---------------- caso 11 ----------------


def test_ticker_em_maiusculas_vale_como_a_empresa():
    ticker = "NVDA shares fall as China export curbs tighten"
    nome = "Nvidia: China endurece controles de exportação"
    assert news.story_keys(ticker)["companies"] == {"nvidia"}
    assert _mesma(ticker, nome)


# ---------------- caso 12 ----------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("Samsung raises DRAM prices", "Micron raises DRAM prices"),
        ("Nvidia tells data centers to limit business from Chinese customers",
         "Nvidia can only fulfill 1% of China GPU order"),
        ("US chip curbs hit SK Hynix plant in China",
         "CXMT expands DRAM output in China despite US chip curbs"),
        ("DRAM prices double", "Memory prices soar"),
    ],
    ids=["empresas-diferentes", "mesma-empresa-sem-tema", "skhynix-x-cxmt", "so-generico"],
)
def test_nao_junta_historias_diferentes_pelas_chaves(a, b):
    assert not _mesma(a, b)
    assert not _mesma(b, a)


@pytest.mark.parametrize(
    "a, b",
    [
        ("US chip curbs hit SK Hynix plant in China",
         "CXMT expands DRAM output in China despite US chip curbs"),
        ("DRAM prices double", "Memory prices soar"),
    ],
)
def test_digest_mantem_fonte_unica_quando_nao_e_a_mesma_historia(a, b):
    items, _, stats = news.build_digest([_art(a, "reuters.com"), _art(b, "ft.com")])
    assert len(items) == 2
    assert {i["confidence"] for i in items} == {"single-source"}
    assert stats["merged_by_keys"] == 0


def test_digest_nao_junta_empresas_diferentes_com_titulo_parecido():
    items, _, _ = news.build_digest([
        _art("Samsung raises DRAM prices", "reuters.com"),
        _art("Micron raises DRAM prices", "ft.com"),
    ])
    assert len(items) == 2
    assert {i["confidence"] for i in items} == {"single-source"}


# ---------------- caso 13 ----------------


def test_us_minusculo_nao_vira_estados_unidos():
    assert news.story_keys("Let us know what you think about memory prices")["countries"] == frozenset()
    assert "usa" in news.story_keys("US curbs on memory exports")["countries"]
    assert "usa" in news.story_keys("U.S. curbs on memory exports")["countries"]


# ---------------- caso 14 ----------------


def test_mais_de_72_horas_entre_as_datas_nao_junta():
    items, _, stats = news.build_digest([
        _art(APPLE_EN, "reuters.com", "en", seen="2026-11-01T00:00:00+00:00"),
        _art(APPLE_PT, "valor.globo.com", "pt", seen="2026-11-04T01:00:00+00:00"),
    ])
    assert len(items) == 2
    assert {i["confidence"] for i in items} == {"single-source"}
    assert stats["merged_by_keys"] == 0


def test_ate_72_horas_ainda_junta():
    items, _, _ = news.build_digest([
        _art(APPLE_EN, "reuters.com", "en", seen="2026-11-01T00:00:00+00:00"),
        _art(APPLE_PT, "valor.globo.com", "pt", seen="2026-11-04T00:00:00+00:00"),
    ])
    assert len(items) == 1 and items[0]["corroboration"] == 2


def test_sem_data_pode_juntar():
    items, _, stats = news.build_digest([
        _art(APPLE_EN, "reuters.com", "en", seen=None),
        _art(APPLE_PT, "valor.globo.com", "pt", seen="2026-11-04T00:00:00+00:00"),
    ])
    assert len(items) == 1
    assert items[0]["confidence"] == "corroborated"
    assert stats["cross_language"] == 1


# ---------------- caso 15 ----------------


def test_item_exibido_nao_carrega_chaves_internas():
    items, _, _ = news.build_digest([
        _art(APPLE_EN, "reuters.com", "en"),
        _art(APPLE_ES, "elpais.com", "es"),
        _art(HBM_EN, "tomshardware.com", "en"),
    ])
    assert items
    for item in items:
        assert "_keys" not in item
        assert not any(k.startswith("_") for k in item)
