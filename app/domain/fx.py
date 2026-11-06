"""Por que o dólar se mexeu — e o que isso faz com o preço do hardware.

Não existe dado que "prove" a causa de um movimento de câmbio. O que dá para
medir com honestidade é a **comparação**:

1. **Real contra pares emergentes** (México, Chile, África do Sul, Colômbia):
   se o real caiu junto com eles, a causa é global; se caiu sozinho, é
   brasileira (fiscal, política, fluxo de capital).
2. **Dólar contra moedas fortes (DXY)**: dólar forte no mundo puxa todas.
3. **Diferencial de juros Brasil–EUA** (Selic − Fed funds): encolhendo, o
   real rende menos e perde atratividade.
4. **Medo global (VIX)**: em crise, o dinheiro sai de emergentes de uma vez.
5. **Commodities (FMI)**: exportação brasileira mais barata traz menos dólar.

O impacto usa a mesma conta do índice: variação do dólar × repasse (85%) no
preço do importado, e o custo de desembarque de US$ 100 em reais com a carga
tributária típica de importação.

Módulo puro: recebe as coletas, devolve números e frases prontas.
"""

from __future__ import annotations

from statistics import median

from ..cache import Fetched
from ..schemas import FxExplanation, FxReason
from ..series_utils import Point, pct_change, pct_change_n, value_n_days_ago
from .analyzer import FX_PASSTHROUGH_DAYS as PASSTHROUGH_DAYS
from .catalog import CATEGORIES

WINDOW_DAYS = 30

# Emergentes com perfil parecido (exportadores de commodities, juro alto).
PEERS: dict[str, str] = {
    "market.usd_mxn": "peso mexicano",
    "market.usd_clp": "peso chileno",
    "market.usd_zar": "rand sul-africano",
    "market.usd_cop": "peso colombiano",
}

# Abaixo disso o movimento é ruído de câmbio, não "alta" nem "queda".
FLAT_PCT = 0.5
# Parcela a partir da qual uma das causas "explica" o movimento.
DOMINANT_SHARE = 0.6


def _points(collected: dict[str, Fetched], key: str) -> list[Point]:
    fetched = collected.get(key)
    if fetched is None or not fetched.ok or not isinstance(fetched.payload, dict):
        return []
    return [
        (str(p[0]), float(p[1]))
        for p in fetched.payload.get("points") or []
        if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None
    ]


def _fmt(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}f}".replace(".", ",")


def _abs(v: float, digits: int = 2) -> str:
    return f"{v:.{digits}f}".replace(".", ",")


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _decomposition(brl: float, peers_avg: float | None) -> tuple[FxReason, float | None]:
    """Separa a parte global (pares) da parte brasileira do movimento."""
    if peers_avg is None:
        return FxReason(
            key="decomposicao",
            text=(
                f"O real variou {_fmt(brl)}% contra o dólar em {WINDOW_DAYS} dias. "
                "Sem as moedas de comparação neste ciclo, não dá para separar "
                "causa global de causa brasileira."
            ),
        ), None

    domestic = brl - peers_avg
    share = max(0.0, min(1.0, domestic / brl)) if abs(brl) >= FLAT_PCT else None
    peers_txt = f"moedas de emergentes parecidos variaram em média {_fmt(peers_avg)}%"
    if abs(brl) < FLAT_PCT:
        text = (
            f"O dólar ficou praticamente estável contra o real ({_fmt(brl)}% em "
            f"{WINDOW_DAYS} dias); {peers_txt}."
        )
    elif brl > 0 and share is not None and share >= DOMINANT_SHARE:
        text = (
            f"A alta é sobretudo brasileira: o dólar subiu {_abs(brl, 1)}% contra o "
            f"real, enquanto {peers_txt}. Cerca de {share:.0%} do movimento não "
            "aparece nos pares — o que aponta para fatores internos, como risco "
            "fiscal, ruído político ou saída de capital."
        )
    elif brl > 0 and share is not None and share <= 1 - DOMINANT_SHARE:
        text = (
            f"A alta acompanha o mundo: o dólar subiu {_abs(brl, 1)}% contra o real "
            f"e {peers_txt}. O real caiu junto com os pares, não sozinho."
        )
    elif brl > 0:
        text = (
            f"Parte global, parte brasileira: o dólar subiu {_abs(brl, 1)}% contra o "
            f"real e {peers_txt}; cerca de {share:.0%} da alta é específica do Brasil."
        )
    elif domestic < -FLAT_PCT:
        text = (
            f"O real se valorizou ({_fmt(brl)}% para o dólar) e foi melhor que os "
            f"pares ({peers_txt}) — sinal de confiança específica no Brasil."
        )
    else:
        text = (
            f"O real se valorizou ({_fmt(brl)}% para o dólar) em linha com os "
            f"pares: {peers_txt}. Movimento global de fraqueza do dólar."
        )
    return FxReason(key="decomposicao", text=text), share


