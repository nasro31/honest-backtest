"""
test_momentum_mop.py — Momentum facon Moskowitz, Ooi & Pedersen (2012).

Le test precedent (croisement d'EMA, long/cash) a conclu "phenomene non
detecte", avec une raison precise : une strategie long/cash ameliore
mecaniquement le Sharpe de +0,13 rien qu'en etant hors marche la moitie du
temps. L'effet observe n'etait pas separable de cet artefact.

Cette version reprend les trois choix de MOP qui changent la nature du test :

  1. SIGNAL = signe du rendement sur 12 mois glissants (pas un croisement de
     moyennes, dont les parametres sont arbitraires et surajustables).

  2. LONG / SHORT, jamais en cash. C'est le point decisif : la strategie est
     investie a 100 % en permanence, donc l'artefact "moins d'exposition =
     moins de volatilite = meilleur Sharpe" DISPARAIT. Toute amelioration
     restante vient du signal, pas de la structure.

  3. TAILLE PONDEREE PAR L'INVERSE DE LA VOLATILITE : position = cible / vol
     estimee ex-ante. Egalise la contribution au risque entre actifs et dans
     le temps — sans quoi le petrole ecrase les devises dans le portefeuille.

Tout reste causal : la vol est estimee sur les rendements passes, le signal
sur les 12 mois precedents, et la position s'applique au jour suivant.

    python test_momentum_mop.py
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

LOOKBACK = 252          # 12 mois de bourse
VOL_FENETRE = 60        # estimation de volatilite ex-ante
VOL_CIBLE = 0.40        # 40 % annualise, comme MOP
LEVIER_MAX = 3.0        # garde-fou : sans plafond, un actif tres calme
                        # produirait un levier absurde et dominerait tout
N_PERMUTATIONS = 500

CLASSES = {
    "US Equities":   {"actifs": ["SPY", "QQQ", "IWM"],             "cout": 0.0005},
    "International": {"actifs": ["EFA", "EEM"],                    "cout": 0.0005},
    "Devises":       {"actifs": ["EURUSD=X", "GBPUSD=X", "JPY=X"], "cout": 0.0002},
    "Matieres":      {"actifs": ["GC=F", "CL=F", "SI=F"],          "cout": 0.0005},
    "Crypto":        {"actifs": ["BTC-USD", "ETH-USD"],            "cout": 0.0036},
}


def telecharger(ticker: str) -> pd.Series:
    df = yf.download(ticker, period="max", auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def mop(prix: pd.Series, cout: float, long_short: bool = True) -> dict:
    """Momentum MOP. `long_short=False` retombe en long/cash pour comparaison
    directe : c'est ce commutateur qui isole l'artefact structurel."""
    rdt = prix.pct_change()

    # Signal : signe du rendement des 12 derniers mois, decale d'un jour.
    signal = np.sign(prix.pct_change(LOOKBACK)).shift(1)
    if not long_short:
        signal = signal.clip(lower=0)

    # Volatilite ex-ante : ecart-type des rendements PASSES uniquement.
    vol = rdt.rolling(VOL_FENETRE).std().shift(1) * np.sqrt(252)
    levier = (VOL_CIBLE / vol).clip(upper=LEVIER_MAX)

    position = (signal * levier).fillna(0.0)
    brut = position * rdt
    frais = position.diff().abs().fillna(0.0) * cout
    net = (brut - frais).fillna(0.0)

    valides = net.iloc[LOOKBACK + VOL_FENETRE:]
    rdt_bh = rdt.iloc[LOOKBACK + VOL_FENETRE:].fillna(0.0)
    if len(valides) < 500:
        return None

    def stats(s):
        eq = (1 + s).cumprod()
        sd = s.std()
        return {
            "rdt": float((eq.iloc[-1] - 1) * 100),
            "sharpe": float(s.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
            "dd": float(((eq.cummax() - eq) / eq.cummax()).max() * 100),
        }

    s_strat, s_bh = stats(valides), stats(rdt_bh)
    return {
        "rdt": s_strat["rdt"], "rdt_bh": s_bh["rdt"],
        "sharpe": s_strat["sharpe"], "sharpe_bh": s_bh["sharpe"],
        "dd": s_strat["dd"], "dd_bh": s_bh["dd"],
        "expo_moy": float(position.abs().iloc[LOOKBACK + VOL_FENETRE:].mean()),
        "temps_short": float((position < 0).iloc[LOOKBACK + VOL_FENETRE:].mean() * 100),
        "annees": len(valides) / 252,
        "net": valides, "brut": rdt_bh,
    }


def portefeuille(resultats: dict, cle: str = "net") -> pd.Series:
    """Equipondere PAR CLASSE, pas par actif."""
    parts = []
    for classe in CLASSES:
        membres = [k for k, v in resultats.items() if v["classe"] == classe]
        if membres:
            parts.append(pd.DataFrame({k: resultats[k][cle] for k in membres}).mean(axis=1))
    return pd.concat(parts, axis=1).dropna().mean(axis=1)


def sharpe(s: pd.Series) -> float:
    return float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0


def main():
    console.print("[bold]Momentum MOP 2012 — signal 12 mois, long/short, "
                  "pondere par la volatilite[/bold]\n")

    donnees, res_ls, res_lc = {}, {}, {}
    for classe, cfg in CLASSES.items():
        for t in cfg["actifs"]:
            s = telecharger(t)
            if len(s) < 1500:
                continue
            a = mop(s, cfg["cout"], long_short=True)
            b = mop(s, cfg["cout"], long_short=False)
            if a is None or b is None:
                continue
            donnees[t] = s
            a["classe"] = b["classe"] = classe
            res_ls[t], res_lc[t] = a, b

    t = Table(title="Long/short pondere volatilite — par actif", style="cyan")
    for c in ("Actif", "Classe", "Ans", "Strat.", "B&H", "Sharpe", "S.B&H",
              "DD", "DD B&H", "Expo", "% short"):
        t.add_column(c, justify="right")
    for tick, r in res_ls.items():
        mieux = r["sharpe"] > r["sharpe_bh"]
        t.add_row(tick.replace("-USD", "").replace("=X", "").replace("=F", ""),
                  r["classe"][:9], f"{r['annees']:.0f}",
                  f"{r['rdt']:+.0f}%", f"{r['rdt_bh']:+.0f}%",
                  f"[{'green' if mieux else 'red'}]{r['sharpe']:.2f}[/]",
                  f"{r['sharpe_bh']:.2f}", f"{r['dd']:.0f}%", f"{r['dd_bh']:.0f}%",
                  f"{r['expo_moy']:.2f}", f"{r['temps_short']:.0f}%")
    console.print(t)

    gagnants = sum(1 for r in res_ls.values() if r["sharpe"] > r["sharpe_bh"])
    console.print(f"\n  Sharpe > B&H : [bold]{gagnants}/{len(res_ls)} actifs[/bold]\n")

    # ── Portefeuilles ────────────────────────────────────────────────────────
    pf_ls, pf_lc = portefeuille(res_ls), portefeuille(res_lc)
    pf_bh = portefeuille(res_ls, "brut")
    s_ls, s_lc, s_bh = sharpe(pf_ls), sharpe(pf_lc), sharpe(pf_bh)

    t = Table(title="Portefeuille equipondere par classe", style="cyan")
    for c in ("Version", "Rendement", "Sharpe", "vs B&H", "DD"):
        t.add_column(c, justify="right")
    for nom, pf, sh in (("MOP long/short", pf_ls, s_ls),
                        ("MOP long/cash", pf_lc, s_lc),
                        ("Buy & hold", pf_bh, s_bh)):
        eq = (1 + pf).cumprod()
        dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
        ecart = sh - s_bh
        t.add_row(nom, f"{(eq.iloc[-1]-1)*100:+.0f}%", f"{sh:.2f}",
                  f"{ecart:+.2f}" if nom != "Buy & hold" else "-", f"{dd:.0f}%")
    console.print(t)

    # ── Permutation : le point critique ─────────────────────────────────────
    console.print(f"\n[bold]Test de permutation ({N_PERMUTATIONS} tirages)[/bold]")
    console.print("[dim]En long/short l'exposition est permanente : le plancher "
                  "mecanique du long/cash (+0,13 mesure precedemment) doit "
                  "disparaitre. S'il subsiste, c'est encore un artefact.[/dim]")

    rng = np.random.default_rng(11)
    tirages = []
    for _ in range(N_PERMUTATIONS):
        faux = {}
        for tick, r in res_ls.items():
            melange = rng.permutation(donnees[tick].pct_change().dropna().to_numpy())
            serie = pd.Series(
                float(donnees[tick].iloc[0]) * np.cumprod(1 + melange),
                index=donnees[tick].index[1:])
            f = mop(serie, CLASSES[r["classe"]]["cout"], long_short=True)
            if f is not None:
                f["classe"] = r["classe"]
                faux[tick] = f
        if faux:
            tirages.append(sharpe(portefeuille(faux)) - s_bh)

    tirages = np.array(tirages)
    reel = s_ls - s_bh
    p = float((tirages >= reel).mean())

    console.print(f"  ecart de Sharpe reel   : {reel:+.3f}")
    console.print(f"  plancher du hasard     : {tirages.mean():+.3f}  "
                  f"[dim](etait +0,130 en long/cash)[/dim]")
    console.print(f"  meilleur tirage        : {tirages.max():+.3f}")
    couleur = "green" if p < 0.05 else "red"
    console.print(f"  [bold {couleur}]p-value = {p:.4f}[/bold {couleur}] "
                  f"({'SIGNIFICATIF' if p < 0.05 else 'non significatif'})")

    console.print("\n" + "=" * 62)
    if p < 0.05 and gagnants >= len(res_ls) * 0.6:
        console.print("[bold green]PHENOMENE DETECTE[/bold green]")
    elif p < 0.05:
        console.print("[bold yellow]SIGNAL PARTIEL — significatif au niveau "
                      "portefeuille mais pas assez d'actifs[/bold yellow]")
    else:
        console.print("[bold red]PHENOMENE NON DETECTE[/bold red]")
    console.print("=" * 62)


if __name__ == "__main__":
    main()
