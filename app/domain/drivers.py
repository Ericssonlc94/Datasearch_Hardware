"""Os seis vetores de pressão que o painel acompanha.

Cada driver é uma tese geopolítica/econômica traduzida em sinais mensuráveis
com dado público. `scale` é o tamanho de movimento considerado "grande" para
aquele sinal — é o parâmetro que calibra a sensibilidade do índice e está
exposto aqui de propósito, para poder ser auditado e ajustado.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalSpec:
    key: str
    label: str
    source: str  # chave no dicionário de coletas
    unit: str
    window_days: int
    scale: float  # variação % que satura o score em ~88/100
    weight: float
    path: str = "points"  # campo do payload que contém a série
    invert: bool = False  # True quando queda do sinal significa pressão de alta


@dataclass(frozen=True)
class DriverSpec:
    key: str
    label: str
    thesis: str
    weight: float
    signals: list[SignalSpec] = field(default_factory=list)


DRIVERS: list[DriverSpec] = [
    DriverSpec(
        key="ormuz_helio",
        label="Estreito de Ormuz e hélio",
        weight=0.16,
        thesis=(
            "O Catar responde por cerca de um terço do hélio mundial e escoa pelo "
            "Estreito de Ormuz. Hélio é insumo crítico de litografia, gravação e "
            "resfriamento em fábricas de semicondutores — sem substituto prático. "
            "Restrição no estreito eleva energia e aperta o gás nobre ao mesmo tempo, "
            "atingindo o custo de wafer antes de chegar à prateleira."
        ),
        signals=[
            SignalSpec(
                key="brent",
                label="Petróleo Brent",
                source="market.brent",
                unit="US$/bbl",
                window_days=90,
                scale=25.0,
                weight=0.28,
            ),
            SignalSpec(
                key="brent_fred",
                label="Brent (série diária FRED)",
                source="fred.brent",
                unit="US$/bbl",
                window_days=90,
                scale=25.0,
                weight=0.10,
            ),
            SignalSpec(
                key="natgas",
                label="Gás natural Europa (hélio é subproduto)",
                source="fred.natgas_eu",
                unit="US$/MMBtu",
                window_days=180,
                scale=40.0,
                weight=0.18,
            ),
            SignalSpec(
                key="global_energy",
                label="Índice global de energia (FMI/PCPS)",
                source="fred.global_energy",
                unit="índice",
                window_days=180,
                scale=20.0,
                weight=0.12,
            ),
            SignalSpec(
                key="tension_hormuz",
                label="Cobertura noticiosa — Estreito de Ormuz",
                source="gdelt.hormuz",
                unit="artigos/10k",
                window_days=60,
                scale=60.0,
                weight=0.20,
            ),
            SignalSpec(
                key="tension_helium",
                label="Cobertura noticiosa — escassez de hélio",
                source="gdelt.helium",
                unit="artigos/10k",
                window_days=60,
                scale=60.0,
                weight=0.12,
            ),
        ],
    ),
    DriverSpec(
        key="chip_datacenter",
        label="Demanda de datacenter por microchips",
        weight=0.24,
        thesis=(
            "A corrida por capacidade de IA consome wafer, encapsulamento avançado e "
            "memória de alta banda. Como HBM e DRAM de consumo dividem as mesmas "
            "linhas, cada lote desviado para datacenter reduz a oferta de memória e "
            "GPU para o varejo — o consumidor doméstico disputa fila com hyperscaler."
        ),
        signals=[
            SignalSpec(
                key="soxx",
                label="Índice de semicondutores (SOXX)",
                source="market.soxx",
                unit="US$",
                window_days=90,
                scale=25.0,
                weight=0.20,
            ),
            SignalSpec(
                key="micron",
                label="Micron (MU) — ciclo de memória",
                source="market.micron",
                unit="US$",
                window_days=90,
                scale=35.0,
                weight=0.22,
            ),
            SignalSpec(
                key="nvda",
                label="NVIDIA (NVDA) — demanda de GPU",
                source="market.nvda",
                unit="US$",
                window_days=90,
                scale=35.0,
                weight=0.15,
            ),
            SignalSpec(
                key="ppi_semis",
                label="PPI EUA — semicondutores",
                source="fred.ppi_semiconductors",
                unit="índice",
                window_days=365,
                scale=8.0,
                weight=0.23,
            ),
            SignalSpec(
                key="tension_chips",
                label="Cobertura noticiosa — demanda de chips por IA",
                source="gdelt.chip_demand",
                unit="artigos/10k",
                window_days=60,
                scale=50.0,
                weight=0.20,
            ),
        ],
    ),
    DriverSpec(
        key="terras_raras",
        label="Terras raras e ímãs permanentes",
        weight=0.14,
        thesis=(
            "Neodímio, disprósio e praseodímio entram em ímãs de motores de HD, "
            "alto-falantes, motores de vibração e ventoinhas. A cadeia é concentrada "
            "na China, que já usou controle de exportação como instrumento de "
            "política externa. Restrição aqui atinge armazenamento e celular primeiro."
        ),
        signals=[
            SignalSpec(
                key="remx",
                label="Cesta de terras raras (REMX)",
                source="market.rare_earth",
                unit="US$",
                window_days=90,
                scale=25.0,
                weight=0.40,
            ),
            SignalSpec(
                key="tension_re",
                label="Cobertura noticiosa — controles de exportação",
                source="gdelt.rare_earth",
                unit="artigos/10k",
                window_days=60,
                scale=50.0,
                weight=0.35,
            ),
            SignalSpec(
                key="trade_re",
                label="Valor unitário importado de terras raras (Brasil)",
                source="comtrade.rare_earth",
                unit="US$/kg",
                window_days=730,
                scale=40.0,
                weight=0.25,
                path="unit_values",
            ),
        ],
    ),
    DriverSpec(
        key="commodities",
        label="Metais industriais e energia",
        weight=0.14,
        thesis=(
            "Cobre em trilhas de placa, dissipadores e cabos; alumínio em gabinetes e "
            "coolers; energia em toda a cadeia. É o piso de custo físico do hardware, "
            "que se move mais devagar que semicondutor mas não recua com facilidade."
        ),
        signals=[
            SignalSpec(
                key="copper",
                label="Cobre futuro",
                source="market.copper",
                unit="US$/lb",
                window_days=90,
                scale=20.0,
                weight=0.30,
            ),
            SignalSpec(
                key="copper_global",
                label="Cobre — preço global mensal",
                source="fred.copper",
                unit="US$/t",
                window_days=180,
                scale=22.0,
                weight=0.20,
            ),
            SignalSpec(
                key="aluminum",
                label="Alumínio — preço global mensal",
                source="fred.aluminum",
                unit="US$/t",
                window_days=180,
                scale=22.0,
                weight=0.20,
            ),
            SignalSpec(
                key="imf_metals",
                label="Índice global de metais (FMI/PCPS)",
                source="fred.global_metals",
                unit="índice",
                window_days=180,
                scale=18.0,
                weight=0.30,
            ),
        ],
    ),
    DriverSpec(
        key="logistica",
        label="Frete, tarifas e logística de importação",
        weight=0.12,
        thesis=(
            "Hardware é volumoso em valor e sensível a rota. Desvios no Mar Vermelho, "
            "tarifas e controles de exportação alongam prazo e encarecem o frete — "
            "custo que no Brasil entra na base de cálculo do imposto e é multiplicado."
        ),
        signals=[
            SignalSpec(
                key="import_px",
                label="Índice de preço de importação — semicondutores",
                source="fred.import_px_semis",
                unit="índice",
                window_days=365,
                scale=8.0,
                weight=0.30,
            ),
            SignalSpec(
                key="tension_shipping",
                label="Cobertura noticiosa — ruptura em frete marítimo",
                source="gdelt.shipping",
                unit="artigos/10k",
                window_days=60,
                scale=50.0,
                weight=0.35,
            ),
            SignalSpec(
                key="tension_tariff",
                label="Cobertura noticiosa — tarifas em eletrônicos",
                source="gdelt.trade_tariff",
                unit="artigos/10k",
                window_days=60,
                scale=50.0,
                weight=0.35,
            ),
        ],
    ),
    DriverSpec(
        key="cambio_br",
        label="Câmbio e macro Brasil",
        weight=0.20,
        thesis=(
            "Praticamente todo hardware vendido no Brasil é importado e cotado em "
            "dólar. O câmbio é o canal mais rápido e mais forte de repasse ao preço "
            "final — e incide antes dos impostos, que então multiplicam a alta."
        ),
        signals=[
            SignalSpec(
                key="ptax",
                label="Dólar PTAX (BCB)",
                source="bcb.ptax_usd",
                unit="R$/US$",
                window_days=90,
                scale=12.0,
                weight=0.45,
            ),
            SignalSpec(
                key="usd_brl_spot",
                label="Dólar/Real spot",
                source="market.usd_brl",
                unit="R$/US$",
                window_days=90,
                scale=12.0,
                weight=0.25,
            ),
            SignalSpec(
                key="igpm",
                label="IGP-M acumulado (custo de reposição)",
                source="bcb.igpm",
                unit="%",
                window_days=180,
                scale=6.0,
                weight=0.15,
            ),
            SignalSpec(
                key="usd_brl_fed",
                label="USD/BRL (Federal Reserve H.10)",
                source="fred.usd_brl_fed",
                unit="R$/US$",
                window_days=90,
                scale=12.0,
                weight=0.15,
            ),
        ],
    ),
]

DRIVERS_BY_KEY: dict[str, DriverSpec] = {d.key: d for d in DRIVERS}


def driver_weights() -> dict[str, float]:
    return {d.key: d.weight for d in DRIVERS}
