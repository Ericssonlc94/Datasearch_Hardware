"""Preço na KaBuM por categoria e faixa (baixo, médio, alto) — contas puras.

Desenho da T35 (05/11/2026): a cesta é uma lista de **modelos**, cada um com
um termo de busca. A coleta (`app/providers/kabum.py`) faz 1 busca por modelo
e devolve os anúncios cujo nome casa com o modelo (`match_name`). Este módulo
não acessa rede, banco nem framework.

Regras, na ordem em que entram:

1. **Anúncio válido no dia** (`screen_listing`): disponível, vendedor aceito,
   preço cheio coerente, dentro da faixa plausível da categoria (K14b) e da
   faixa de preço do nível com folga (`band_filter`). Indisponível é lacuna
   (K14e): o último preço nunca é repetido. Oferta relâmpago não tira o
   anúncio: o preço principal é o cheio, e o relâmpago só vira selo (T24i).
2. **Vendedor**: vale a própria KaBuM!; o marketplace dentro da KaBuM entra
   só no modelo que não tem nenhum anúncio válido da KaBuM! no dia (T33).
3. **Preço anormal** (`screen_abnormal`, T29b): anúncio acima de 1,5× ou
   abaixo de 1/1,5 da mediana dos outros anúncios do modelo sai da conta.
4. **Preço do modelo** (`model_day`): mediana do preço cheio dos anúncios
   válidos; os até 3 mais próximos da mediana ficam como referência.
5. **Preço da faixa**: média simples dos modelos com preço — cada modelo pesa
   igual. **Variação** (`paired_change`): pareada por modelo (cada modelo
   contra ele mesmo) e média dos modelos presentes nas duas datas, para a
   entrada ou a falta de um modelo não aparecer como salto de preço.
6. **Categoria** (`category_day`): só publica com ≥ 2 das 3 faixas.

Preço cheio (T24i/T27c): na **busca**, `price` é o cheio (parcelado em até
10× sem juros), igual ao `oldPrice` da página de produto em oferta; o à vista
(`priceWithDiscount`) só é guardado sem relâmpago, para a 2ª linha; durante a
oferta ele vira o preço relâmpago e é só selo. Nenhum dos dois entra na
mediana.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

# Ligado na T30, junto com a coleta da KaBuM (`app/providers/kabum.py`).
PRICES_ENABLED = True

KABUM_SELLER = "KaBuM!"
PRICE_LABEL = "Preço na KaBuM (preço cheio)"
PRICE_NOTE = (
    "Uma loja, {models} modelos buscados por coleta; o preço de cada modelo é "
    "a mediana dos anúncios. Não é média de mercado. "
    "Preço cheio = parcelado em até 10× sem juros."
)
# Teto de renda do consumidor médio (T24i): 10 × R$ 1.000 ≈ 27% da renda
# média do trabalhador (R$ 3.722, PNAD 1T26) por 10 meses. Nenhuma faixa
# exibida passa dele.
INCOME_CEILING_BRL = 10_000.0
BANDS = ("baixo", "medio", "alto")
BAND_LABELS = {"baixo": "baixo", "medio": "médio", "alto": "alto"}

# Mínimo de faixas com preço para a categoria aparecer.
MIN_BANDS = 2
# Categorias sem faixa alta / fora da aba de preço (só IPCA). Desde a T33
# todas têm as três faixas.
NO_HIGH_BAND: frozenset[str] = frozenset()
OUT_OF_PRICE_TAB: frozenset[str] = frozenset()

# Preço anormal (T29b): montadoras diferentes do mesmo chip ficam a até
# ~30–40% umas das outras; edição especial chega a 2–4×. 1,5× separa as duas
# coisas. Na T35 vale também para baixo (anúncio de peça avulsa que passou
# pelo filtro de nome).
PEER_MAX_RATIO = 1.5
# Folga da faixa do nível no filtro do anúncio (T35): a faixa exibida é
# contígua entre os níveis; 25% de folga deixa o modelo continuar na conta
# quando o preço anda, e ainda tira o produto errado (notebook com "RTX 3050"
# no nome, peça avulsa).
BAND_FILTER_MARGIN = 0.25
# Referências guardadas por modelo (as mais próximas da mediana).
MAX_REFS = 3

# K14b: preço plausível por categoria, em R$ (proteção contra centavos lidos
# como reais, 0 ou 1e9 — não é a faixa do nível).
PLAUSIBLE_BRL: dict[str, tuple[float, float]] = {
    "gpu": (300.0, 40_000.0),
    "ram": (50.0, 25_000.0),
    "storage": (80.0, 12_000.0),
    "cpu": (200.0, 15_000.0),
    "motherboard": (250.0, 10_000.0),
    "psu": (150.0, 5_000.0),
    "smartphone": (400.0, 20_000.0),
    "notebook": (1_500.0, 60_000.0),
    "monitor": (300.0, 15_000.0),
    "console": (1_000.0, 10_000.0),
}


# --- cesta: modelos e faixas --------------------------------------------------

# Muda a cada troca da cesta; entra na chave do cache (cesta nova = coleta
# vencida) e é conferida no payload (coleta de outra cesta não vira preço).
BASKET_VERSION = "t35-2026-11-05"

# Faixa exibida de cada nível, em R$ de preço cheio (T33c): contígua, o
# máximo de um nível é o mínimo do seguinte.
BAND_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "gpu": {"baixo": (1_500, 2_500), "medio": (2_500, 5_000), "alto": (5_000, 10_000)},
    "ram": {"baixo": (650, 1_300), "medio": (1_300, 4_100), "alto": (4_100, 8_000)},
    "storage": {"baixo": (350, 750), "medio": (750, 2_050), "alto": (2_050, 3_550)},
    "cpu": {"baixo": (500, 1_400), "medio": (1_400, 2_100), "alto": (2_100, 4_000)},
    "motherboard": {"baixo": (450, 1_000), "medio": (1_000, 2_000), "alto": (2_000, 3_500)},
    "psu": {"baixo": (300, 600), "medio": (600, 1_000), "alto": (1_000, 1_500)},
    "monitor": {"baixo": (600, 1_100), "medio": (1_100, 2_300), "alto": (2_300, 3_500)},
    "console": {"baixo": (2_000, 3_600), "medio": (3_600, 5_500), "alto": (5_500, 7_500)},
    "smartphone": {"baixo": (800, 1_500), "medio": (1_500, 2_800), "alto": (2_800, 5_500)},
    "notebook": {"baixo": (2_700, 4_450), "medio": (4_450, 5_700), "alto": (5_700, 10_000)},
}

# Fora de qualquer modelo (T35): kit, combo, usado e acessório.
GLOBAL_EXCLUDE = ("kit", "combo", "usado", "seminovo", "recondicionado", "vitrine",
                  "acessorio", "acessorios")
# Por categoria, o nome precisa **começar** pelo tipo do produto (T35): tira
# tampa, leitor e cooler de console, PC montado, "kit upgrade" e capa.
CATEGORY_PREFIX: dict[str, tuple[str, ...]] = {
    "gpu": ("placa de video",),
    "ram": ("memoria",),
    "storage": ("ssd",),
    "cpu": ("processador",),
    "motherboard": ("placa mae",),
    "psu": ("fonte",),
    "monitor": ("monitor",),
    "console": ("console",),
    "smartphone": ("smartphone", "celular"),
    "notebook": ("notebook",),
}
# E não pode ter, em lugar nenhum do nome, o que costuma vir junto na busca.
CATEGORY_EXCLUDE: dict[str, tuple[str, ...]] = {
    "gpu": ("notebook", "pc gamer", "computador"),
    "ram": ("notebook", "sodimm", "so dimm"),
    "storage": ("case", "gaveta", "adaptador", "externo", "portatil"),
    "cpu": ("placa mae",),
    "motherboard": ("processador",),
    "psu": ("gabinete",),
    "monitor": ("suporte",),
    "console": ("tampa", "leitor drive", "leitor de disco para"),
    "smartphone": ("capa", "capinha", "pelicula"),
    "notebook": ("capa", "mochila", "suporte", "carregador", "bateria"),
}


@dataclass(frozen=True)
class BasketModel:
    """Um modelo da cesta: termo de busca e como reconhecer o anúncio pelo nome.

    `require`: cada item precisa aparecer no nome; "a|b" aceita qualquer uma
    das grafias. `exclude`: nenhum pode aparecer (soma-se aos globais e aos da
    categoria). `keep` tira um global da lista (o kit 2×16 da RAM).
    """

    key: str
    category: str
    band: str
    brand: str
    model: str
    term: str
    require: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()


def _m(category: str, band: str, key: str, model: str, term: str, require: tuple[str, ...],
       exclude: tuple[str, ...] = (), brand: str = "—", keep: tuple[str, ...] = ()) -> BasketModel:
    return BasketModel(f"{category}-{key}", category, band, brand, model, term,
                       require, exclude, keep)


_QHD = "qhd|2k|wqhd|1440p|2560x1440"
_FHD = "full hd|fhd|1080p|1920x1080"
_PS5 = "playstation 5|playstation5|ps5"

# Cesta aprovada (T35): de 3 a 5 modelos de alto consumo por faixa, de
# qualquer geração, escolhidos pelo preço atual dentro da faixa exibida. A
# chave não leva a faixa: o modelo pode mudar de nível com o preço sem perder
# o histórico. Remanejados pela coleta de 05/11/2026 (mediana medida): NV3
# 500 GB e i5-12400F para o médio, B550 e 750 W Bronze para o baixo, notebook
# Ryzen 5/8 GB para o médio e Core i5/16 GB para o alto. Fora: RTX 5070 Ti e
# notebooks RTX 4050/4060 (mediana acima de R$ 10 mil), Arc B580 (busca
# redirecionada duas vezes).
BASKET: list[BasketModel] = [
    # GPU — marca entra na visão NVIDIA × AMD; Intel só na faixa.
    _m("gpu", "baixo", "rtx-3050", "RTX 3050", "rtx-3050", ("rtx 3050",), brand="NVIDIA"),
    _m("gpu", "baixo", "rx-6600", "RX 6600", "rx-6600", ("rx 6600",),
       ("6600 xt", "6650"), brand="AMD"),
    _m("gpu", "baixo", "rtx-3060", "RTX 3060", "rtx-3060", ("rtx 3060",),
       ("3060 ti",), brand="NVIDIA"),
    _m("gpu", "baixo", "arc-b570", "Arc B570", "placa-de-video-arc-b570", ("b570",), brand="Intel"),
    _m("gpu", "medio", "rtx-5060", "RTX 5060", "rtx-5060", ("rtx 5060",),
       ("5060 ti",), brand="NVIDIA"),
    _m("gpu", "medio", "rtx-4060", "RTX 4060", "rtx-4060", ("rtx 4060",),
       ("4060 ti",), brand="NVIDIA"),
    _m("gpu", "medio", "rx-7600", "RX 7600", "rx-7600", ("rx 7600",),
       ("7600 xt",), brand="AMD"),
    _m("gpu", "medio", "rtx-5060-ti", "RTX 5060 Ti", "placa-de-video-rtx-5060-ti", ("rtx 5060 ti",),
       brand="NVIDIA"),
    _m("gpu", "alto", "rtx-5070", "RTX 5070", "placa-de-video-rtx-5070", ("rtx 5070",),
       ("5070 ti",), brand="NVIDIA"),
    _m("gpu", "alto", "rx-9070-xt", "RX 9070 XT", "placa-de-video-rx-9070-xt", ("rx 9070 xt",),
       brand="AMD"),
    _m("gpu", "alto", "rx-9070", "RX 9070", "placa-de-video-rx-9070", ("rx 9070",),
       ("9070 xt",), brand="AMD"),
    # RAM — desktop (sem SODIMM); o alto é kit 2×16.
    _m("ram", "baixo", "fury-ddr4-8", "Kingston Fury Beast DDR4 8 GB", "memoria-kingston-fury-beast-ddr4-8gb",
       ("fury beast", "ddr4", "8gb"), ("16gb", "32gb", "2x8", "rgb")),
    _m("ram", "baixo", "lpx-ddr4-8", "Corsair Vengeance LPX DDR4 8 GB", "memoria-corsair-vengeance-lpx-8gb",
       ("vengeance lpx", "ddr4", "8gb"), ("16gb", "32gb", "2x8")),
    _m("ram", "baixo", "d35-ddr4-8", "XPG Gammix D35 DDR4 8 GB", "memoria-xpg-gammix-d35-8gb",
       ("d35", "8gb"), ("16gb", "32gb", "2x8")),
    _m("ram", "medio", "fury-ddr5-16", "Kingston Fury Beast DDR5 16 GB", "memoria-kingston-fury-beast-ddr5-16gb",
       ("fury beast", "ddr5", "16gb"), ("32gb", "2x8", "2x16", "rgb")),
    _m("ram", "medio", "vengeance-ddr5-16", "Corsair Vengeance DDR5 16 GB", "memoria-corsair-vengeance-ddr5-16gb",
       ("vengeance", "ddr5", "16gb"), ("32gb", "2x8", "2x16", "rgb")),
    _m("ram", "medio", "fury-ddr4-16", "Kingston Fury Beast DDR4 16 GB", "memoria-kingston-fury-beast-ddr4-16gb",
       ("fury beast", "ddr4", "16gb"), ("32gb", "2x8", "2x16", "rgb")),
    _m("ram", "medio", "lancer-ddr5-16", "XPG Lancer DDR5 16 GB", "memoria-xpg-lancer-ddr5-16gb",
       ("lancer", "16gb"), ("32gb", "2x8", "2x16")),
    _m("ram", "alto", "fury-ddr5-32", "Kingston Fury Beast DDR5 32 GB", "memoria-kingston-fury-beast-ddr5-32gb",
       ("fury beast", "ddr5", "32gb"), ("64gb",), keep=("kit",)),
    _m("ram", "alto", "vengeance-ddr5-32", "Corsair Vengeance DDR5 32 GB", "memoria-corsair-vengeance-ddr5-32gb",
       ("vengeance", "ddr5", "32gb"), ("64gb",), keep=("kit",)),
    _m("ram", "alto", "lancer-ddr5-32", "XPG Lancer DDR5 32 GB", "memoria-xpg-lancer-ddr5-32gb",
       ("lancer", "32gb"), ("64gb",), keep=("kit",)),
    _m("ram", "alto", "fury-ddr4-32", "Kingston Fury Beast DDR4 32 GB", "memoria-kingston-fury-beast-ddr4-32gb",
       ("fury beast", "ddr4", "32gb"), ("64gb",), keep=("kit",)),
    # SSD
    _m("storage", "baixo", "a400-240", "Kingston A400 240 GB", "ssd-kingston-a400-240gb", ("a400", "240gb")),
    _m("storage", "baixo", "a400-480", "Kingston A400 480 GB", "ssd-kingston-a400-480gb", ("a400", "480gb")),
    _m("storage", "baixo", "green-240", "WD Green 240 GB", "ssd-wd-green-240gb", ("green", "240gb")),
    _m("storage", "medio", "nv3-500", "Kingston NV3 500 GB", "ssd-kingston-nv3-500gb", ("nv3", "500gb")),
    _m("storage", "medio", "nv3-1tb", "Kingston NV3 1 TB", "kingston-nv3-1tb", ("nv3", "1tb")),
    _m("storage", "medio", "sn770-1tb", "WD Black SN770 1 TB", "wd-black-sn770", ("sn770", "1tb")),
    _m("storage", "medio", "p3plus-1tb", "Crucial P3 Plus 1 TB", "crucial-p3-plus-1tb", ("p3 plus", "1tb")),
    _m("storage", "medio", "a400-960", "Kingston A400 960 GB", "ssd-kingston-a400-960gb", ("a400", "960gb")),
    _m("storage", "alto", "nv3-2tb", "Kingston NV3 2 TB", "ssd-kingston-nv3-2tb", ("nv3", "2tb")),
    _m("storage", "alto", "sn850x-2tb", "WD Black SN850X 2 TB", "wd-black-sn850x", ("sn850x", "2tb")),
    _m("storage", "alto", "990evoplus-2tb", "Samsung 990 EVO Plus 2 TB", "ssd-samsung-990-evo-plus-2tb",
       ("990 evo plus", "2tb")),
    _m("storage", "alto", "p3plus-2tb", "Crucial P3 Plus 2 TB", "crucial-p3-plus-2tb", ("p3 plus", "2tb")),
    # CPU — "ryzen 5 5600" não casa com 5600X/5600G (token diferente).
    _m("cpu", "baixo", "r5-5500", "Ryzen 5 5500", "ryzen-5-5500", ("ryzen 5 5500",), brand="AMD"),
    _m("cpu", "baixo", "r5-5600", "Ryzen 5 5600", "ryzen-5-5600", ("ryzen 5 5600",), brand="AMD"),
    _m("cpu", "baixo", "r5-5600g", "Ryzen 5 5600G", "ryzen-5-5600g", ("5600g",), brand="AMD"),
    _m("cpu", "baixo", "i3-12100f", "Core i3-12100F", "processador-intel-core-i3-12100f", ("12100f",),
       brand="Intel"),
    _m("cpu", "medio", "i5-12400f", "Core i5-12400F", "processador-intel-core-i5-12400f", ("12400f",),
       brand="Intel"),
    _m("cpu", "medio", "i5-14400f", "Core i5-14400F", "processador-intel-core-i5-14400f", ("14400f",),
       brand="Intel"),
    _m("cpu", "medio", "r5-7600", "Ryzen 5 7600", "processador-amd-ryzen-5-7600", ("ryzen 5 7600",), brand="AMD"),
    _m("cpu", "medio", "r5-8600g", "Ryzen 5 8600G", "processador-amd-ryzen-5-8600g", ("8600g",), brand="AMD"),
    _m("cpu", "medio", "i5-13400f", "Core i5-13400F", "processador-intel-core-i5-13400f", ("13400f",),
       brand="Intel"),
    _m("cpu", "alto", "r7-5700x", "Ryzen 7 5700X", "processador-amd-ryzen-7-5700x", ("ryzen 7 5700x",),
       brand="AMD"),
    _m("cpu", "alto", "r7-7700", "Ryzen 7 7700", "processador-amd-ryzen-7-7700", ("ryzen 7 7700",), brand="AMD"),
    _m("cpu", "alto", "i7-14700f", "Core i7-14700F", "processador-intel-core-i7-14700f", ("14700f",),
       brand="Intel"),
    _m("cpu", "alto", "i5-14600kf", "Core i5-14600KF", "processador-intel-core-i5-14600kf", ("14600kf",),
       brand="Intel"),
    # Placa-mãe — o chipset é o modelo.
    _m("motherboard", "baixo", "a520", "Chipset A520 (AM4)", "placa-mae-a520m", ("a520",)),
    _m("motherboard", "baixo", "h610", "Chipset H610 (LGA 1700)", "placa-mae-h610", ("h610",)),
    _m("motherboard", "baixo", "b450", "Chipset B450 (AM4)", "placa-mae-b450m", ("b450",)),
    _m("motherboard", "baixo", "a620", "Chipset A620 (AM5)", "placa-mae-a620m", ("a620",)),
    _m("motherboard", "medio", "b650", "Chipset B650 (AM5)", "placa-mae-b650", ("b650",)),
    _m("motherboard", "baixo", "b550", "Chipset B550 (AM4)", "placa-mae-b550m", ("b550",)),
    _m("motherboard", "medio", "b760", "Chipset B760 (LGA 1700)", "placa-mae-b760m", ("b760",)),
    _m("motherboard", "medio", "b860", "Chipset B860 (LGA 1851)", "placa-mae-b860", ("b860",)),
    _m("motherboard", "alto", "b850", "Chipset B850 (AM5)", "placa-mae-b850", ("b850",)),
    _m("motherboard", "alto", "x870", "Chipset X870 (AM5)", "placa-mae-x870", ("x870",)),
    _m("motherboard", "alto", "z790", "Chipset Z790 (LGA 1700)", "placa-mae-z790", ("z790",)),
    # Fonte — potência e selo são o modelo.
    _m("psu", "baixo", "650-bronze", "650 W 80 Plus Bronze", "fonte-650w-80-plus-bronze", ("650w", "bronze")),
    _m("psu", "baixo", "600-bronze", "600 W 80 Plus Bronze", "fonte-600w-80-plus-bronze", ("600w", "bronze")),
    _m("psu", "baixo", "550-bronze", "550 W 80 Plus Bronze", "fonte-550w-80-plus-bronze", ("550w", "bronze")),
    _m("psu", "baixo", "500-80plus", "500 W 80 Plus", "fonte-500w-80-plus", ("500w", "80 plus")),
    _m("psu", "medio", "750-gold", "750 W 80 Plus Gold", "fonte-750w-80-plus-gold", ("750w", "gold")),
    _m("psu", "medio", "850-gold", "850 W 80 Plus Gold", "fonte-850w-80-plus-gold", ("850w", "gold")),
    _m("psu", "baixo", "750-bronze", "750 W 80 Plus Bronze", "fonte-750w-80-plus-bronze", ("750w", "bronze")),
    _m("psu", "medio", "650-gold", "650 W 80 Plus Gold", "fonte-650w-80-plus-gold", ("650w", "gold")),
    _m("psu", "alto", "1000-gold", "1000 W 80 Plus Gold", "fonte-1000w-gold", ("1000w", "gold")),
    _m("psu", "alto", "1000-bronze", "1000 W 80 Plus Bronze", "fonte-1000w-80-plus-bronze", ("1000w", "bronze")),
    _m("psu", "alto", "1200-gold", "1200 W 80 Plus Gold", "fonte-1200w-80-plus-gold", ("1200w", "gold")),
    # Monitor — tamanho, resolução e taxa são o modelo.
    _m("monitor", "baixo", "24-fhd-100", '24" Full HD 100 Hz', "monitor-24-full-hd-100hz",
       ("24|23 8", _FHD, "100hz")),
    _m("monitor", "baixo", "24-fhd-180", '24" Full HD 165–180 Hz', "monitor-gamer-24-180hz",
       ("24|23 8", _FHD, "165hz|170hz|180hz")),
    _m("monitor", "baixo", "27-fhd-100", '27" Full HD 100–120 Hz', "monitor-27-full-hd-100hz",
       ("27", _FHD, "100hz|120hz")),
    _m("monitor", "medio", "27-qhd-165", '27" QHD 165–170 Hz', "monitor-gamer-27-qhd-165hz",
       ("27", _QHD, "165hz|170hz")),
    _m("monitor", "medio", "27-qhd-180", '27" QHD 180 Hz', "monitor-gamer-27-qhd-180hz",
       ("27", _QHD, "180hz")),
    _m("monitor", "medio", "27-fhd-240", '27" Full HD 240 Hz', "monitor-gamer-27-full-hd-240hz",
       ("27", _FHD, "240hz")),
    _m("monitor", "medio", "34-uw", '34" ultrawide', "monitor-ultrawide-34", ("34", "ultrawide|ultra wide")),
    _m("monitor", "alto", "27-qhd-240", '27" QHD 240 Hz', "monitor-qhd-240hz", ("27", _QHD, "240hz")),
    _m("monitor", "alto", "27-qhd-200", '27" QHD 200–210 Hz', "monitor-gamer-27-qhd-200hz",
       ("27", _QHD, "200hz|210hz")),
    _m("monitor", "alto", "4k-144", '4K 144–160 Hz', "monitor-4k-144hz",
       ("4k|uhd|3840x2160", "144hz|150hz|160hz")),
    # Console
    _m("console", "baixo", "switch-oled", "Nintendo Switch OLED", "console-nintendo-switch-oled",
       ("switch", "oled"), ("switch 2",), brand="Nintendo"),
    _m("console", "baixo", "series-s", "Xbox Series S", "console-xbox-series-s", ("series s",),
       brand="Microsoft"),
    _m("console", "baixo", "switch", "Nintendo Switch", "nintendo-switch", ("nintendo switch",),
       ("oled", "lite", "switch 2"), brand="Nintendo"),
    _m("console", "medio", "switch-2", "Nintendo Switch 2", "nintendo-switch-2", ("switch 2",),
       brand="Nintendo"),
    _m("console", "medio", "ps5-digital", "PlayStation 5 Slim Digital", "console-playstation-5-slim-digital",
       (_PS5, "digital"), ("pro",), brand="Sony"),
    _m("console", "medio", "series-x", "Xbox Series X", "xbox-series-x", ("series x",),
       brand="Microsoft"),
    _m("console", "alto", "ps5-disco", "PlayStation 5 Slim com leitor", "console-playstation-5-slim",
       (_PS5,), ("digital", "pro"), brand="Sony"),
    _m("console", "alto", "ps5-pro", "PlayStation 5 Pro", "console-playstation-5-pro", (_PS5, "pro"),
       brand="Sony"),
    _m("console", "alto", "rog-ally", "ROG Ally", "rog-ally", ("rog ally",), brand="ASUS"),
    # Celular
    _m("smartphone", "baixo", "a07", "Galaxy A07", "smartphone-samsung-galaxy-a07", ("a07",), brand="Samsung"),
    _m("smartphone", "baixo", "a16", "Galaxy A16", "smartphone-samsung-galaxy-a16", ("a16",), brand="Samsung"),
    _m("smartphone", "baixo", "g15", "Moto G15", "smartphone-motorola-moto-g15", ("g15",), brand="Motorola"),
    _m("smartphone", "baixo", "redmi-15c", "Redmi 15C", "smartphone-xiaomi-redmi-15c", ("redmi 15c",),
       brand="Xiaomi"),
    _m("smartphone", "medio", "a57", "Galaxy A57", "smartphone-samsung-galaxy-a57", ("a57",), brand="Samsung"),
    _m("smartphone", "medio", "a37", "Galaxy A37", "smartphone-samsung-galaxy-a37", ("a37",), brand="Samsung"),
    _m("smartphone", "medio", "g86", "Moto G86", "smartphone-motorola-moto-g86", ("g86",), brand="Motorola"),
    _m("smartphone", "medio", "note-15", "Redmi Note 15", "smartphone-xiaomi-redmi-note-15",
       ("redmi note 15",), ("pro",), brand="Xiaomi"),
    _m("smartphone", "alto", "s25-fe", "Galaxy S25 FE", "smartphone-samsung-galaxy-s25-fe", ("s25 fe",),
       brand="Samsung"),
    _m("smartphone", "alto", "s25", "Galaxy S25", "galaxy-s25", ("galaxy s25",),
       ("fe", "ultra", "plus", "edge"), brand="Samsung"),
    _m("smartphone", "alto", "iphone-15", "iPhone 15", "iphone-15-128gb", ("iphone 15",), ("pro", "plus"),
       brand="Apple"),
    _m("smartphone", "alto", "edge-60-pro", "Motorola Edge 60 Pro", "smartphone-motorola-edge-60-pro",
       ("edge 60 pro",), brand="Motorola"),
    # Notebook — processador, memória e placa de vídeo são o modelo.
    _m("notebook", "baixo", "r3", "Ryzen 3", "notebook-ryzen-3", ("ryzen 3",)),
    _m("notebook", "baixo", "i3", "Core i3", "notebook-intel-core-i3", ("i3",)),
    _m("notebook", "medio", "r5-8gb", "Ryzen 5 / 8 GB", "notebook-ryzen-5-8gb", ("ryzen 5", "8gb"), ("rtx",)),
    _m("notebook", "baixo", "i5-8gb", "Core i5 / 8 GB", "notebook-intel-core-i5-8gb", ("i5", "8gb"), ("rtx",)),
    _m("notebook", "medio", "r5-16gb", "Ryzen 5 / 16 GB", "notebook-ryzen-5-16gb", ("ryzen 5", "16gb"),
       ("rtx",)),
    _m("notebook", "alto", "i5-16gb", "Core i5 / 16 GB", "notebook-intel-core-i5-16gb", ("i5", "16gb"),
       ("rtx",)),
    _m("notebook", "medio", "r7-16gb", "Ryzen 7 / 16 GB", "notebook-ryzen-7-16gb", ("ryzen 7", "16gb"),
       ("rtx",)),
    _m("notebook", "medio", "i7-16gb", "Core i7 / 16 GB", "notebook-intel-core-i7-16gb", ("i7", "16gb"),
       ("rtx",)),
    _m("notebook", "alto", "rtx-3050", "Gamer RTX 3050", "notebook-gamer-rtx-3050", ("rtx 3050",)),
    _m("notebook", "alto", "rtx-5050", "Gamer RTX 5050", "notebook-gamer-rtx-5050", ("rtx 5050",)),
]

BASKET_BY_KEY: dict[str, BasketModel] = {m.key: m for m in BASKET}
MODELS_PER_BAND = (3, 5)
_TERM_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){0,11}$")
_KEY_RE = re.compile(r"^[a-z0-9-]{3,60}$")


def expected_bands(category: str) -> tuple[str, ...]:
    """Faixas que a categoria tem (todas, desde a T33)."""
    if category in OUT_OF_PRICE_TAB:
        return ()
    if category in NO_HIGH_BAND:
        return tuple(b for b in BANDS if b != "alto")
    return BANDS


def display_range(category: str, band: str) -> tuple[float, float | None]:
    """Faixa de R$ exibida no nível; contígua com a do nível de cima."""
    lo, hi = BAND_RANGES.get(category, {}).get(band, (0.0, None))
    return float(lo), (float(hi) if hi is not None else None)


def band_filter(category: str, band: str) -> tuple[float, float]:
    """Faixa aceita para o anúncio: a exibida com `BAND_FILTER_MARGIN` de folga."""
    lo, hi = display_range(category, band)
    top = hi if hi is not None else PLAUSIBLE_BRL[category][1]
    return lo / (1 + BAND_FILTER_MARGIN), top * (1 + BAND_FILTER_MARGIN)


def models_for(category: str, band: str) -> list[BasketModel]:
    return [m for m in BASKET if m.category == category and m.band == band]


def validate_basket() -> list[str]:
    """Confere a cesta contra o catálogo, as faixas e o formato dos termos."""
    from .catalog import CATEGORIES_BY_KEY

    problems: list[str] = []
    if len(BASKET_BY_KEY) != len(BASKET):
        problems.append("chave de modelo repetida")
    terms = [m.term for m in BASKET]
    if len(set(terms)) != len(terms):
        problems.append("termo de busca repetido")
    for m in BASKET:
        if m.category not in CATEGORIES_BY_KEY:
            problems.append(f"{m.key}: categoria desconhecida")
        if m.band not in BANDS:
            problems.append(f"{m.key}: faixa desconhecida")
        if not _TERM_RE.match(m.term):
            problems.append(f"{m.key}: termo fora do formato a-z0-9 com hífen")
        if not _KEY_RE.match(m.key):
            problems.append(f"{m.key}: chave fora do formato")
        if not m.require:
            problems.append(f"{m.key}: sem termo obrigatório no nome")
    lo_n, hi_n = MODELS_PER_BAND
    for key in CATEGORIES_BY_KEY:
        if key not in PLAUSIBLE_BRL:
            problems.append(f"{key}: sem faixa plausível (K14b)")
        bands = expected_bands(key)
        for band in bands:
            n = len(models_for(key, band))
            if not lo_n <= n <= hi_n:
                problems.append(f"{key}/{band}: {n} modelos, esperado de {lo_n} a {hi_n}")
            hi = display_range(key, band)[1]
            if hi is None or hi > INCOME_CEILING_BRL:
                problems.append(f"{key}/{band}: teto acima do consumidor médio (R$ 10 mil)")
        for low, high in zip(bands, bands[1:]):
            if (display_range(key, low)[1] or 0) > display_range(key, high)[0]:
                problems.append(f"{key}: faixa exibida de {low} sobrepõe {high}")
    return problems


# --- nome do anúncio ----------------------------------------------------------------

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_UNIT = re.compile(r"(?<=\d) (gb|tb|w|hz|mhz)(?![a-z0-9])")


def normalize_name(text: str) -> str:
    """Minúsculas, sem acento, só letras e números; "8 GB" vira "8gb"."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch)).lower()
    plain = " ".join(_NON_ALNUM.sub(" ", plain).split())
    return _UNIT.sub(r"\1", plain)


