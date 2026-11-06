"""Os sete vetores de pressão que o painel acompanha.

Cada driver é uma tese geopolítica/econômica traduzida em sinais mensuráveis
com dado público. `scale` é o tamanho de movimento considerado "grande" para
aquele sinal — é o parâmetro que calibra a sensibilidade do índice e está
exposto aqui de propósito, para poder ser auditado e ajustado.

Janelas: sinais diários (mercado, câmbio, terremotos) olham os últimos 30 dias,
para o painel reagir ao que acabou de acontecer. Ao encurtar de 90 para 30
dias, a escala dos sinais de mercado foi multiplicada por √(30/90) ≈ 0,58 —
variação de preço cresce com a raiz do tempo, e sem esse ajuste o índice
ficaria artificialmente calmo. Séries mensais, trimestrais e anuais mantêm
janelas longas: em 30 dias elas teriam um ponto só.

Todos os sinais são medidos (preço, câmbio, arrecadação, volume, evento
físico). As contagens de cobertura noticiosa do GDELT saíram do índice em
04/11/2026: a fonte falhava (429) na maior parte dos ciclos.
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
    fallback_source: str | None = None  # reserva; nunca somada com a primária
    smooth_days: int = 0  # média móvel antes da variação (série diária ruidosa)
    # Desempenho relativo: a série vira razão `source / relative_to` nas datas
    # comuns. Isola o componente específico (ex.: Taiwan contra chips global).
    relative_to: str | None = None
    # "change": pressão pela variação % na janela (padrão).
    # "peak": pressão pelo pico na janela acima de `threshold` — para eventos
    # físicos (terremoto), que não têm "variação" e nunca aliviam abaixo de 50.
    # "sum": soma líquida de eventos na janela (regra que aperta +, que alivia −).
    # "front": frente de oferta lida por `supply_fronts.read_front` (z contra a
    # própria história; dado vencido fica sem nota).
    mode: str = "change"
    threshold: float = 0.0


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
        weight=0.15,
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
                window_days=30,
                scale=15.0,
                weight=0.48,
                fallback_source="fred.brent",
            ),
            SignalSpec(
                key="natgas",
                label="Gás natural Europa (hélio é subproduto)",
                source="fred.natgas_eu",
                unit="US$/MMBtu",
                window_days=180,
                scale=40.0,
                weight=0.23,
            ),
            SignalSpec(
                key="global_energy",
                label="Índice global de energia (FMI/PCPS)",
                source="fred.global_energy",
                unit="índice",
                window_days=180,
                scale=20.0,
                weight=0.14,
            ),
            SignalSpec(
                key="trade_helium",
                label="Valor unitário importado de gases raros, inclui hélio (Brasil)",
                source="comtrade.helium",
                unit="US$/kg",
                window_days=730,
                scale=40.0,
                weight=0.15,
                path="unit_values",
            ),
        ],
    ),
    DriverSpec(
        key="alocacao_chips",
        label="Alocação de chips: datacenter × consumidor",
        weight=0.22,
        thesis=(
            "A corrida por capacidade de IA consome wafer, encapsulamento avançado e "
            "memória de alta banda. Como HBM e DRAM de consumo dividem as mesmas "
            "linhas, cada lote desviado para datacenter reduz a oferta de memória e "
            "GPU para o varejo. Capex e estoque mostram a fila: quando o hyperscaler "
            "acelera e o estoque de memória cai, o consumidor doméstico vai para o "
            "fim dela."
        ),
        signals=[
            SignalSpec(
                key="capex_hyperscaler",
                label="Capex trimestral dos hyperscalers (TTM)",
                source="sec.capex_hyperscaler",
                unit="US$",
                window_days=365,
                scale=30.0,
                weight=0.20,
                path="ttm_points",
            ),
            # Frentes de oferta (§T24c, ligadas na T30): z contra a própria
            # história; `window_days`/`scale` não se aplicam a `mode="front"`.
            SignalSpec(
                key="tsmc_revenue",
                label="Receita da TSMC (a/a da soma de 3 meses)",
                source="tsmc.monthly_revenue",
                unit="% a/a",
                window_days=0,
                scale=0.0,
                weight=0.13,
                mode="front",
            ),
            SignalSpec(
                key="dio_memory",
                label="Dias de estoque — memória (Micron, invertido)",
                source="sec.memory_quarters",
                unit="dias",
                window_days=0,
                scale=0.0,
                weight=0.15,
                mode="front",
            ),
            SignalSpec(
                key="dio_logic",
                label="Dias de estoque — chips (NVIDIA, AMD, Intel; invertido)",
                source="sec.logic_quarters",
                unit="dias",
                window_days=0,
                scale=0.0,
                weight=0.12,
                mode="front",
            ),
            SignalSpec(
                key="ppi_semis",
                label="PPI EUA — semicondutores",
                source="fred.ppi_semiconductors",
                unit="índice",
                window_days=365,
                scale=8.0,
                weight=0.10,
            ),
            SignalSpec(
                key="micron",
                label="Micron (MU) — ciclo de memória",
                source="market.micron",
                unit="US$",
                window_days=30,
                scale=20.0,
                weight=0.08,
            ),
            SignalSpec(
                key="soxx",
                label="Índice de semicondutores (SOXX)",
                source="market.soxx",
                unit="US$",
                window_days=30,
                scale=15.0,
                weight=0.03,
            ),
            SignalSpec(
                key="tsmc",
                label="TSMC (TSM) — capacidade de fundição",
                source="market.tsmc",
                unit="US$",
                window_days=30,
                scale=15.0,
                weight=0.03,
            ),
            SignalSpec(
                key="nvda",
                label="NVIDIA (NVDA) — demanda de GPU",
                source="market.nvda",
                unit="US$",
                window_days=30,
                scale=20.0,
                weight=0.05,
            ),
            SignalSpec(
                key="comtrade_memory",
                label="Volume importado de memória — Brasil",
                source="comtrade.memory",
                unit="US$",
                window_days=730,
                scale=40.0,
                weight=0.06,
                path="totals",
            ),
            SignalSpec(
                key="comtrade_processors",
                label="Volume importado de processadores — Brasil",
                source="comtrade.processors",
                unit="US$",
                window_days=730,
                scale=40.0,
                weight=0.05,
                path="totals",
            ),
        ],
    ),
    DriverSpec(
        key="terras_raras",
        label="Terras raras e ímãs permanentes",
        weight=0.13,
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
                window_days=30,
                scale=15.0,
                weight=0.60,
            ),
            SignalSpec(
                key="trade_re",
                label="Valor unitário importado de terras raras (Brasil)",
                source="comtrade.rare_earth",
                unit="US$/kg",
                window_days=730,
                scale=40.0,
                weight=0.40,
                path="unit_values",
            ),
        ],
    ),
    DriverSpec(
        key="commodities",
        label="Metais industriais e energia",
        weight=0.11,
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
                window_days=30,
                scale=12.0,
                weight=0.50,
                fallback_source="fred.copper",
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
        weight=0.10,
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
                weight=0.25,
            ),
            SignalSpec(
                key="freight_deep_sea",
                label="PPI EUA — frete marítimo de longo curso",
                source="fred.freight_deep_sea",
                unit="índice",
                window_days=180,
                scale=10.0,
                weight=0.30,
            ),
            SignalSpec(
                key="customs_duties",
                label="Tarifas alfandegárias arrecadadas pelos EUA",
                source="fred.customs_duties",
                unit="US$ bi",
                window_days=365,
                scale=30.0,
                weight=0.25,
            ),
            SignalSpec(
                key="cpi_computers_us",
                label="Preço de computadores ao consumidor nos EUA (CPI)",
                source="fred.cpi_computers_us",
                unit="índice",
                window_days=365,
                scale=6.0,
                weight=0.20,
            ),
        ],
    ),
    DriverSpec(
        key="geopolitica_chips",
        label="Taiwan e disputa EUA–China por chips",
        weight=0.10,
        thesis=(
            "Quase toda a fabricação de chips de ponta está em Taiwan, a poucos "
            "quilômetros da China e numa zona de terremotos; memória depende ainda "
            "de Japão e Coreia. Tensão militar aparece primeiro no mercado — a "
            "bolsa de Taiwan descola do setor de chips global e a moeda local "
            "perde valor com a fuga de capital. Terremoto forte perto de fábrica "
            "para linhas e perde wafers. Os controles de exportação dos EUA sobre "
            "chips e China entram pelo ato oficial: cada regra do BIS publicada "
            "no Federal Register que aperta ou alivia a oferta."
        ),
        signals=[
            SignalSpec(
                key="taiwan_relative",
                label="Bolsa de Taiwan contra o índice global de chips (invertido)",
                source="market.taiwan_index",
                relative_to="market.soxx",
                unit="razão",
                window_days=30,
                scale=10.0,
                weight=0.30,
                invert=True,
            ),
            SignalSpec(
                key="usd_twd",
                label="Dólar contra o novo dólar taiwanês",
                source="market.usd_twd",
                unit="TWD/US$",
                window_days=30,
                scale=3.0,
                weight=0.25,
            ),
            SignalSpec(
                key="fab_quakes",
                label="Maior terremoto perto de fábricas de chips (Taiwan, Japão, Coreia)",
                source="usgs.fab_quakes",
                unit="magnitude",
                window_days=30,
                scale=1.0,
                weight=0.25,
                mode="peak",
                threshold=5.5,
            ),
            SignalSpec(
                key="bis_chip_rules",
                label="Regras dos EUA sobre exportação de chips para a China (BIS)",
                source="fedreg.bis_chip_rules",
                unit="regras (líquido)",
                window_days=30,
                scale=1.5,
                weight=0.20,
                mode="sum",
            ),
        ],
    ),
    DriverSpec(
        key="cambio_br",
        label="Dólar",
        weight=0.19,
        thesis=(
            "O dólar sobe quando o juro brasileiro perde atratividade frente ao "
            "americano, quando cresce o risco fiscal ou o medo global, e cai quando "
            "as commodities que o Brasil exporta se valorizam; costuma andar junto "
            "com o peso mexicano, o chileno e o rand. Quase todo hardware é "
            "importado ou cotado em dólar: o varejo repassa a alta em semanas (85% "
            "em um trimestre, no modelo), e o imposto de importação incide sobre o "
            "valor já convertido em reais."
        ),
        signals=[
            SignalSpec(
                key="ptax",
                label="Dólar PTAX (BCB)",
                source="bcb.ptax_usd",
                unit="R$/US$",
                window_days=30,
                scale=7.0,
                weight=0.75,
                fallback_source="market.usd_brl,fred.usd_brl_fed",
            ),
            SignalSpec(
                key="igpm",
                label="IGP-M acumulado (custo de reposição)",
                source="bcb.igpm",
                unit="%",
                window_days=180,
                scale=6.0,
                weight=0.25,
            ),
        ],
    ),
]

DRIVERS_BY_KEY: dict[str, DriverSpec] = {d.key: d for d in DRIVERS}


def driver_weights() -> dict[str, float]:
    return {d.key: d.weight for d in DRIVERS}
