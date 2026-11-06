"""Digest editorial das manchetes: deduplicação, procedência e corroboração.

Não existe algoritmo que prove que uma notícia é verdadeira. O que dá para
fazer com honestidade — e sem inventar um "detector de fake news" — é:

1. **Descartar o que não é reportagem**: comunicado de imprensa distribuído
   por agência paga e agregador/redirecionador não passaram por apuração
   editorial independente.
2. **Aceitar só inglês, português ou espanhol**: o leitor precisa conseguir
   conferir a fonte sem tradução automática; idioma ausente também é descartado.
3. **Deduplicar a mesma matéria republicada**: URL canônica + impressão
   digital do título normalizado.
4. **Agrupar a mesma história em veículos diferentes** e contar quantos
   domínios distintos a cobriram. Além das palavras do título, o agrupamento
   compara entidades que não mudam com o idioma — empresas, tickers, países
   e temas (memória, preço, controle de exportação…) —, para que a mesma
   história em inglês, português e espanhol conte como uma só.
5. **Exigir relação direta com preço de hardware** (`is_price_relevant`): o
   título precisa citar a cadeia de hardware *e* um mecanismo de preço/oferta,
   ou um choque de oferta que já é, por si, um dos vetores do índice. Review,
   oferta de loja, streaming, sorteio e comunicado ficam fora.
6. **Variar as fontes**: cada veículo aparece no máximo duas vezes, e a
   primeira página (5 itens) prioriza veículos distintos.
7. **Rotular cada item**: `corroborated` (≥ 2 domínios) ou `single-source`.
   Fonte única não é sinônimo de falsa; é ausência de segunda checagem no
   recorte.
8. **Fechar o conjunto com um digest SHA-256** sobre as impressões digitais
   exibidas, para auditoria e para detectar que o conjunto mudou.

O módulo é puro (sem rede, sem I/O) justamente para poder ser testado offline.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --- classificação de domínio ------------------------------------------------

# Conteúdo que não é reportagem apurada. A lista é estrutural, não um juízo
# sobre a linha editorial de ninguém: são agências de release e agregadores.
BLOCKED_DOMAINS = frozenset(
    {
        # comunicado de imprensa / distribuição paga
        "prnewswire.com",
        "businesswire.com",
        "globenewswire.com",
        "accesswire.com",
        "einpresswire.com",
        "newsfilecorp.com",
        "openpr.com",
        "pressreleasepoint.com",
        # agregador / redirecionador (não é a fonte original)
        "news.google.com",
        "msn.com",
        "newsnow.co.uk",
        "flipboard.com",
        "smartnews.com",
        "biztoc.com",
        "newsbreak.com",
    }
)

# Agências e veículos de referência. Não é endosso: é só prioridade de exibição.
WIRE_DOMAINS = frozenset({"reuters.com", "apnews.com", "afp.com"})
QUALITY_DOMAINS = frozenset(
    {
        "bloomberg.com",
        "ft.com",
        "wsj.com",
        "nytimes.com",
        "washingtonpost.com",
        "theguardian.com",
        "cnn.com",
        "economist.com",
        "bbc.com",
        "bbc.co.uk",
        "cnbc.com",
        "nikkei.com",
        "asia.nikkei.com",
        "scmp.com",
        "aljazeera.com",
        "dw.com",
        "lemonde.fr",
        "spiegel.de",
        "elpais.com",
        # Vale do Silício
        "techcrunch.com",
        "theverge.com",
        "wired.com",
        "stratechery.com",
        # Europa e leste europeu
        "politico.eu",
        "euronews.com",
        "kyivindependent.com",
        "notesfrompoland.com",
        "balkaninsight.com",
        "emerging-europe.com",
        # Ásia
        "thediplomat.com",
        "channelnewsasia.com",
        # análise
        "theconversation.com",
        "lowyinstitute.org",
        "project-syndicate.org",
        "chinatalk.media",
    }
)
TRADE_DOMAINS = frozenset(
    {
        "tomshardware.com",
        "theregister.com",
        "arstechnica.com",
        "eetimes.com",
        "digitimes.com",
        "semianalysis.com",
        "anandtech.com",
        "techpowerup.com",
        "wccftech.com",
        "semiengineering.com",
        "ieee.org",
        "datacenterdynamics.com",
        "lightreading.com",
        "spglobal.com",
        "hellenicshippingnews.com",
        "gcaptain.com",
        "mining.com",
    }
)
BR_DOMAINS = frozenset(
    {
        "valor.globo.com",
        "folha.uol.com.br",
        "estadao.com.br",
        "g1.globo.com",
        "infomoney.com.br",
        "exame.com",
        "tecmundo.com.br",
        "olhardigital.com.br",
        "canaltech.com.br",
        "tecnoblog.net",
        "gazetadopovo.com.br",
        "brasil247.com",
    }
)

TIER_RANK = {"wire": 0, "quality": 1, "br": 1, "trade": 2, "unknown": 3, "blocked": 9}

# O painel é publicado em português e só aceita material que o leitor consiga
# conferir sem tradução automática. Inglês, português e espanhol cobrem as
# fontes usadas; qualquer outro idioma (ou idioma ausente) fica de fora.
ALLOWED_LANGUAGES = frozenset({"en", "pt", "es"})

_LANGUAGE_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "portugues": "pt",
    "português": "pt",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "espanol": "es",
    "español": "es",
}


def language_code(value: str | None) -> str | None:
    """Normaliza 'English', 'en-US', 'pt_BR' etc. para en/pt/es.

    Ausente ou desconhecido devolve ``None``: o chamador deve descartar o item,
    em vez de adivinhar o idioma pelo título.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    first = re.split(r"[-_]", raw, maxsplit=1)[0]
    code = _LANGUAGE_ALIASES.get(raw) or _LANGUAGE_ALIASES.get(first)
    return code if code in ALLOWED_LANGUAGES else None