def _has(norm: str, phrase: str) -> bool:
    """`phrase` no nome, em palavras inteiras; o espaço entre palavras é opcional
    ("rtx 5070" casa "RTX5070"), mas "rtx 5070" não casa "RTX 5070 Ti" só se
    "5070 ti" estiver nas exclusões."""
    for alt in phrase.split("|"):
        tokens = normalize_name(alt).split()
        if tokens and re.search(r"(?<![a-z0-9])" + " ?".join(map(re.escape, tokens)) + r"(?![a-z0-9])", norm):
            return True
    return False


def match_name(model: BasketModel, name: str | None) -> bool:
    """Se o anúncio é do modelo: começa pelo tipo, tem todos os obrigatórios e
    nenhuma exclusão."""
    if not name:
        return False
    norm = normalize_name(name)
    prefixes = CATEGORY_PREFIX.get(model.category, ())
    if prefixes and not norm.startswith(tuple(normalize_name(x) for x in prefixes)):
        return False
    if not all(_has(norm, req) for req in model.require):
        return False
    banned = [w for w in GLOBAL_EXCLUDE if w not in model.keep]
    banned += list(CATEGORY_EXCLUDE.get(model.category, ())) + list(model.exclude)
    return not any(_has(norm, word) for word in banned)


# --- 1. anúncio válido no dia ------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    """O que a coleta guarda de um anúncio num dia (K8): só o necessário."""

    code: str
    day: date
    price_full: float | None  # cheio (parcelado em até 10×, principal)
    price_cash: float | None = None  # à vista; só sem relâmpago (2ª linha)
    available: bool = True
    seller: str | None = KABUM_SELLER
    flash_offer: bool = False  # só selo, não exclui
    flash_price: float | None = None  # relâmpago (priceWithDiscount na oferta)
    name: str | None = None


