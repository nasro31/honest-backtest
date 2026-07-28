"""
test_momentum.py — Croisement de moyennes mobiles : edge reel ou bruit ?

Applique au momentum la discipline qui a manque a la grille :

  1. CAUSALITE STRICTE. Le signal est calcule sur les bougies CLOTUREES, et
     l'ordre s'execute a l'ouverture de la bougie SUIVANTE. Aucun acces au
     futur — c'est le bug qui avait fait passer la grille pour rentable.

  2. SURFACE COMPLETE DE PARAMETRES, pas un point. Si seul EMA 10/30 gagne et
     que ses voisins immediats (9/28, 11/32) perdent, ce n'est pas un edge :
     c'est un accident de cette serie de prix. Un vrai signal est ROBUSTE au
     voisinage. On regarde donc la carte entiere.

  3. BENCHMARK = BUY & HOLD, jamais zero. Une strategie long-only qui suit une
     hausse n'a aucun merite : c'est le marche qui monte.

  4. TEST DE PERMUTATION. On rejoue la strategie sur des rendements melanges
     au hasard (memes rendements, ordre detruit). Si la vraie performance
     n'est pas nettement au-dessus de ces tirages, elle est indiscernable de
     la chance. C'est le critere qui manquait au plan initial.

    python test_momentum.py
"""

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

from backtest_regimes import charger_donnees

console = Console()

CAPITAL = 20.0
FRAIS = 0.0016          # Kraken maker, palier de base (table de paliers ccxt)
N_PERMUTATIONS = 200


def simuler_momentum(prix: pd.Series, rapide: int, lent: int,
                     frais: float = FRAIS) -> dict:
    """Long quand EMA rapide > EMA lente, cash sinon.

    Signal decale d'une barre : la decision prise a la cloture de la bougie i
    ne s'applique qu'a partir de i+1. Sans ce decalage on achete en connaissant
    la bougie qu'on est en train de trader."""
    ema_r = prix.ewm(span=rapide, adjust=False).mean()
    ema_l = prix.ewm(span=lent, adjust=False).mean()
    position = (ema_r > ema_l).shift(1).fillna(False).astype(float)

    rendements = prix.pct_change().fillna(0.0)
    # Rendement de la strategie = rendement du marche quand on est investi
    brut = position * rendements
    # Frais a chaque changement de position (entree ou sortie)
    changements = position.diff().abs().fillna(0.0)
    net = brut - changements * frais

    equity = CAPITAL * (1 + net).cumprod()
    bh = CAPITAL * (1 + rendements).cumprod()

    n_trades = int(changements.sum())
    rendement_pct = (equity.iloc[-1] / CAPITAL - 1) * 100
    bh_pct = (bh.iloc[-1] / CAPITAL - 1) * 100

    # Sharpe annualise sur bougies 1h
    ecart = net.std()
    sharpe = (net.mean() / ecart * np.sqrt(24 * 365)) if ecart > 0 else 0.0

    pic = equity.cummax()
    dd_max = ((pic - equity) / pic).max() * 100

    return {
        "rendement_pct": rendement_pct,
        "bh_pct": bh_pct,
        "surperf": rendement_pct - bh_pct,
        "sharpe": sharpe,
        "trades": n_trades,
        "dd_max": dd_max,
        "temps_investi": position.mean() * 100,
    }


def test_permutation(prix: pd.Series, rapide: int, lent: int,
                     n: int = N_PERMUTATIONS) -> dict:
    """La performance survit-elle a la destruction de la structure temporelle ?

    On melange les RENDEMENTS (pas les prix) : meme distribution, meme
    volatilite, meme rendement total — mais l'ordre chronologique disparait.
    Toute performance qui subsiste vient du hasard, pas d'un signal."""
    reel = simuler_momentum(prix, rapide, lent)["surperf"]

    rendements = prix.pct_change().fillna(0.0).to_numpy()
    rng = np.random.default_rng(42)
    tirages = []
    for _ in range(n):
        melange = rng.permutation(rendements)
        faux_prix = pd.Series(float(prix.iloc[0]) * np.cumprod(1 + melange),
                              index=prix.index)
        tirages.append(simuler_momentum(faux_prix, rapide, lent)["surperf"])

    tirages = np.array(tirages)
    # p-value : proportion de tirages au hasard qui font AUSSI BIEN ou mieux
    p = float((tirages >= reel).mean())
    return {"reel": reel, "moyenne_hasard": float(tirages.mean()),
            "p_value": p, "meilleur_hasard": float(tirages.max())}