# Parâmetros de rastreio que não mudam o conteúdo da página.
_TRACKING = re.compile(
    r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$|ref$|source$|s_cid$|igshid$|"
    r"__twitter_impression$|cmpid$|ncid$|taid$)",
    re.IGNORECASE,
)

# Palavras que não ajudam a identificar a mesma história (pt + en).
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "these", "those",
        "are", "was", "were", "has", "have", "had", "will", "would", "can",
        "could", "should", "its", "their", "after", "before", "over", "under",
        "into", "about", "than", "more", "less", "new", "says", "said", "amid",
        "what", "why", "how", "who", "when", "where", "not", "but", "you",
        "your", "our", "they", "them", "his", "her", "she", "its", "been",
        "being", "just", "now", "still", "may", "might", "also", "very",
        "para", "com", "por", "dos", "das", "uma", "que", "não", "mais",
        "como", "sobre", "após", "entre", "sem", "foi", "são", "ser", "tem",
        "ter", "pelo", "pela", "nos", "nas", "aos", "pode", "ainda", "já",
        "enquanto", "contra", "desde", "até", "isso", "este", "esta",
    }
)


def base_domain(domain: str) -> str:
    """`WWW.Exemplo.com.` → `exemplo.com`."""
    d = (domain or "").strip().lower().rstrip(".")
    return d.removeprefix("www.")


def host_from_url(url: str) -> str:
    try:
        return base_domain(urlsplit(url).hostname or "")
    except ValueError:
        return ""


def domain_tier(domain: str) -> str:
    d = base_domain(domain)
    if not d:
        return "unknown"
    for tier, domains in (
        ("blocked", BLOCKED_DOMAINS),
        ("wire", WIRE_DOMAINS),
        ("quality", QUALITY_DOMAINS),
        ("trade", TRADE_DOMAINS),
        ("br", BR_DOMAINS),
    ):
        if any(d == x or d.endswith("." + x) for x in domains):
            return tier
    return "unknown"