def listing_from_prices(
    code: str,
    day: date,
    prices: dict,
    *,
    flash_offer: bool,
    available: bool = True,
    seller: str | None = KABUM_SELLER,
    name: str | None = None,
    page: str = "search",
) -> Listing:
    """Monta o `Listing` a partir dos preços da busca (padrão) ou do produto.

    Na **busca**, `price` já é o cheio, com ou sem oferta. Na **página de
    produto** (`page="product"`), durante o relâmpago o cheio é `oldPrice`
    (o `price` vira o parcelado da oferta); sem oferta, é `price` — nesse caso
    o `oldPrice` é o "de" riscado ou 0 e inflaria o preço (T27c).
    """
    def _num(key: str) -> float | None:
        value = prices.get(key)
        return float(value) if _finite_positive(value) else None

    if page == "product" and flash_offer:
        full = _num("oldPrice") or _num("price")
    else:
        full = _num("price")
    discount = _num("priceWithDiscount")
    return Listing(
        code=code,
        day=day,
        price_full=full,
        price_cash=None if flash_offer else discount,
        available=available,
        seller=seller,
        flash_offer=flash_offer,
        flash_price=discount if flash_offer else None,
        name=name,
    )


# Motivo de exclusão no dia; `None` em `screen_listing` = passa.
REASONS = {
    "unavailable": "indisponível",
    "seller": "vendido por terceiro",
    "invalid": "preço inválido",
    "out_of_range": "fora da faixa",
    "abnormal": "suspeito: preço anormal",
}


