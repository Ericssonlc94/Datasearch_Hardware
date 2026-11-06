"""Catálogo de séries do histórico — a fonte única do `/api/series`.

Cada chave aqui tem que casar exatamente com o que `services/history.py`
grava. O teste `test_history` cobre essa correspondência para o subconjunto
que ele exercita; o restante é gerado a partir de `drivers.py` e `catalog.py`,
então adicionar um driver ou categoria propaga sozinho.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import CATEGORIES
from .drivers import DRIVERS
from .prices import BAND_LABELS, BANDS, NO_HIGH_BAND, OUT_OF_PRICE_TAB

GROUP_LABELS = {
    "index": "Pressão",
    "supply": "Fila do consumidor",
    "driver": "Fatores",
    "signal": "Sinais",
    "category": "Produtos",
    "price": "Preços na loja",
}

# Versão da conta por série (ou prefixo terminado em "."), lida por
# `services/history.model_versions`: mudar a versão marca `model_since` no
# próximo snapshot. T30 (05/11/2026): frentes de oferta no vetor de alocação
# de chips, nota por exposição nas categorias e fila só de demanda.
_T30 = "t30-2026-11-05"
MODEL_VERSIONS = {
    "supply.queue": _T30,
    "driver.alocacao_chips": _T30,
    "iph": _T30,
    "iph_br": _T30,
    "cat.": _T30,
}


@dataclass(frozen=True)
class SeriesMeta:
    key: str
    label: str
    kind: str  # observed | modeled
    unit: str
    group: str


def _build() -> list[SeriesMeta]:
    out: list[SeriesMeta] = [
        SeriesMeta("iph", "Pressão global", "modeled", "0-100", "index"),
        SeriesMeta("iph_br", "Pressão no Brasil", "modeled", "0-100", "index"),
        SeriesMeta("coverage", "Dados disponíveis", "modeled", "%", "index"),
        SeriesMeta("supply.queue", "Fila do consumidor", "modeled", "0-100", "supply"),
        SeriesMeta("supply.capex_ttm", "Investimento em IA", "observed", "US$", "supply"),
        SeriesMeta("supply.inventory_ratio", "Estoque de memória (Micron)", "observed", "razão", "supply"),
        SeriesMeta("supply.diversion", "Desvio para IA", "modeled", "z", "supply"),
        SeriesMeta("supply.comtrade_volume", "Memória importada pelo Brasil", "observed", "US$", "supply"),
    ]

    for driver in DRIVERS:
        out.append(
            SeriesMeta(f"driver.{driver.key}", driver.label, "modeled", "0-100", "driver")
        )

    for driver in DRIVERS:
        for signal in driver.signals:
            out.append(
                SeriesMeta(
                    f"signal.{signal.key}",
                    f"{signal.label} ({driver.label})",
                    "observed",
                    signal.unit,
                    "signal",
                )
            )

    for cat in CATEGORIES:
        out.extend(
            [
                SeriesMeta(
                    f"cat.{cat.key}.pressure",
                    f"Pressão — {cat.label}",
                    "modeled",
                    "0-100",
                    "category",
                ),
                SeriesMeta(
                    f"cat.{cat.key}.proj30_global",
                    f"Global em US$ (estimativa p/ 30 dias seguintes) — {cat.label}",
                    "modeled",
                    "%",
                    "category",
                ),
                SeriesMeta(
                    f"cat.{cat.key}.proj30_br",
                    f"Brasil (estimativa p/ 30 dias seguintes) — {cat.label}",
                    "modeled",
                    "%",
                    "category",
                ),
            ]
        )
        if cat.ipca_subitem:
            out.append(
                SeriesMeta(
                    f"obs.{cat.key}.ipca",
                    f"Inflação mensal — {cat.label}",
                    "observed",
                    "%",
                    "category",
                )
            )
        out.append(
            SeriesMeta(
                f"obs.{cat.key}.usd_kg",
                f"Preço de importação — {cat.label}",
                "observed",
                "US$/kg",
                "category",
            )
        )

    # Preço cheio da faixa na KaBuM (`prices.build_prices_view`). As séries por
    # anúncio (`kabum.<código>.*`) ficam fora do catálogo público.
    for cat in CATEGORIES:
        if cat.key in OUT_OF_PRICE_TAB:
            continue
        for band in BANDS:
            if band == "alto" and cat.key in NO_HIGH_BAND:
                continue
            label = f"Preço cheio, faixa {BAND_LABELS[band]} — {cat.label}"
            out.append(SeriesMeta(f"price.{cat.key}.{band}", label, "observed", "R$", "price"))
            if cat.key == "gpu":
                for brand, name in (("nvidia", "NVIDIA"), ("amd", "AMD")):
                    out.append(SeriesMeta(
                        f"price.gpu.{band}.{brand}",
                        f"Preço cheio {name}, faixa {BAND_LABELS[band]} — {cat.label}",
                        "observed", "R$", "price",
                    ))
                out.append(SeriesMeta(
                    f"price.gpu.{band}.diff_amd_pct",
                    f"Diferença AMD × NVIDIA, faixa {BAND_LABELS[band]} — {cat.label}",
                    "observed", "%", "price",
                ))

    return out


SERIES: list[SeriesMeta] = _build()
SERIES_BY_KEY: dict[str, SeriesMeta] = {s.key: s for s in SERIES}


def catalog_groups() -> list[dict]:
    """Agrupa o catálogo na ordem em que a interface deve exibir."""
    groups: list[dict] = []
    for group, label in GROUP_LABELS.items():
        items = [s for s in SERIES if s.group == group]
        if not items:
            continue
        groups.append(
            {
                "key": group,
                "label": label,
                "series": [
                    {"key": s.key, "label": s.label, "kind": s.kind, "unit": s.unit}
                    for s in items
                ],
            }
        )
    return groups