def canonical_url(url: str) -> str:
    """Normaliza a URL para comparar republicações da mesma matéria."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING.match(k)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        ("https", host_from_url(raw) or (parts.hostname or ""), path, urlencode(query), "")
    )


def normalize_title(title: str) -> str:
    """Minúsculas, sem acento e sem pontuação — para comparação, não exibição."""
    s = unicodedata.normalize("NFKD", title or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def title_tokens(title: str) -> set[str]:
    return {
        t
        for t in normalize_title(title).split()
        if len(t) >= 4 and t not in _STOPWORDS and not t.isdigit()
    }


def fingerprint(title: str, url: str) -> str:
    """Impressão curta do par título+URL canônica; é o que entra no digest."""
    raw = f"{normalize_title(title)}|{canonical_url(url)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _similar(a: str, b: str) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    shared = len(ta & tb)
    if shared < 2:
        return False
    return shared / len(ta | tb) >= 0.5


# --- relevância para a tendência de preço -----------------------------------
#
# A decisão olha só o título: é o que o leitor vê, e nem todo feed entrega
# resumo. Comparação sem acento, minúscula e com fronteira de palavra.


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _words(*terms: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(fold(t)) for t in terms) + r")\b")


# --- entidades independentes de idioma --------------------------------------
#
# A mesma história em outro idioma quase não divide palavras com o original,
# mas divide os nomes próprios e o tema. Cada alias aponta para uma chave
# canônica; o agrupamento compara as chaves, nunca o texto.

_COMPANY_ALIASES = {
    "apple": ("apple",),
    "nvidia": ("nvidia",),
    "amd": ("amd", "radeon"),
    "intel": ("intel",),
    "micron": ("micron",),
    "samsung": ("samsung",),
    "sk_hynix": ("sk hynix", "hynix"),
    "tsmc": ("tsmc",),
    "asml": ("asml",),
    "kioxia": ("kioxia",),
    "cxmt": ("cxmt", "changxin"),
    "ymtc": ("ymtc", "yangtze memory"),
    "huawei": ("huawei",),
    "qualcomm": ("qualcomm",),
    "microsoft": ("microsoft",),
    "google": ("google", "alphabet"),
    "amazon": ("amazon", "aws"),
    "meta": ("meta platforms",),
    "oracle": ("oracle",),
    "openai": ("openai",),
    "sony": ("sony", "playstation"),
    "nintendo": ("nintendo",),
    "xiaomi": ("xiaomi",),
    "team_group": ("team group", "teamgroup"),
    "western_digital": ("western digital",),
    "seagate": ("seagate",),
    "foxconn": ("foxconn", "hon hai"),
    "nexperia": ("nexperia",),
}
# Ticker só vale em maiúsculas, para "MU" não casar com palavra comum.
_TICKERS = {
    "AAPL": "apple", "NVDA": "nvidia", "AMD": "amd", "INTC": "intel",
    "MU": "micron", "TSM": "tsmc", "ASML": "asml", "MSFT": "microsoft",
    "GOOGL": "google", "GOOG": "google", "AMZN": "amazon", "META": "meta",
    "ORCL": "oracle", "QCOM": "qualcomm", "WDC": "western_digital",
    "STX": "seagate",
}
_COUNTRY_ALIASES = {
    "china": ("china", "chinese", "chinesa", "chines", "chinesas", "chineses",
              "chino", "china's", "beijing", "pequim"),
    "taiwan": ("taiwan", "taiwanese", "taiwanes", "taiwanesa", "taiwán", "taipei"),
    "japan": ("japan", "japanese", "japao", "japones", "japonesa", "japon", "tokyo", "toquio"),
    "korea": ("korea", "korean", "coreia", "coreano", "coreana", "corea", "seoul", "seul"),
    "usa": ("united states", "american", "americano", "americana", "eua",
            "estados unidos", "eeuu", "washington", "white house", "casa branca"),
    "brazil": ("brazil", "brazilian", "brasil", "brasileiro", "brasileira"),
    "netherlands": ("netherlands", "dutch", "holanda", "paises baixos", "paises bajos"),
    "russia": ("russia", "russian", "russo", "russa", "rusia", "ruso"),
    "ukraine": ("ukraine", "ukrainian", "ucrania", "ucraniano"),
    "iran": ("iran", "iranian", "ira", "irani", "iraniano"),
    "qatar": ("qatar", "catar", "qatari"),
    "india": ("india", "indian", "indiano"),
    "mexico": ("mexico", "mexican", "mexicano"),
    "europe": ("europe", "european", "europa", "europeu", "europeia", "europeo"),
}
# "US" e "U.S." só em maiúsculas: "us" minúsculo é pronome em inglês.
_USA_RAW = re.compile(r"\bU\.?S\.?(?=[\s,;:'’-]|$)|\bUSA\b")

# Temas: genérico (aparece em quase toda manchete do recorte) pesa menos.
_GENERIC_TOPICS = {
    "chip": ("chip", "chips", "semiconductor", "semiconductors", "semicondutor",
             "semicondutores", "semiconductor", "semiconductores"),
    "memory": ("memory", "memoria", "memorias", "ram", "dram", "ddr4", "ddr5",
               "nand", "flash"),
    "price": ("price", "prices", "pricing", "cost", "costs", "preco", "precos",
              "custo", "custos", "precio", "precios", "costo", "costos"),
}
_SPECIFIC_TOPICS = {
    "hbm": ("hbm", "hbm3", "hbm3e", "hbm4"),
    "gpu": ("gpu", "gpus", "graphics card", "graphics cards", "placa de video",
            "placas de video", "tarjeta grafica", "tarjetas graficas", "geforce", "rtx"),
    "shortage": ("shortage", "shortages", "crisis", "crise", "escassez", "escasez",
                 "falta", "scarcity"),
    "export_control": ("export control", "export controls", "trade control",
                       "chip curbs", "curbs", "entity list", "controle de exportacao",
                       "controles de exportacao", "control de exportaciones",
                       "controles a la exportacion", "restricoes de exportacao"),
    "tariff": ("tariff", "tariffs", "tarifa", "tarifas", "arancel", "aranceles"),
    "smuggling": ("smuggler", "smugglers", "smuggling", "smuggled", "contrabando",
                  "contrabandistas"),
    "earnings": ("earnings", "revenue", "margins", "margin", "quarterly results",
                 "balanco", "receita", "lucro", "margem", "margens", "ingresos",
                 "ganancias", "resultados"),
    "earthquake": ("earthquake", "quake", "terremoto", "sismo"),
    "rare_earth": ("rare earth", "rare earths", "terras raras", "tierras raras"),
    "helium": ("helium", "helio"),
    "hormuz": ("hormuz", "ormuz"),
    "capacity": ("capacity", "capacidade", "capacidad"),
}


def _alias_patterns(table: dict[str, tuple[str, ...]]) -> list[tuple[str, re.Pattern[str]]]:
    return [(key, _words(*aliases)) for key, aliases in table.items()]


_COMPANY_PATTERNS = _alias_patterns(_COMPANY_ALIASES)
_COUNTRY_PATTERNS = _alias_patterns(_COUNTRY_ALIASES)
_GENERIC_PATTERNS = _alias_patterns(_GENERIC_TOPICS)
_SPECIFIC_PATTERNS = _alias_patterns(_SPECIFIC_TOPICS)
_TICKER_RE = re.compile(r"\b(" + "|".join(_TICKERS) + r")\b")


def story_keys(title: str) -> dict[str, frozenset[str]]:
    """Empresas, países e temas citados no título, como chaves canônicas.

    O resultado é o mesmo para a mesma manchete em en/pt/es, desde que os
    termos estejam nas tabelas acima. Ticker só conta em maiúsculas.
    """
    raw = title or ""
    text = fold(raw)

    def _match(patterns: list[tuple[str, re.Pattern[str]]]) -> set[str]:
        return {key for key, pattern in patterns if pattern.search(text)}

    companies = _match(_COMPANY_PATTERNS)
    companies |= {_TICKERS[t] for t in _TICKER_RE.findall(raw)}
    countries = _match(_COUNTRY_PATTERNS)
    if _USA_RAW.search(raw):
        countries.add("usa")
    return {
        "companies": frozenset(companies),
        "countries": frozenset(countries),
        "generic": frozenset(_match(_GENERIC_PATTERNS)),
        "specific": frozenset(_match(_SPECIFIC_PATTERNS)),
    }


# Pesos do agrupamento por entidade. Empresa identifica a história; país e
# tema específico ajudam; tema genérico (chip, memória, preço) quase todo
# título do recorte tem. Ver `same_story_by_keys`.
KEY_WEIGHTS = {"companies": 2.0, "countries": 1.0, "specific": 1.0, "generic": 0.5}
KEY_MIN_SCORE = 3.0
KEY_MIN_JACCARD = 0.5
# Mesma história sai em dias próximos; acima disso é outro capítulo.
KEY_MAX_HOURS = 72.0


def different_companies(
    a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]
) -> bool:
    """Os dois títulos nomeiam empresas e nenhuma é comum: histórias diferentes."""
    return bool(a["companies"] and b["companies"] and not a["companies"] & b["companies"])


def same_story_by_keys(
    a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]
) -> bool:
    """Mesma história pelas entidades, independente do idioma.

    Regras, todas obrigatórias:

    * os dois títulos que citam empresa precisam dividir pelo menos uma —
      empresas diferentes são histórias diferentes;
    * sem empresa em comum, são precisos dois países em comum;
    * pelo menos um tema em comum — quem e onde sem o quê não basta;
    * a soma ponderada do que é comum chega a `KEY_MIN_SCORE`;
    * as chaves em comum são ao menos metade da união (Jaccard).

    O desenho prefere não agrupar a agrupar errado: um agrupamento errado
    daria o selo "confirmada" a uma história que só um veículo publicou.
    """
    shared = {kind: a[kind] & b[kind] for kind in KEY_WEIGHTS}
    if different_companies(a, b):
        return False
    if not shared["companies"] and len(shared["countries"]) < 2:
        return False
    if not (shared["generic"] or shared["specific"]):
        return False
    score = sum(KEY_WEIGHTS[kind] * len(keys) for kind, keys in shared.items())
    if score < KEY_MIN_SCORE:
        return False
    union = sum(len(a[kind] | b[kind]) for kind in KEY_WEIGHTS)
    inter = sum(len(keys) for keys in shared.values())
    return bool(union) and inter / union >= KEY_MIN_JACCARD


def _close_in_time(a: dict, b: dict) -> bool:
    ta, tb = _ts(a.get("seen_at")), _ts(b.get("seen_at"))
    if not ta or not tb:
        return True  # sem data não dá para separar pelo tempo
    return abs(ta - tb) <= KEY_MAX_HOURS * 3600


# Choques de oferta que já são vetores do índice: bastam sozinhos.
_SUPPLY_SHOCK = _words(
    "rare earth", "rare earths", "terras raras", "tierras raras",
    "helium shortage", "helium supply", "escassez de helio", "falta de helio",
    "strait of hormuz", "hormuz", "estreito de ormuz", "ormuz",
    "taiwan strait", "estreito de taiwan", "taiwan earthquake", "terremoto em taiwan",
    "export control", "export controls", "export ban", "entity list",
    "controle de exportacao", "controles de exportacao",
    "chip shortage", "chip shortages", "memory shortage", "dram shortage",
    "escassez de chips", "falta de chips", "escassez de memoria",
    # Gás de litografia; Ucrânia e Rússia foram os grandes fornecedores.
    "neon gas", "neon supply", "neon shortage", "gas neon", "gas neonio",
    # Mecanismos que mudam o preço de importado no Brasil.
    "remessa conforme", "taxa das blusinhas", "imposto de importacao",
    "lei de informatica",
)

# Elo da cadeia de hardware, em três forças. Componente e produto final já
# são o próprio objeto do preço; fabricante e datacenter aparecem também em
# notícia de política, energia e balanço, então exigem um termo mais forte.
_COMPONENT = _words(
    "chip", "chips", "semiconductor", "semiconductors", "semicondutor",
    "semicondutores", "semiconductores", "wafer", "wafers", "dram", "nand",
    "hbm", "gddr6", "gddr7", "ram", "memory", "memoria", "memorias", "ssd",
    "ssds", "pcb", "pcbs", "gpu", "gpus", "graphics card", "graphics cards",
    "placa de video", "placas de video", "placa-mae", "motherboard",
    "motherboards", "processor", "processors", "processador", "processadores",
    "cpu", "cpus", "smartphone", "smartphones", "celular", "celulares",
    "laptop", "laptops", "notebook", "notebooks", "pc", "pcs", "computer",
    "computers", "computador", "computadores", "console", "consoles",
    "electronics", "eletronicos", "electronicos", "hardware",
)
_MAKER = _words(
    "chipmaker", "chipmakers", "foundry", "foundries", "fab", "fabs",
    "lithography", "litografia", "tsmc", "sk hynix", "hynix", "micron",
    "kioxia", "asml", "nvidia", "amd", "intel", "samsung electronics",
)
_DATACENTER = _words(
    "data center", "data centers", "datacenter", "datacenters",
    "hyperscaler", "hyperscalers",
)

# Termo forte de preço: fala de preço, custo ou escassez sem ambiguidade.
_PRICE_TERMS = _words(
    "price", "prices", "pricing", "priced", "cost", "costs", "costlier",
    "expensive", "pricier", "shortage", "shortages", "shortfall",
    "inflation", "hike", "hikes", "rationing", "sold out", "msrp",
    "preco", "precos", "custo", "custos", "caro", "caros", "encarece",
    "encarecem", "encarecer", "reajuste", "escassez", "falta", "esgotado",
    "esgotados", "esgotada", "esgotadas", "esgota", "esgotam", "inflacao",
    "precio", "precios", "escasez",
)
# Termo forte de restrição: mexe na oferta por regra, tarifa ou choque físico.
_RESTRICTION_TERMS = _words(
    "tariff", "tariffs", "duty", "duties", "ban", "bans", "banned",
    "restriction", "restrictions", "curb", "curbs", "sanction", "sanctions",
    "embargo", "quota", "quotas", "blockade", "earthquake",
    "tarifa", "tarifas", "imposto", "impostos", "restricao", "restricoes",
    "sancao", "sancoes", "proibicao", "bloqueio", "terremoto", "aranceles",
    "arancel",
)
# Termo fraco: oferta e demanda em sentido amplo (capacidade, estoque, alta).
_PRICE_WEAK = _words(
    "supply", "supplies", "capacity", "output", "production", "inventory",
    "inventories", "demand", "surge", "surges", "soar", "soars", "spike",
    "spikes", "rise", "rises", "rising", "climb", "climbs", "climbing",
    "allocation", "backlog", "lead time", "lead times", "disruption",
    "disruptions", "dries up", "import", "imports", "importacao",
    "importacoes", "importados", "dolar", "cambio", "alta", "aumento",
    "aumentos", "estoque",
    "estoques", "producao", "capacidade", "demanda", "dispara", "disparam",
    "sobe", "sobem", "interrupcao",
)

# O que nunca é sinal de tendência: análise de produto, varejo, entretenimento,
# promoção e comunicado. Aplicado antes de tudo — um "review" com "preço" no
# título continua sendo review.
_NOT_TREND = _words(
    "review", "reviews", "hands-on", "hands on", "unboxing", "trailer",
    "gameplay", "walkthrough", "how to", "the best", "best deals", "deal",
    "deals", "coupon",
    "giveaway", "sweepstakes", "streaming", "netflix", "prime video",
    "disney", "hbo", "spotify", "episode", "season", "movie", "movies",
    "anime", "game pass", "pre-load", "preload", "black friday",
    "black november", "cyber monday", "prime day", "at amazon", "at walmart",
    "at best buy", "on amazon", "na amazon", "no mercado livre", "na shopee",
    "analise", "resenha", "cupom", "desconto", "descontos", "promocao",
    "promocoes", "oferta", "ofertas", "sorteio", "episodio", "temporada",
    "filme", "filmes",
)
_NOT_TREND_RAW = ("% off", "save $", "(pr)", "[pr]", "| review", "review:")


def is_price_relevant(title: str) -> bool:
    """True quando o título tem relação direta com a tendência de preço.

    Regra: nada de review/varejo/entretenimento; aceita choque de oferta que
    já é vetor do índice; componente + qualquer termo de preço/oferta;
    fabricante + termo forte ou dois fracos; datacenter + termo de preço
    (regra local e licença de datacenter não mexem no preço do hardware).
    """
    text = fold(title)
    if not text or any(token in text for token in _NOT_TREND_RAW):
        return False
    if _NOT_TREND.search(text):
        return False
    if _SUPPLY_SHOCK.search(text):
        return True
    price = bool(_PRICE_TERMS.search(text))
    strong = price or bool(_RESTRICTION_TERMS.search(text))
    weak = len(set(_PRICE_WEAK.findall(text)))
    if _COMPONENT.search(text):
        return strong or weak >= 1
    if _MAKER.search(text):
        return strong or weak >= 2
    if _DATACENTER.search(text):
        return price
    return False


def _ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# Variedade: no máximo duas matérias por veículo, e a primeira rodada da
# seleção pega uma por veículo — a primeira página nunca é um veículo só.
MAX_PER_DOMAIN = 2
# Artigos de análise (kind="analysis") ganham vagas próprias: saem com menos
# frequência que notícia e perderiam sempre na ordenação por data.
MAX_ANALYSIS = 3
FIRST_PAGE = 5


def _diverse(items: list[dict], limit: int) -> list[dict]:
    """Seleciona em rodadas: 1ª matéria de cada veículo, depois a 2ª."""
    shown: list[dict] = []
    for round_ in range(1, MAX_PER_DOMAIN + 1):
        used: dict[str, int] = {}
        for item in shown:
            used[item["domain"]] = used.get(item["domain"], 0) + 1
        for item in items:
            if len(shown) >= limit:
                return shown
            if item in shown or used.get(item["domain"], 0) >= round_:
                continue
            shown.append(item)
            used[item["domain"]] = used.get(item["domain"], 0) + 1
    return shown


def build_digest(
    articles: list[dict], limit: int = 12
) -> tuple[list[dict], str, dict[str, int]]:
    """Devolve (itens exibíveis, digest, estatísticas).

    Cada item ganha `tier`, `fingerprint`, `corroboration`, `sources` e
    `confidence`. O digest é SHA-256 das impressões digitais ordenadas — muda
    se o conjunto muda, e é o mesmo se a ordem de entrada muda.
    """
    stats = {
        "raw": len(articles),
        "language": 0,
        "irrelevant": 0,
        "invalid": 0,
        "blocked": 0,
        "duplicate": 0,
        "kept": 0,
        "corroborated": 0,
        "single_source": 0,
        # Agrupamentos feitos só pelas entidades (o título não bastou) e,
        # dentre eles, os que juntaram idiomas diferentes.
        "merged_by_keys": 0,
        "cross_language": 0,
    }

    candidates: list[dict] = []
    for art in articles:
        url = str(art.get("url") or "").strip()
        title = str(art.get("title") or "").strip()
        if not url or not title:
            stats["invalid"] += 1
            continue
        language = language_code(art.get("language"))
        if language is None:
            stats["language"] += 1
            continue
        domain = base_domain(str(art.get("domain") or "")) or host_from_url(url)
        tier = domain_tier(domain)
        if tier == "blocked":
            stats["blocked"] += 1
            continue
        if not is_price_relevant(title):
            stats["irrelevant"] += 1
            continue
        candidates.append(
            {
                **art,
                "domain": domain,
                "language": language,
                "tier": tier,
                "fingerprint": fingerprint(title, url),
                "canonical": canonical_url(url),
                "_keys": story_keys(title),
            }
        )

    # 1ª passada: mesma impressão digital = mesma matéria.
    seen: set[str] = set()
    unique: list[dict] = []
    for cand in candidates:
        if cand["fingerprint"] in seen:
            stats["duplicate"] += 1
            continue
        seen.add(cand["fingerprint"])
        unique.append(cand)

    # 2ª passada: mesma URL canônica, títulos quase iguais ou as mesmas
    # entidades (qualquer idioma) = mesma história. Compara só com a cabeça
    # do grupo, para um grupo não crescer por encadeamento.
    clusters: list[list[dict]] = []
    for cand in unique:
        for cluster in clusters:
            head = cluster[0]
            if cand["canonical"] == head["canonical"]:
                cluster.append(cand)
                break
            # Título parecido não junta empresas diferentes: "Samsung raises
            # DRAM prices" e "Micron raises DRAM prices" são duas histórias.
            if not different_companies(cand["_keys"], head["_keys"]) and _similar(
                cand["title"], head["title"]
            ):
                cluster.append(cand)
                break
            if _close_in_time(cand, head) and same_story_by_keys(
                cand["_keys"], head["_keys"]
            ):
                stats["merged_by_keys"] += 1
                if cand["language"] != head["language"]:
                    stats["cross_language"] += 1
                cluster.append(cand)
                break
        else:
            clusters.append([cand])
    stats["duplicate"] += len(unique) - len(clusters)

    items: list[dict] = []
    for cluster in clusters:
        domains = sorted({c["domain"] for c in cluster if c["domain"]})
        rep = min(
            cluster,
            key=lambda c: (TIER_RANK.get(c["tier"], 3), -_ts(c.get("seen_at"))),
        )
        item = {k: v for k, v in rep.items() if k != "_keys"}
        item["corroboration"] = len(domains)
        item["sources"] = domains[:5]
        item["confidence"] = "corroborated" if len(domains) >= 2 else "single-source"
        items.append(item)

    # Corroborado primeiro; dentro disso, veículo de referência e mais recente.
    items.sort(
        key=lambda i: (
            i["corroboration"] < 2,
            TIER_RANK.get(i["tier"], 3),
            -_ts(i.get("seen_at")),
        )
    )
    limit = max(0, limit)
    analysis = _diverse([i for i in items if i.get("kind") == "analysis"], min(MAX_ANALYSIS, limit))
    news = _diverse([i for i in items if i.get("kind") != "analysis"], limit - len(analysis))
    # Notícia abre a lista; análise entra logo depois da primeira página.
    shown = (news[:FIRST_PAGE] + analysis + news[FIRST_PAGE:])[:limit]
    stats["kept"] = len(shown)
    stats["analysis"] = len(analysis)
    stats["corroborated"] = sum(1 for i in shown if i["corroboration"] >= 2)
    stats["single_source"] = len(shown) - stats["corroborated"]

    digest = ""
    if shown:
        joined = "\n".join(sorted(i["fingerprint"] for i in shown))
        digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return shown, digest, stats