def _finite_positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def screen_listing(listing: Listing, category: str, seller: str | None = KABUM_SELLER,
                   band: str | None = None) -> str | None:
    """Motivo para o anúncio ficar fora da conta no dia, ou `None` se passa.

    `seller=None` aceita qualquer vendedor (marketplace, T35). Com `band`, o
    preço também precisa caber em `band_filter`.
    """
    if not listing.available:
        return "unavailable"
    if seller is not None and (listing.seller or "").strip() != seller:
        return "seller"
    if not _finite_positive(listing.price_full):
        return "invalid"
    # Consistência: à vista e relâmpago nunca acima do cheio.
    for other in (listing.price_cash, listing.flash_price):
        if other is not None and _finite_positive(other) and other > listing.price_full:
            return "invalid"
    lo, hi = PLAUSIBLE_BRL[category]
    if not lo <= listing.price_full <= hi:
        return "out_of_range"
    if band is not None:
        lo, hi = band_filter(category, band)
        if not lo <= listing.price_full <= hi:
            return "out_of_range"
    return None


def screen_abnormal(prices: dict[str, float]) -> set[str]:
    """Anúncios de **um mesmo modelo** que saem da mediana como anormais.

    Acima de `PEER_MAX_RATIO` × ou abaixo de 1/`PEER_MAX_RATIO` da mediana dos
    **outros** anúncios. Com 2 anúncios, os dois a mais de 1,5× um do outro
    saem: não há como saber qual é o certo.
    """
    out: set[str] = set()
    for code, price in prices.items():
        others = [p for c, p in prices.items() if c != code]
        if not others:
            continue
        ref = median(others)
        if price > PEER_MAX_RATIO * ref or price * PEER_MAX_RATIO < ref:
            out.add(code)
    return out


