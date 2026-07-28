"""
test_momentum_cross_asset.py — Le momentum est-il un PHENOMENE reel ?

Test scientifique, pas operationnel. On ne cherche pas une strategie tradable
sur Kraken : on cherche a savoir si le suivi de tendance est detectable
statistiquement sur des marches decorreles et sur un historique long.

Protocole (v5, apres plusieurs revisions) :
  - EMA 10/30 jours, long/cash, signal DECALE d'une barre (aucun lookahead)
  - 10 actifs repartis en 5 classes
  - Decision AU NIVEAU DES CLASSES, pas des actifs : SPY/QQQ/IWM correles a
    0,9 ne sont pas 3 observations. Le comptage par actif reste affiche, mais
    a titre d'information seulement.
  - Correction de significativite sur le nombre EFFECTIF de tests
    independants : N_eff = N / (1 + rho_moyen * (N - 1))
  - Test de permutation : on melange les rendements de chaque actif (meme
    distribution, structure temporelle detruite). Si le hasard fait aussi
    bien, il n'y a pas de phenomene.
  - Analyse de sensibilite sans les contrats a terme (GC/CL/SI) : leurs
    enchainements de contrats creent des discontinuites de roulement qui
    peuvent fabriquer de fausses tendances.

Verdict : PHENOMENE VALIDE / NON DETECTE / INCONCLUSANT

    python test_momentum_cross_asset.py
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

RAPIDE, LENT = 10, 30
N_PERMUTATIONS = 500

# Couts aller-retour realistes PAR CLASSE. Utiliser le cout crypto partout
# fausserait le test : un ETF ne coute pas 0,36 % a traiter.
CLASSES = {
    "US Equities":   {"actifs": ["SPY", "QQQ", "IWM"],            "cout": 0.0005},
    "International": {"actifs": ["EFA", "EEM"],                   "cout": 0.0005},
    "Devises":       {"actifs": ["EURUSD=X", "GBPUSD=X", "JPY=X"], "cout": 0.0002},
    "Matieres":      {"actifs": ["GC=F", "CL=F", "SI=F"],         "cout": 0.0005},
    "Crypto":        {"actifs": ["BTC-USD", "ETH-USD"],           "cout": 0.0036},
}
# Classes retenues pour la DECISION (la crypto est mesuree mais exclue :
# c'est le marche qu'on veut eventuellement trader, l'y inclure reviendrait
# a valider le phenomene sur son terrain d'application).
CLASSES_DECISION = ["US Equities", "International", "Devises", "Matieres"]

FUTURES = {"GC=F", "CL=F", "SI=F"}


def telecharger(ticker: str) -> pd.Series:
    df = yf.download(ticker, period="max", auto_adjust=True,
                     progress=False, multi_level_index=False)
    if df is None or df.empty or "Close" not in df:
        return pd.Series(dtype=float)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def momentum(prix: pd.Series, cout: float, rapide=RAPIDE, lent=LENT) -> dict:
    er = prix.ewm(span=rapide, adjust=False).mean()
    el = prix.ewm(span=lent, adjust=False).mean()
    pos = (er > el).shift(1).fillna(False).astype(float)

    rdt = prix.pct_change().fillna(0.0)
    net = pos * rdt - pos.diff().abs().fillna(0.0) * cout

    eq = (1 + net).cumprod()
    bh = (1 + rdt).cumprod()

    def dd(s):
        return float(((s.cummax() - s) / s.cummax()).max() * 100)

    sd, sd_bh = net.std(), rdt.std()
    return {
        "rdt": float((eq.iloc[-1] - 1) * 100),
        "rdt_bh": float((bh.iloc[-1] - 1) * 100),
        "sharpe": float(net.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
        "sharpe_bh": float(rdt.mean() / sd_bh * np.sqrt(252)) if sd_bh > 0 else 0.0,
        "dd": dd(eq), "dd_bh": dd(bh),
        "trades": int(pos.diff().abs().sum()),
        "annees": len(prix) / 252,
        "net": net, "brut": rdt,
    }


def n_effectif(rendements: pd.DataFrame) -> tuple:
    corr = rendements.corr()
    hors = corr.to_numpy()[np.triu_indices(len(corr), k=1)]
    rho = float(np.nanmean(hors))
    n = len(corr)
    return n / (1 + rho * (n - 1)), rho, float(np.nanmin(hors)), float(np.nanmax(hors))


def main():
    console.print(f"[bold]Momentum EMA {RAPIDE}/{LENT} — test cross-asset[/bold]\n")

    donnees, resultats = {}, {}
    for classe, cfg in CLASSES.items():
        for t in cfg["actifs"]:
            s = telecharger(t)
            if len(s) < 1500:
                console.print(f"  [yellow]{t}: {len(s)} jours — ignore[/yellow]")
                continue
            donnees[t] = s
            resultats[t] = momentum(s, cfg["cout"])
            resultats[t]["classe"] = classe

    # ── Detail par actif (information, PAS decision) ─────────────────────────
    t = Table(title="Par actif — information seulement", style="cyan")
    for c in ("Actif", "Classe", "Ans", "Strat.", "B&H", "Sharpe", "S.B&H",
              "DD", "DD B&H", "Trades"):
        t.add_column(c, justify="right")
    for tick, r in resultats.items():
        gagne = r["rdt"] > r["rdt_bh"]
        t.add_row(tick, r["classe"][:9], f"{r['annees']:.0f}",
                  f"[{'green' if gagne else 'red'}]{r['rdt']:+.0f}%[/]",
                  f"{r['rdt_bh']:+.0f}%", f"{r['sharpe']:.2f}",
                  f"{r['sharpe_bh']:.2f}", f"{r['dd']:.0f}%", f"{r['dd_bh']:.0f}%",
                  str(r["trades"]))
    console.print(t)

    # ── Agregation PAR CLASSE — c'est ici que se decide le verdict ───────────
    console.print("\n[bold]Par classe — base de la decision[/bold]")
    t = Table(style="cyan")
    for c in ("Classe", "Actifs", "Rdt moy", "B&H moy", "Sharpe", "S.B&H",
              "DD", "DD B&H", "3 criteres"):
        t.add_column(c, justify="right")

    classes_ok = {}
    for classe in CLASSES:
        membres = [r for r in resultats.values() if r["classe"] == classe]
        if not membres:
            continue
        moy = lambda k: float(np.mean([m[k] for m in membres]))  # noqa: E731
        c1 = moy("rdt") > moy("rdt_bh")
        c2 = moy("sharpe") > moy("sharpe_bh")
        c3 = moy("dd") < moy("dd_bh")
        ok = c1 and c2 and c3
        classes_ok[classe] = ok
        marques = ("V" if c1 else "x") + ("V" if c2 else "x") + ("V" if c3 else "x")
        t.add_row(classe, str(len(membres)), f"{moy('rdt'):+.0f}%",
                  f"{moy('rdt_bh'):+.0f}%", f"{moy('sharpe'):.2f}",
                  f"{moy('sharpe_bh'):.2f}", f"{moy('dd'):.0f}%",
                  f"{moy('dd_bh'):.0f}%",
                  f"[{'green' if ok else 'red'}]{marques}[/]")
    console.print(t)
    console.print("[dim]criteres : rendement > B&H | Sharpe > Sharpe B&H | DD < DD B&H[/dim]")

    valides = sum(1 for c in CLASSES_DECISION if classes_ok.get(c))
    console.print(f"\n  [bold]{valides}/{len(CLASSES_DECISION)} classes de decision "
                  f"valident[/bold]  (crypto mesuree mais exclue du verdict)")

    # ── Independance reelle ─────────────────────────────────────────────────
    rdts = pd.DataFrame({k: v["brut"] for k, v in resultats.items()}).dropna()
    neff, rho, rmin, rmax = n_effectif(rdts)
    console.print(f"\n[bold]Independance[/bold]")
    console.print(f"  correlation moyenne {rho:.2f} (min {rmin:.2f}, max {rmax:.2f})")
    console.print(f"  {len(resultats)} actifs -> [bold]{neff:.1f} tests independants[/bold]")

    # ── Portefeuille equipondere PAR CLASSE ─────────────────────────────────
    parts_net, parts_bh = [], []
    for classe in CLASSES:
        membres = [k for k, v in resultats.items() if v["classe"] == classe]
        if membres:
            parts_net.append(pd.DataFrame({k: resultats[k]["net"] for k in membres}).mean(axis=1))
            parts_bh.append(pd.DataFrame({k: resultats[k]["brut"] for k in membres}).mean(axis=1))
    pf_net = pd.concat(parts_net, axis=1).dropna().mean(axis=1)
    pf_bh = pd.concat(parts_bh, axis=1).dropna().mean(axis=1)

    def stats(s):
        eq = (1 + s).cumprod()
        return ((eq.iloc[-1] - 1) * 100,
                s.mean() / s.std() * np.sqrt(252),
                float(((eq.cummax() - eq) / eq.cummax()).max() * 100))

    r_m, s_m, d_m = stats(pf_net)
    r_b, s_b, d_b = stats(pf_bh)
    console.print(f"\n[bold]Portefeuille equipondere par classe[/bold]")
    console.print(f"  momentum   {r_m:+8.0f} %   Sharpe {s_m:5.2f}   DD {d_m:.0f} %")
    console.print(f"  buy & hold {r_b:+8.0f} %   Sharpe {s_b:5.2f}   DD {d_b:.0f} %")

    # ── Permutation ─────────────────────────────────────────────────────────
    console.print(f"\n[bold]Test de permutation ({N_PERMUTATIONS} tirages)[/bold]")
    reel = s_m - s_b
    rng = np.random.default_rng(7)
    tirages = []
    for _ in range(N_PERMUTATIONS):
        faux = []
        for tick, r in resultats.items():
            melange = rng.permutation(r["brut"].to_numpy())
            serie = pd.Series(float(donnees[tick].iloc[0]) * np.cumprod(1 + melange),
                              index=r["brut"].index)
            faux.append(momentum(serie, CLASSES[r["classe"]]["cout"])["net"])
        pf = pd.concat(faux, axis=1).dropna().mean(axis=1)
        tirages.append(pf.mean() / pf.std() * np.sqrt(252) - s_b)
    tirages = np.array(tirages)
    p = float((tirages >= reel).mean())
    p_corrige = min(1.0, p * max(1.0, neff))

    console.print(f"  ecart de Sharpe reel     : {reel:+.3f}")
    console.print(f"  moyenne des tirages      : {tirages.mean():+.3f}")
    console.print(f"  p-value brute            : {p:.4f}")
    console.print(f"  p-value corrigee (N_eff) : [bold]{p_corrige:.4f}[/bold]")

    # ── Sensibilite : sans les contrats a terme ─────────────────────────────
    console.print(f"\n[bold]Sensibilite — sans les futures (GC/CL/SI)[/bold]")
    console.print("[dim]Contrats enchaines : les roulements peuvent fabriquer de "
                  "fausses tendances. Le resultat en depend-il ?[/dim]")
    sans = {k: v for k, v in resultats.items() if k not in FUTURES}
    p_net = pd.DataFrame({k: v["net"] for k, v in sans.items()}).dropna().mean(axis=1)
    p_bh = pd.DataFrame({k: v["brut"] for k, v in sans.items()}).dropna().mean(axis=1)
    r2, s2, d2 = stats(p_net)
    r2b, s2b, d2b = stats(p_bh)
    console.print(f"  momentum   {r2:+8.0f} %   Sharpe {s2:5.2f}   DD {d2:.0f} %")
    console.print(f"  buy & hold {r2b:+8.0f} %   Sharpe {s2b:5.2f}   DD {d2b:.0f} %")

    # ── Verdict ─────────────────────────────────────────────────────────────
    console.print("\n" + "=" * 66)
    assez = neff >= 3 and min(r["annees"] for r in resultats.values()) >= 5
    if not assez:
        verdict, couleur = "INCONCLUSANT (donnees insuffisantes)", "yellow"
    elif valides >= 3 and p_corrige < 0.05:
        verdict, couleur = "PHENOMENE VALIDE", "green"
    else:
        verdict, couleur = "PHENOMENE NON DETECTE", "red"
    console.print(f"[bold {couleur}]{verdict}[/bold {couleur}]")
    console.print(f"  classes validant : {valides}/{len(CLASSES_DECISION)} (requis 3)")
    console.print(f"  p corrigee : {p_corrige:.4f} (requis < 0,05)")
    console.print(f"  N_eff : {neff:.1f} (requis >= 3)")
    console.print("=" * 66)


if __name__ == "__main__":
    main()
