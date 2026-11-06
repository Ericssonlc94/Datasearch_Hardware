"""Catálogo de categorias de hardware.

Para cada categoria guardamos três coisas distintas, que nunca devem ser
confundidas na apresentação:

1. `betas`  — exposição *modelada* a cada driver (soma 1.0). Heurística.
2. `sh6`/`ncms` — chaves para o dado *observado* de importação (Comex Stat).
3. `ipca_subitem` — chave para o dado *observado* de preço ao consumidor (IBGE).

`sensitivity_pct` é a amplitude típica de 90 dias da categoria: o quanto o
preço se move quando os drivers vão de neutro a máximo. Memória oscila muito
mais que fonte de alimentação, e o modelo precisa refletir isso. A calibração
continua em 90 dias; o ranking converte para o horizonte exibido (30 dias) em
`ranking.HORIZON_DAYS`.

`geopolitica_chips` recebeu 30% do beta que antes ficava todo em
`alocacao_chips`: o risco de Taiwan e dos controles EUA–China estava embutido
ali e agora é medido à parte.

`tax_multiplier` é o multiplicador estimado de custo de desembarque no Brasil
(II + IPI + PIS/COFINS-Importação + ICMS + AFRMM + despesas). São estimativas
de ordem de grandeza para explicar a amplificação local, não apuração fiscal.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    icon: str
    sh6: str
    ncms: list[str]
    betas: dict[str, float]
    sensitivity_pct: float
    tax_multiplier: float
    tax_note: str
    ipca_subitem: str | None = None
    ipca_is_proxy: bool = False
    note: str = ""


CATEGORIES: list[Category] = [
    Category(
        key="gpu",
        label="Placa de vídeo",
        icon="gpu",
        sh6="847330",
        ncms=["84733041", "84733042", "84733043", "84733099"],
        betas={
            "alocacao_chips": 0.24,
            "geopolitica_chips": 0.10,
            "cambio_br": 0.22,
            "commodities": 0.12,
            "terras_raras": 0.12,
            "ormuz_helio": 0.10,
            "logistica": 0.10,
        },
        sensitivity_pct=22.0,
        tax_multiplier=1.85,
        tax_note="II ~16% + IPI + PIS/COFINS-Imp 11,75% + ICMS 18%; sem incentivo de ZFM.",
        ipca_subitem="47641",
        ipca_is_proxy=True,
        note="A mesma linha de produção que atende datacenter atende o varejo.",
    ),
    Category(
        key="ram",
        label="Memória RAM",
        icon="ram",
        sh6="854232",
        ncms=["85423211", "85423219", "85423221", "85423229", "85423290"],
        betas={
            "alocacao_chips": 0.28,
            "geopolitica_chips": 0.12,
            "cambio_br": 0.20,
            "ormuz_helio": 0.12,
            "terras_raras": 0.10,
            "logistica": 0.10,
            "commodities": 0.08,
        },
        sensitivity_pct=32.0,
        tax_multiplier=1.75,
        tax_note="Memória tem II reduzido em várias posições, mas ICMS e PIS/COFINS pesam.",
        ipca_subitem="47641",
        ipca_is_proxy=True,
        note="Categoria mais volátil do catálogo: HBM para IA compete por wafer com DDR de consumo.",
    ),
    Category(
        key="storage",
        label="Armazenamento (HD/SSD)",
        icon="storage",
        sh6="847170",
        ncms=["84717011", "84717012", "84717019", "84717032", "84717039", "84717090"],
        betas={
            "alocacao_chips": 0.21,
            "geopolitica_chips": 0.09,
            "cambio_br": 0.22,
            "terras_raras": 0.16,
            "logistica": 0.12,
            "commodities": 0.10,
            "ormuz_helio": 0.10,
        },
        sensitivity_pct=24.0,
        tax_multiplier=1.78,
        tax_note="SSD e HD seguem regra geral de informática, com ICMS estadual dominante.",
        ipca_subitem="47641",
        ipca_is_proxy=True,
        note="HD mecânico usa ímã de neodímio e hélio selado — exposto aos dois gargalos.",
    ),
    Category(
        key="cpu",
        label="Processador",
        icon="cpu",
        sh6="854231",
        ncms=["85423110", "85423120", "85423190"],
        betas={
            "alocacao_chips": 0.22,
            "geopolitica_chips": 0.10,
            "cambio_br": 0.24,
            "ormuz_helio": 0.14,
            "terras_raras": 0.12,
            "logistica": 0.10,
            "commodities": 0.08,
        },
        sensitivity_pct=15.0,
        tax_multiplier=1.72,
        tax_note="Processadores têm alíquota de importação menor, mas carga interna cheia.",
        ipca_subitem="47641",
        ipca_is_proxy=True,
        note="Litografia avançada é a etapa mais dependente de hélio de alta pureza.",
    ),
    Category(
        key="motherboard",
        label="Placa-mãe",
        icon="motherboard",
        sh6="847330",
        ncms=["84733041", "84733049"],
        betas={
            "cambio_br": 0.24,
            "commodities": 0.22,
            "alocacao_chips": 0.14,
            "geopolitica_chips": 0.06,
            "ormuz_helio": 0.12,
            "logistica": 0.12,
            "terras_raras": 0.10,
        },
        sensitivity_pct=16.0,
        tax_multiplier=1.85,
        tax_note="Placa montada entra com II cheio quando não há similar nacional habilitado.",
        note="Cobre e laminado de fibra de vidro respondem por parte relevante do custo.",
    ),
    Category(
        key="psu",
        label="Fonte de alimentação",
        icon="psu",
        sh6="850440",
        ncms=["85044090", "85044030"],
        betas={
            "commodities": 0.34,
            "cambio_br": 0.26,
            "logistica": 0.16,
            "ormuz_helio": 0.08,
            "alocacao_chips": 0.06,
            "geopolitica_chips": 0.02,
            "terras_raras": 0.08,
        },
        sensitivity_pct=14.0,
        tax_multiplier=1.88,
        tax_note="Produto pesado: frete e AFRMM têm peso proporcionalmente maior.",
        note="É a categoria mais colada em cobre — quase um derivado de commodity.",
    ),
    Category(
        key="smartphone",
        label="Celular / smartphone",
        icon="smartphone",
        sh6="851713",
        ncms=["85171331", "85171339", "85171390"],
        betas={
            "cambio_br": 0.26,
            "alocacao_chips": 0.18,
            "geopolitica_chips": 0.08,
            "terras_raras": 0.16,
            "ormuz_helio": 0.12,
            "commodities": 0.10,
            "logistica": 0.10,
        },
        sensitivity_pct=14.0,
        tax_multiplier=1.65,
        tax_note="Montagem na Zona Franca de Manaus reduz a carga efetiva de parte do mercado.",
        ipca_subitem="7794",
        note="Ímãs de terras raras entram em alto-falante, motor de vibração e câmera.",
    ),
    Category(
        key="notebook",
        label="Notebook",
        icon="notebook",
        sh6="847130",
        ncms=["84713012", "84713019", "84713090"],
        betas={
            "alocacao_chips": 0.21,
            "geopolitica_chips": 0.09,
            "cambio_br": 0.26,
            "commodities": 0.12,
            "logistica": 0.12,
            "ormuz_helio": 0.10,
            "terras_raras": 0.10,
        },
        sensitivity_pct=16.0,
        tax_multiplier=1.70,
        tax_note="Lei de Informática e PPB reduzem IPI de parte da linha montada no país.",
        ipca_subitem="47641",
        note="Subitem 'Computador pessoal' do IPCA é a leitura oficial mais próxima.",
    ),
    Category(
        key="monitor",
        label="Monitor",
        icon="monitor",
        sh6="852852",
        ncms=["85285220", "85285290"],
        betas={
            "cambio_br": 0.26,
            "commodities": 0.22,
            "alocacao_chips": 0.13,
            "geopolitica_chips": 0.05,
            "logistica": 0.16,
            "ormuz_helio": 0.10,
            "terras_raras": 0.08,
        },
        sensitivity_pct=13.0,
        tax_multiplier=1.80,
        tax_note="Volume alto e valor médio baixo: frete pesa mais que o chip embarcado.",
        ipca_subitem="7542",
        ipca_is_proxy=True,
        note="Painel LCD/OLED é commodity própria, menos sensível ao ciclo de IA.",
    ),
    Category(
        key="console",
        label="Console de videogame",
        icon="console",
        sh6="950450",
        ncms=["95045000"],
        betas={
            "alocacao_chips": 0.21,
            "geopolitica_chips": 0.09,
            "cambio_br": 0.26,
            "commodities": 0.12,
            "logistica": 0.12,
            "terras_raras": 0.10,
            "ormuz_helio": 0.10,
        },
        sensitivity_pct=18.0,
        tax_multiplier=1.95,
        tax_note="Console tem a carga tributária mais alta do catálogo na importação regular.",
        ipca_subitem="47640",
        note="O IPCA já mostra este subitem entre os que mais sobem em 12 meses.",
    ),
]

CATEGORIES_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}


def validate_catalog() -> list[str]:
    """Confere que os betas somam 1.0 e referenciam drivers existentes."""
    from .drivers import DRIVERS_BY_KEY

    problems: list[str] = []
    for cat in CATEGORIES:
        total = sum(cat.betas.values())
        if abs(total - 1.0) > 1e-6:
            problems.append(f"{cat.key}: betas somam {total:.4f}, esperado 1.0")
        for dk in cat.betas:
            if dk not in DRIVERS_BY_KEY:
                problems.append(f"{cat.key}: driver desconhecido '{dk}'")
    return problems