# --- 2–4. preço do modelo -------------------------------------------------------------


@dataclass
class ModelDay:
    model: BasketModel
    day: date
    price: float | None  # mediana do cheio dos anúncios válidos
    cash: float | None = None  # mediana do à vista, só se todo válido tem à vista
    found: int = 0  # anúncios com o nome do modelo
    valid: list[Listing] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)  # motivo → quantos
    marketplace: bool = False  # preço vindo de marketplace (sem KaBuM! válida)
    flash: bool = False  # algum anúncio de referência em relâmpago
    refs: list[Listing] = field(default_factory=list)
    status: str = "ok"  # "ok", "sem_preco_hoje" ou "sem_coleta"


def model_day(model: BasketModel, listings: list[Listing], day: date) -> ModelDay:
    """Preço do modelo no dia: válidos, anormais fora, mediana e referências."""
    result = ModelDay(model, day, None, found=len(listings))

    def _screen(seller: str | None) -> tuple[list[Listing], dict[str, int]]:
        ok, out = [], {}
        for lst in listings:
            reason = screen_listing(lst, model.category, seller, model.band)
            if reason is None:
                ok.append(lst)
            else:
                out[reason] = out.get(reason, 0) + 1
        return ok, out

    valid, excluded = _screen(KABUM_SELLER)
    if not valid:
        # Marketplace só onde a KaBuM! não tem o modelo hoje (T33).
        market, market_excl = _screen(None)
        if market:
            valid, excluded, result.marketplace = market, market_excl, True
    # Código repetido na busca conta uma vez.
    by_code = {lst.code: lst for lst in valid}
    abnormal = screen_abnormal({c: float(l.price_full) for c, l in by_code.items()})  # type: ignore[arg-type]
    if abnormal:
        excluded["abnormal"] = excluded.get("abnormal", 0) + len(abnormal)
    result.valid = [l for c, l in by_code.items() if c not in abnormal]
    result.excluded = excluded
    if not result.valid:
        result.status = "sem_preco_hoje"
        return result
    prices = [float(l.price_full) for l in result.valid]  # type: ignore[arg-type]
    result.price = median(prices)
    cash = [l.price_cash for l in result.valid if _finite_positive(l.price_cash)]
    result.cash = median(cash) if cash and len(cash) == len(result.valid) else None
    result.refs = sorted(result.valid, key=lambda l: (abs(float(l.price_full) - result.price), l.code))[:MAX_REFS]
    result.flash = any(l.flash_offer for l in result.refs)
    return result