def explain_fx(
    collected: dict[str, Fetched],
    usd_brl: list[Point],
    passthrough: float,
) -> FxExplanation | None:
    """Monta a explicação do movimento do dólar e o impacto no hardware."""
    brl = pct_change(usd_brl, WINDOW_DAYS) if usd_brl else None
    if brl is None:
        return None

    peers = {
        label: chg
        for key, label in PEERS.items()
        if (chg := pct_change(_points(collected, key), WINDOW_DAYS)) is not None
    }
    peers_avg = sum(peers.values()) / len(peers) if peers else None
    reasons: list[FxReason] = []
    decomposition, share = _decomposition(brl, peers_avg)
    reasons.append(decomposition)

    dxy = pct_change(_points(collected, "market.dxy"), WINDOW_DAYS)
    if dxy is not None:
        if dxy >= 1.0:
            text = (f"O dólar também se fortaleceu no mundo: o índice DXY (dólar contra "
                    f"moedas fortes) subiu {_abs(dxy, 1)}%.")
        elif dxy <= -1.0:
            text = (f"No mundo o dólar enfraqueceu (DXY {_fmt(dxy)}%), o que torna a "
                    "alta contra o real ainda mais específica do Brasil." if brl > FLAT_PCT
                    else f"No mundo o dólar enfraqueceu (DXY {_fmt(dxy)}%).")
        else:
            text = (f"O dólar ficou estável contra moedas fortes (DXY {_fmt(dxy)}%): "
                    "não houve onda global de dólar forte.")
        reasons.append(FxReason(key="dxy", text=text))

    selic = _points(collected, "bcb.selic_meta")
    fed = _points(collected, "fred.fed_funds")
    rate_diff = rate_diff_change = None
    if selic and fed:
        rate_diff = selic[-1][1] - fed[-1][1]
        s0 = value_n_days_ago(selic, WINDOW_DAYS)
        f0 = value_n_days_ago(fed, WINDOW_DAYS)
        if s0 is not None and f0 is not None:
            rate_diff_change = rate_diff - (s0 - f0)
        if rate_diff_change is not None and rate_diff_change <= -0.25:
            tail = "encolheu — aplicar em reais ficou menos atraente, o que pressiona o câmbio."
        elif rate_diff_change is not None and rate_diff_change >= 0.25:
            tail = "aumentou — o real rende mais, o que tende a segurar o dólar."
        else:
            tail = "não mudou no período — os juros não explicam a oscilação."
        reasons.append(FxReason(
            key="juros",
            text=(f"O diferencial de juros Brasil–EUA (Selic {_abs(selic[-1][1])}% menos "
                  f"Fed {_abs(fed[-1][1])}%) é de {_abs(rate_diff)} p.p. e {tail}"),
        ))

    vix_pts = _points(collected, "market.vix")
    vix = vix_pts[-1][1] if vix_pts else None
    vix_change = pct_change(vix_pts, WINDOW_DAYS) if vix_pts else None
    if vix is not None:
        if vix >= 25:
            text = (f"O medo global está alto (VIX {_abs(vix, 1)}): em crise, investidores "
                    "tiram dinheiro de emergentes, e o real costuma sofrer.")
        else:
            text = (f"O medo global está contido (VIX {_abs(vix, 1)}), então aversão a risco "
                    "não explica o movimento.")
        reasons.append(FxReason(key="risco_global", text=text))

    commodities = _points(collected, "fred.global_all")
    commodities_change = pct_change_n(commodities, 1) if commodities else None
    if commodities_change is not None:
        direction = "subiram" if commodities_change > 0 else "caíram"
        effect = ("menos dólares entram com as exportações" if commodities_change < -1
                  else "não pesa contra o real" if commodities_change >= 0
                  else "efeito pequeno")
        reasons.append(FxReason(
            key="commodities",
            text=(f"As commodities {direction} {_abs(abs(commodities_change), 1)}% no último mês "
                  f"(índice do FMI, {commodities[-1][0][:7]}): {effect}."),
        ))

    # --- impacto ---
    # `price_effect` é o repasse completo do trimestre; o ranking usa só a
    # fração de 30 dias (`analyzer.fx_price_effect`). O texto mostra os dois.
    price_effect = brl * passthrough
    multiplier = median(c.tax_multiplier for c in CATEGORIES)
    now = usd_brl[-1][1]
    before = value_n_days_ago(usd_brl, WINDOW_DAYS)
    landed_now = 100.0 * now * multiplier
    landed_before = 100.0 * before * multiplier if before else None
    if landed_before:
        diff = landed_now - landed_before
        landed_txt = (f" — eram {_brl(landed_before)} há {WINDOW_DAYS} dias "
                      f"({'+' if diff >= 0 else '−'}{_brl(abs(diff))} por produto). ")
    else:
        landed_txt = ". "

    return FxExplanation(
        brl_change_30d_pct=round(brl, 2),
        peers_change_30d_pct=round(peers_avg, 2) if peers_avg is not None else None,
        peers={k: round(v, 2) for k, v in peers.items()},
        dxy_change_30d_pct=round(dxy, 2) if dxy is not None else None,
        domestic_share=round(share, 3) if share is not None else None,
        rate_diff_pp=round(rate_diff, 2) if rate_diff is not None else None,
        rate_diff_change_pp=round(rate_diff_change, 2) if rate_diff_change is not None else None,
        vix=round(vix, 2) if vix is not None else None,
        vix_change_30d_pct=round(vix_change, 2) if vix_change is not None else None,
        commodities_change_pct=round(commodities_change, 2) if commodities_change is not None else None,
        price_effect_pct=round(price_effect, 2),
        tax_multiplier=multiplier,
        landed_per_100usd=round(landed_now, 2),
        landed_per_100usd_30d_ago=round(landed_before, 2) if landed_before else None,
        reasons=reasons,
        impact_hardware=(
            f"Com repasse de {passthrough:.0%}, a variação do dólar acrescenta cerca de "
            f"{_fmt(price_effect)}% ao preço do hardware importado ao longo de uns três "
            f"meses — perto de {_fmt(price_effect * WINDOW_DAYS / PASSTHROUGH_DAYS)}% "
            f"no primeiro mês."
        ),
        impact_market=(
            f"Um produto de US$ 100, com a carga típica de importação ({_abs(multiplier)}×), "
            f"custa {_brl(landed_now)} para desembarcar{landed_txt}"
            "O varejo reajusta pelo custo de repor o próximo lote, então a diferença "
              "chega antes ao produto novo do que ao estoque antigo."
        ),
    )