def main():
    df = charger_donnees("BTC/USDT", 1095)
    prix = df["close"]
    console.print(f"[green]{len(prix)} bougies 1h[/green] "
                  f"({prix.index[0].date()} -> {prix.index[-1].date()}), "
                  f"frais {FRAIS*100:.2f} %/trade\n")

    # ── 1. Le point propose par le plan ──────────────────────────────────────
    # EMA 10/30 "jours" -> en bougies 1h : 240 et 720
    r = simuler_momentum(prix, 240, 720)
    console.print("[bold]EMA 10/30 jours (le parametre propose)[/bold]")
    console.print(f"  strategie {r['rendement_pct']:+.1f} %  |  "
                  f"buy & hold {r['bh_pct']:+.1f} %  |  "
                  f"surperformance [{'green' if r['surperf'] > 0 else 'red'}]"
                  f"{r['surperf']:+.1f} pt[/]")
    console.print(f"  Sharpe {r['sharpe']:.2f}  |  {r['trades']} trades  |  "
                  f"investi {r['temps_investi']:.0f} % du temps  |  "
                  f"DD max {r['dd_max']:.1f} %\n")

    # ── 2. La surface complete : 10/30 est-il un pic isole ? ─────────────────
    console.print("[bold]Surface de parametres — surperformance vs buy & hold[/bold]")
    console.print("[dim]Un edge reel forme un plateau. Un pic isole entoure de "
                  "rouge = accident de cette serie de prix.[/dim]\n")

    rapides_j = [3, 5, 10, 15, 20, 30]
    lents_j = [20, 30, 50, 80, 120, 200]

    t = Table(style="cyan")
    t.add_column("rapide \\ lent", justify="right")
    for lj in lents_j:
        t.add_column(f"{lj}j", justify="right")

    surface = {}
    for rj in rapides_j:
        cellules = []
        for lj in lents_j:
            if rj >= lj:
                cellules.append("[dim]-[/dim]")
                continue
            res = simuler_momentum(prix, rj * 24, lj * 24)
            surface[(rj, lj)] = res["surperf"]
            couleur = "green" if res["surperf"] > 0 else "red"
            cellules.append(f"[{couleur}]{res['surperf']:+6.1f}[/{couleur}]")
        t.add_row(f"{rj}j", *cellules)
    console.print(t)

    positifs = sum(1 for v in surface.values() if v > 0)
    console.print(f"\n  {positifs}/{len(surface)} combinaisons battent le buy & hold")
    console.print(f"  surperformance mediane : "
                  f"{np.median(list(surface.values())):+.1f} pt")

    meilleur = max(surface.items(), key=lambda kv: kv[1])
    console.print(f"  meilleure : EMA {meilleur[0][0]}/{meilleur[0][1]} j "
                  f"({meilleur[1]:+.1f} pt)\n")

    # ── 3. Test de permutation sur le meilleur ───────────────────────────────
    console.print(f"[bold]Test de permutation sur EMA {meilleur[0][0]}/{meilleur[0][1]} "
                  f"({N_PERMUTATIONS} tirages)[/bold]")
    console.print("[dim]On detruit l'ordre chronologique en gardant les memes "
                  "rendements. Si le hasard fait aussi bien, il n'y a pas de signal."
                  "[/dim]")
    perm = test_permutation(prix, meilleur[0][0] * 24, meilleur[0][1] * 24)
    console.print(f"  performance reelle      : {perm['reel']:+.1f} pt")
    console.print(f"  moyenne des tirages     : {perm['moyenne_hasard']:+.1f} pt")
    console.print(f"  meilleur tirage hasard  : {perm['meilleur_hasard']:+.1f} pt")
    verdict = "green" if perm["p_value"] < 0.05 else "red"
    console.print(f"  [bold {verdict}]p-value = {perm['p_value']:.3f}[/bold {verdict}]"
                  f"  ({'significatif' if perm['p_value'] < 0.05 else 'INDISCERNABLE DU HASARD'})")


if __name__ == "__main__":
    main()