# --- 5. faixa e variação pareada --------------------------------------------------


def band_price(model_prices: dict[str, float]) -> float | None:
    """Média simples dos modelos com preço: cada modelo pesa igual."""
    vals = [p for p in model_prices.values() if _finite_positive(p)]
    return sum(vals) / len(vals) if vals else None


def paired_change(before: dict[str, float], now: dict[str, float]) -> float | None:
    """Média das variações % dos modelos presentes nas duas datas."""
    changes = [
        (now[k] / before[k] - 1.0) * 100.0
        for k in now
        if k in before and before[k] > 0 and _finite_positive(now[k])
    ]
    return sum(changes) / len(changes) if changes else None


def prices_on_or_before(
    history: dict[str, list[tuple[date, float]]], keys: list[str], target: date
) -> dict[str, float]:
    """Último preço de cada modelo até `target` (inclusive)."""
    out: dict[str, float] = {}
    for key in keys:
        points = [(d, v) for d, v in history.get(key, []) if d <= target and _finite_positive(v)]
        if points:
            out[key] = max(points)[1]
    return out


def band_change(
    now: dict[str, float], history: dict[str, list[tuple[date, float]]], today: date, days: int = 30
) -> float | None:
    """Variação da faixa em `days` dias, pareada por modelo.

    Cada modelo de hoje contra o seu último preço com pelo menos `days` dias
    de distância. Sem histórico suficiente, `None` — a variação de 30 dias só
    aparece com 30 dias de coleta.
    """
    before = prices_on_or_before(history, list(now), today - timedelta(days=days))
    return paired_change(before, now)


def diff_amd_pct(brand_prices: dict[str, float]) -> float | None:
    """Preço AMD ÷ NVIDIA − 1, em %. Sem uma das marcas, não há diferença."""
    amd, nvidia = brand_prices.get("AMD"), brand_prices.get("NVIDIA")
    if not amd or not nvidia:
        return None
    return (amd / nvidia - 1.0) * 100.0


# --- 6. categoria ------------------------------------------------------------------


