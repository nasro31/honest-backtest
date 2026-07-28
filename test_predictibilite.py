"""
test_predictibilite.py — Y a-t-il seulement quelque chose a exploiter ?

Changement d'approche. Tester les strategies une par une gonfle le compteur de
tests multiples et fait s'effondrer le seuil de significativite. On remonte
donc d'un cran : plutot que de demander "cette strategie marche-t-elle ?", on
demande **"ces series contiennent-elles une structure exploitable, quelle que
soit la strategie ?"**

Trois mesures, toutes classiques et sans parametre a optimiser :

  1. AUTOCORRELATION des rendements aux retards 1 a 20, avec bandes de
     confiance de Bartlett. Une strategie de suivi de tendance a besoin
     d'autocorrelation positive ; une strategie de retour a la moyenne, de
     negative. Si tout est dans le bruit, ni l'une ni l'autre n'a de matiere.

  2. TEST DU RATIO DE VARIANCE (Lo & MacKinlay 1988), statistique robuste a
     l'heteroscedasticite. Sous marche aleatoire, VR(q) = 1. VR > 1 =
     persistance (momentum), VR < 1 = retour a la moyenne. C'est LE test de
     reference pour rejeter la marche aleatoire.

  3. TRADUCTION ECONOMIQUE. Une autocorrelation peut etre statistiquement
     significative et economiquement inutile. On convertit donc toute
     structure detectee en gain brut par transaction, et on la compare au
     cout reel. C'est la seule comparaison qui decide quelque chose.

    python test_predictibilite.py
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

ACTIFS = {
    "SPY": 0.0005, "QQQ": 0.0005, "IWM": 0.0005,
    "EFA": 0.0005, "EEM": 0.0005,
    "EURUSD=X": 0.0002, "GBPUSD=X": 0.0002, "JPY=X": 0.0002,
    "GC=F": 0.0005, "CL=F": 0.0005, "SI=F": 0.0005,
    "BTC-USD": 0.0036, "ETH-USD": 0.0036,
}
HORIZONS = [2, 5, 10, 20]


def telecharger(t: str) -> pd.Series:
    df = yf.download(t, period="max", auto_adjust=True, progress=False,
                     multi_level_index=False)
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def ratio_variance(rdt: np.ndarray, q: int) -> tuple:
    """Lo & MacKinlay, statistique robuste a l'heteroscedasticite.
    Retourne (VR, z, p bilaterale)."""
    n = len(rdt)
    mu = rdt.mean()
    var1 = ((rdt - mu) ** 2).sum() / (n - 1)

    # Variance des rendements cumules sur q periodes (chevauchants)
    cum = np.convolve(rdt, np.ones(q), mode="valid")
    m = q * (n - q + 1) * (1 - q / n)
    varq = ((cum - q * mu) ** 2).sum() / m
    vr = varq / var1

    # Ecart-type robuste a l'heteroscedasticite (Lo & MacKinlay 1988, eq. 4.7) :
    #   delta_j = SUM (r_t-mu)^2 (r_{t-j}-mu)^2  /  [SUM (r_t-mu)^2]^2
    # Pas de facteur n ici — l'ajouter gonflait theta d'un facteur ~5000 et
    # ecrasait toutes les statistiques z a zero.
    den = (((rdt - mu) ** 2).sum()) ** 2
    theta = 0.0
    for j in range(1, q):
        num = ((rdt[j:] - mu) ** 2 * (rdt[:-j] - mu) ** 2).sum()
        delta = num / den if den > 0 else 0.0
        theta += (2 * (q - j) / q) ** 2 * delta

    z = (vr - 1) / np.sqrt(theta) if theta > 0 else 0.0
    from math import erfc, sqrt
    p = erfc(abs(z) / sqrt(2))
    return vr, z, p


def main():
    console.print("[bold]Y a-t-il une structure exploitable dans ces series ?"
                  "[/bold]")
    console.print("[dim]Question posee aux DONNEES, pas a une strategie. "
                  "Aucun parametre a optimiser, donc aucun surajustement "
                  "possible.[/dim]\n")

    series = {}
    for t in ACTIFS:
        s = telecharger(t)
        if len(s) >= 1500:
            series[t] = s.pct_change().dropna().to_numpy()

    # ── 1. Autocorrelation ───────────────────────────────────────────────────
    t = Table(title="Autocorrelation des rendements (retards 1-5) — "
                    "gras = hors bandes de Bartlett a 95 %", style="cyan")
    t.add_column("Actif", justify="right")
    for lag in range(1, 6):
        t.add_column(f"lag {lag}", justify="right")
    t.add_column("|max| 1-20", justify="right")

    autocorrs = {}
    for tick, r in series.items():
        n = len(r)
        seuil = 1.96 / np.sqrt(n)
        cellules = []
        tous = []
        for lag in range(1, 21):
            ac = float(np.corrcoef(r[:-lag], r[lag:])[0, 1])
            tous.append(ac)
            if lag <= 5:
                gras = abs(ac) > seuil
                couleur = "yellow" if gras else "dim"
                cellules.append(f"[{couleur}]{ac:+.3f}[/{couleur}]")
        autocorrs[tick] = tous
        t.add_row(tick.replace("-USD", "").replace("=X", "").replace("=F", ""),
                  *cellules, f"{max(abs(a) for a in tous):.3f}")
    console.print(t)

    # ── 2. Ratio de variance ────────────────────────────────────────────────
    t = Table(title="Test du ratio de variance — VR (z) | VR=1 = marche aleatoire",
              style="cyan")
    t.add_column("Actif", justify="right")
    for q in HORIZONS:
        t.add_column(f"q={q}", justify="right")

    rejets = 0
    for tick, r in series.items():
        cellules = []
        for q in HORIZONS:
            vr, z, p = ratio_variance(r, q)
            signif = p < 0.05
            rejets += signif
            couleur = "yellow" if signif else "dim"
            cellules.append(f"[{couleur}]{vr:.2f} ({z:+.1f})[/{couleur}]")
        t.add_row(tick.replace("-USD", "").replace("=X", "").replace("=F", ""),
                  *cellules)
    console.print(t)
    total = len(series) * len(HORIZONS)
    console.print(f"  marche aleatoire rejetee dans [bold]{rejets}/{total}[/bold] "
                  f"cas (5 % attendus par hasard = {total*0.05:.0f})")

    # ── 3. Traduction economique — la seule qui decide ──────────────────────
    console.print("\n[bold]Traduction economique[/bold]")
    console.print("[dim]Gain brut theorique maximal en exploitant PARFAITEMENT "
                  "l'autocorrelation detectee, contre le cout reel d'un "
                  "aller-retour. Un edge statistique sous le cout est "
                  "ininvestissable.[/dim]\n")

    console.print("[dim]On ne retient que l'autocorrelation POSITIVE : a retard 1, "
                  "une autocorrelation negative est la signature du rebond "
                  "bid-ask (le prix alterne entre achat et vente du carnet). "
                  "C'est un artefact de microstructure, non capturable — il "
                  "faudrait traiter a l'interieur du spread.[/dim]\n")

    t = Table(style="cyan")
    for c in ("Actif", "AC+ max", "AC- (lag1)", "Vol quot.", "Gain brut/trade",
              "Cout A/R", "Net", "Exploitable"):
        t.add_column(c, justify="right")

    exploitables = 0
    for tick, r in series.items():
        positives = [a for a in autocorrs[tick] if a > 0]
        ac_max = max(positives) if positives else 0.0
        ac_neg = autocorrs[tick][0]
        vol = float(np.std(r))
        # Borne haute : en exploitant une autocorrelation rho, le gain espere
        # par transaction est de l'ordre de |rho| * sigma (cas parfait, sans
        # erreur de prevision). C'est genereux — la realite fait bien moins.
        gain = ac_max * vol
        cout = ACTIFS[tick] * 2
        net = gain - cout
        ok = net > 0
        exploitables += ok
        t.add_row(tick.replace("-USD", "").replace("=X", "").replace("=F", ""),
                  f"{ac_max:.3f}",
                  f"[dim]{ac_neg:+.3f}[/dim]",
                  f"{vol*100:.2f}%", f"{gain*100:.3f}%",
                  f"{cout*100:.3f}%",
                  f"[{'green' if ok else 'red'}]{net*100:+.3f}%[/]",
                  "oui" if ok else "non")
    console.print(t)

    console.print(f"\n  [bold]{exploitables}/{len(series)} actifs[/bold] ont une "
                  f"structure superieure a leurs couts, dans le cas le plus "
                  f"favorable imaginable")
    console.print("[dim]  Rappel : ce calcul suppose une prevision PARFAITE de "
                  "l'autocorrelation. Un modele reel en capte une fraction.[/dim]")


if __name__ == "__main__":
    main()