@dataclass
class CategoryDay:
    category: str
    day: date
    published: bool
    band_prices: dict[str, float | None]


def category_day(category: str, day: date, band_prices: dict[str, float | None]) -> CategoryDay:
    """A categoria publica com ≥ `MIN_BANDS` faixas com preço no dia."""
    if category in OUT_OF_PRICE_TAB:
        return CategoryDay(category, day, False, band_prices)
    with_price = sum(1 for b in expected_bands(category) if band_prices.get(b) is not None)
    return CategoryDay(category, day, with_price >= MIN_BANDS, band_prices)


# --- 7. visão do snapshot (`GET /api/prices`, backend.md §T28c) -----------------------

STORE_KEY = "kabum.basket"
STORE_URL = "https://www.kabum.com.br/produto/{code}"
BRAND_KEYS = {"NVIDIA": "nvidia", "AMD": "amd"}
BRAND_VIEW_NOTE = (
    "Compara a média dos modelos de cada marca na faixa, não o custo por "
    "desempenho. Intel Arc entra na faixa, mas não nesta comparação."
)
MARKETPLACE_WARNING = {"code": "marketplace", "text": "inclui anúncio de marketplace"}
_MODEL_STATUS = {"ok": "valid", "sem_preco_hoje": "no_price", "sem_coleta": "no_data"}


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _ipca_block(cat: Any, collected: dict) -> dict:
    """IPCA do subitem da categoria; `subitem` nulo quando não há subitem."""
    block = {"subitem": cat.ipca_subitem, "label": "sem subitem", "is_proxy": cat.ipca_is_proxy,
             "period": None, "change_12m_pct": None, "status": "unavailable"}
    if not cat.ipca_subitem:
        return block
    fetched = collected.get("ibge.ipca_hardware")
    slot = ((getattr(fetched, "payload", None) or {}).get(cat.ipca_subitem)
            if fetched is not None and fetched.ok else None)
    if not slot:
        block["status"] = getattr(fetched, "status", "unavailable") if fetched else "unavailable"
        return block
    yoy = slot.get("yoy") or []
    monthly = slot.get("monthly") or []
    block.update(
        label=slot.get("label") or "—",
        period=(yoy or monthly)[-1][0] if (yoy or monthly) else None,
        change_12m_pct=_round(yoy[-1][1]) if yoy else None,
        status=fetched.status,
    )
    return block


def _listing_from_row(row: dict, day: date) -> Listing | None:
    """`Listing` a partir de um anúncio de `payload["models"][i]["items"]`."""
    code = str(row.get("code") or "")
    if not code.isdigit():
        return None

    def _num(key: str) -> float | None:
        value = row.get(key)
        return float(value) if _finite_positive(value) else None

    return Listing(
        code=code,
        day=day,
        price_full=_num("price_full"),
        price_cash=_num("price_cash"),
        available=row.get("available") is True,
        seller=row.get("seller") if isinstance(row.get("seller"), str) else None,
        flash_offer=row.get("flash_offer") is True,
        flash_price=_num("flash_price"),
        name=row.get("name") if isinstance(row.get("name"), str) else None,
    )


def model_series(key: str) -> str:
    """Série interna do preço do modelo (fora do catálogo público)."""
    return f"kabum_model.{key}"


# Idade máxima da coleta exibida como preço atual: a loja coleta 1 vez por
# semana (Backend, 05/11), e a T35c completa a cesta em mais de um dia.
MAX_COLLECTION_AGE_DAYS = 8


def _collected_models(payload: dict, today: date) -> dict[str, ModelDay]:
    """`ModelDay` de cada modelo da cesta na coleta em vigor (até 8 dias).

    Só recebe payload de coleta `ok`; um `stale` (coleta nova falhou) não
    chega aqui, então preço antigo nunca é exibido como o da coleta atual.
    """
    out: dict[str, ModelDay] = {}
    for row in payload.get("models") or []:
        if not isinstance(row, dict):
            continue
        model = BASKET_BY_KEY.get(str(row.get("key") or ""))
        if model is None:
            continue
        try:
            day = date.fromisoformat(str(row.get("day")))
        except ValueError:
            continue
        if not 0 <= (today - day).days <= MAX_COLLECTION_AGE_DAYS:
            continue
        if row.get("status") == "empty":  # busca sem lista: sem anúncio hoje
            out[model.key] = ModelDay(model, day, None, status="sem_preco_hoje")
            continue
        if row.get("status") != "ok":
            out[model.key] = ModelDay(model, day, None, status="sem_coleta")
            continue
        listings = [l for r in row.get("items") or [] if isinstance(r, dict)
                    if (l := _listing_from_row(r, day)) is not None and match_name(model, l.name)]
        out[model.key] = model_day(model, listings, day)
    return out


def _ref_offer(lst: Listing, md: ModelDay, category: str) -> dict:
    """Anúncio de referência (até 3 por modelo); o link é montado pelo `code`."""
    return {
        "code": lst.code,
        "name": lst.name,
        "brand": BRAND_KEYS.get(md.model.brand) if category == "gpu" else None,
        "model": md.model.model,
        "model_key": md.model.key,
        "price_full_brl": _round(lst.price_full),
        "price_cash_brl": _round(lst.price_cash),
        "flash_offer": lst.flash_offer,
        "flash_price_brl": _round(lst.flash_price),
        "status": "valid",
        # Selo "marketplace" (T33). `seller` é texto da loja já limpo pelo
        # provider; a tela insere como texto (K18).
        "marketplace": (lst.seller or "") != KABUM_SELLER,
        "seller": lst.seller,
        "url": STORE_URL.format(code=lst.code),
    }


def build_prices_view(
    collected: dict,
    listings_by_code: dict | None,
    today: date,
    model_history: dict[str, list[tuple[date, float]]] | None = None,
) -> dict:
    """Preço por categoria e faixa no formato do `GET /api/prices`.

    `collected["kabum.basket"]` traz a coleta do dia (1 busca por modelo).
    `model_history` traz o preço de cada modelo nos dias anteriores
    (`model_series(key)` → [(dia, preço)]), para a variação pareada de 30
    dias. `listings_by_code` é da cesta por URL (até a T33b) e é ignorado.
    """
    from .catalog import CATEGORIES

    fetched = collected.get(STORE_KEY)
    payload = (fetched.payload if fetched is not None and fetched.ok
               and isinstance(fetched.payload, dict) else {}) or {}
    status = fetched.status if fetched is not None else "disabled"
    other_basket = bool(payload) and payload.get("cache_version") != BASKET_VERSION
    usable = payload if status == "ok" and not other_basket else {}
    days = _collected_models(usable, today)
    history = {k: [(d, float(v)) for d, v in pts] for k, pts in (model_history or {}).items()}

    def _hist(md_key: str) -> list[tuple[date, float]]:
        return [(d, v) for d, v in history.get(model_series(md_key), []) if d < today]

    model_hist = {m.key: _hist(m.key) for m in BASKET}
    tracked = sum(len(models_for(c.key, b)) for c in CATEGORIES for b in expected_bands(c.key))
    priced_total = 0
    categories: list[dict] = []
    series_values: dict[str, float] = {}
    gpu_models: dict[str, list[ModelDay]] = {}
    means: dict[str, float] = {}

    for cat in CATEGORIES:
        ipca_only = cat.key in OUT_OF_PRICE_TAB
        entry: dict = {"key": cat.key, "label": cat.label, "ipca_only": ipca_only, "published": False,
                       "warnings": [], "ipca": _ipca_block(cat, collected), "tiers": []}
        if ipca_only or status == "disabled":
            categories.append(entry)
            continue
        band_prices: dict[str, float | None] = {}
        for band in expected_bands(cat.key):
            planned = models_for(cat.key, band)
            mds = [days.get(m.key) or ModelDay(m, today, None, status="sem_coleta") for m in planned]
            now = {md.model.key: md.price for md in mds if md.price is not None}
            price = band_price(now)
            band_prices[band] = price
            priced_total += len(now)
            lo, hi = display_range(cat.key, band)

            models_out, offers = [], []
            for md in mds:
                series = model_series(md.model.key)
                if md.price is not None:
                    series_values[series] = round(md.price, 2)
                before = prices_on_or_before(model_hist, [md.model.key], today - timedelta(days=30))
                change = paired_change(before, {md.model.key: md.price} if md.price else {})
                refs = [_ref_offer(l, md, cat.key) for l in md.refs]
                offers.extend(refs)
                models_out.append({
                    "key": md.model.key,
                    "model": md.model.model,
                    "brand": md.model.brand,
                    "term": md.model.term,
                    "price_full_brl": _round(md.price),
                    "price_cash_brl": _round(md.cash),
                    "change_30d_pct": _round(change),
                    "listings": {"found": md.found, "valid": len(md.valid)},
                    "excluded": dict(md.excluded),
                    "marketplace": md.marketplace,
                    "flash_offer": md.flash,
                    "status": _MODEL_STATUS.get(md.status, md.status),
                    "series": series,
                    "refs": refs,
                })

            warnings: list[dict] = []
            if price is None:
                warnings.append({"code": "no_price", "text": "sem preço hoje"})
            elif len(now) < len(planned):
                warnings.append({"code": "partial", "text": f"{len(now)} de {len(planned)} modelos"})
            if any(md.marketplace for md in mds if md.price is not None):
                warnings.append(dict(MARKETPLACE_WARNING))
            series = f"price.{cat.key}.{band}"
            if price is not None:
                series_values[series] = round(price, 2)
            change = band_change(now, model_hist, today)
            entry["tiers"].append({
                "tier": band,
                "label": BAND_LABELS[band],
                "range_brl": {"min": lo, "max": hi},
                "price_full_brl": _round(price),
                # À vista só quando todo modelo com preço tem à vista.
                "price_cash_brl": _round(band_price({md.model.key: md.cash for md in mds if md.cash}))
                if now and all(md.cash for md in mds if md.price is not None) else None,
                "change_30d_pct": _round(change),
                # Desde a T35 conta modelos, não anúncios.
                "listings": {"tracked": len(planned), "valid": len(now), "unit": "models"},
                "status": "ok" if price is not None else "sem_preco_hoje",
                "warnings": warnings,
                "series": series,
                "models": models_out,
                "offers": offers,
            })
            if cat.key == "gpu":
                gpu_models[band] = mds
        day_cat = category_day(cat.key, today, band_prices)
        entry["published"] = day_cat.published
        if not day_cat.published:
            entry["warnings"].append({"code": "category_unpublished", "text": "menos de 2 faixas com preço hoje"})
        with_price = [p for p in band_prices.values() if p is not None]
        if with_price:
            means[cat.key] = round(sum(with_price) / len(with_price), 2)
        categories.append(entry)

    brand_tiers = []
    for band in BANDS:
        if band not in gpu_models:
            continue
        mds = gpu_models[band]
        cells: dict[str, dict | None] = {}
        brand_prices: dict[str, float] = {}
        for brand, key in BRAND_KEYS.items():
            mine = [md for md in mds if md.model.brand == brand]
            if not mine:
                cells[key] = None
                continue
            now = {md.model.key: md.price for md in mine if md.price is not None}
            price = band_price(now)
            if price is not None:
                brand_prices[brand] = price
            series = f"price.gpu.{band}.{key}"
            if price is not None:
                series_values[series] = round(price, 2)
            warn = []
            if price is None:
                warn.append({"code": "no_price", "text": "sem preço hoje"})
            elif len(now) < len(mine):
                warn.append({"code": "partial", "text": f"{len(now)} de {len(mine)} modelos"})
            cells[key] = {
                "model": " · ".join(md.model.model for md in mine),
                "price_full_brl": _round(price),
                "change_30d_pct": _round(band_change(now, model_hist, today)),
                "listings": {"tracked": len(mine), "valid": len(now), "unit": "models"},
                "warnings": warn,
                "series": series,
            }
        diff = diff_amd_pct(brand_prices) if cells.get("nvidia") and cells.get("amd") else None
        tier_warn = [{"code": "no_model", "text": f"{brand}: sem modelo nesta faixa"}
                     for brand, key in BRAND_KEYS.items() if cells.get(key) is None]
        diff_series = f"price.gpu.{band}.diff_amd_pct" if cells.get("nvidia") and cells.get("amd") else None
        if diff is not None and diff_series:
            series_values[diff_series] = round(diff, 2)
        brand_tiers.append({"tier": band, "nvidia": cells.get("nvidia"), "amd": cells.get("amd"),
                            "diff_amd_pct": _round(diff), "diff_series": diff_series, "warnings": tier_warn})

    reason = None
    if status == "disabled":
        reason = "coleta da KaBuM desligada (DSH_ENABLE_KABUM e DSH_CONTACT)"
    elif fetched is not None and not fetched.ok:
        reason = fetched.error
    elif other_basket:
        reason = "a coleta guardada é de outra versão da cesta; aguardando a nova coleta"
    elif status == "stale":
        reason = "coleta de hoje falhou; nenhum preço de dias anteriores é exibido como de hoje"
    return {
        "day": today.isoformat(),
        "source": {
            "key": "kabum",
            "label": PRICE_LABEL,
            "note": PRICE_NOTE.format(models=tracked),
            "status": status,
            "status_reason": reason,
            "as_of": fetched.as_of.isoformat() if fetched is not None and fetched.as_of else None,
            "basket_version": BASKET_VERSION,
            # Desde a T35 contam modelos buscados e modelos com preço.
            "listings_tracked": tracked,
            "listings_valid": priced_total,
            "unit": "models",
        },
        "tiers": [{"key": b, "label": BAND_LABELS[b].capitalize()} for b in BANDS],
        "categories": categories,
        "brand_view": {
            "category": "gpu",
            "brands": [{"key": "nvidia", "label": "NVIDIA"}, {"key": "amd", "label": "AMD"}],
            "note": BRAND_VIEW_NOTE,
            "tiers": brand_tiers,
        },
        "technical": {"mean_of_tiers_brl": means},
        "series_values": series_values,
    }
