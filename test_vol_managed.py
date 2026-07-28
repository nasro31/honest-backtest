"""
test_vol_managed.py — Piste 1 : gestion par la volatilite realisee.

Fondement academique : Moreira & Muir (2017), "Volatility-Managed Portfolios"
— reduire l'exposition quand la volatilite recente est elevee ameliorerait le
rendement ajuste au risque. Contrairement au carry ou aux options, c'est la
seule piste de la liste realisable avec un compte SPOT (long/cash uniquement).

Deux variantes testees :
  A. REGIME BINAIRE (specification de Nacer) : long si ATR20/ATR100 < seuil,
     cash sinon.
  B. ECHELLE CONTINUE (specification Moreira-Muir) : exposition proportionnelle
     a 1/variance du mois precedent, plafonnee.

Garde-fous herites des tests precedents :
  - signal decale d'une barre, volatilite estimee sur le PASSE uniquement
  - decision au niveau des CLASSES d'actifs, pas des actifs correles
  - test de permutation : les deux variantes sont long/cash, donc soumises au
    plancher mecanique de Sharpe (+0,13 mesure precedemment). La permutation
    le mesure et on ne compare qu'a lui.
  - CORRECTION AU NIVEAU DU PROJET : c'est la 5e famille testee sur les memes
    donnees. Le seuil n'est plus 0,05 mais 0,05/N_STRATEGIES.

    python test_vol_managed.py
"""

import warnings

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")
console = Console()

# Familles deja testees sur ce meme jeu de donnees : grille, momentum EMA
# long/cash, momentum MOP long/short, carry (verifie mais non teste), et
# celle-ci. Tester N hypotheses sur les memes donnees gonfle mecaniquement la
# chance d'un faux positif ; le seuil doit etre divise par N.
N_STRATEGIES_TESTEES = 5
SEUIL = 0.05 / N_STRATEGIES_TESTEES

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


def vol_managed(prix: pd.Series, cout: float, mode: str = "continu",
                seuil_ratio: float = 1.0, cible: float = 0.15,
                expo_max: float = 1.5) -> dict:
    rdt = prix.pct_change()

    if mode == "binaire":
        # Ratio vol courte / vol longue. < seuil = regime calme = investi.
        vol_courte = rdt.rolling(20).std()
        vol_longue = rdt.rolling(100).std()
        ratio = (vol_courte / vol_longue).shift(1)
        position = (ratio < seuil_ratio).astype(float)
        debut = 100
    else:
        # Moreira-Muir : exposition inverse a la variance du mois precedent.
        vol = rdt.rolling(21).std().shift(1) * np.sqrt(252)
        position = (cible / vol).clip(upper=expo_max).fillna(0.0)
        debut = 22

    position = position.fillna(0.0)
    net = (position * rdt - position.diff().abs().fillna(0.0) * cout).fillna(0.0)

    valides = net.iloc[debut:]
    bh = rdt.iloc[debut:].fillna(0.0)
    if len(valides) < 500:
        return None

    def st(s):
        eq = (1 + s).cumprod()
        sd = s.std()
        return ((eq.iloc[-1] - 1) * 100,
                float(s.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
                float(((eq.cummax() - eq) / eq.cummax()).max() * 100))

    r, sh, dd = st(valides)
    rb, shb, ddb = st(bh)
    return {"rdt": r, "rdt_bh": rb, "sharpe": sh, "sharpe_bh": shb,
            "dd": dd, "dd_bh": ddb, "annees": len(valides) / 252,
            "expo": float(position.iloc[debut:].mean()),
            "net": valides, "brut": bh}


def portefeuille(res: dict, cle="net") -> pd.Series:
    parts = []
    for classe in CLASSES:
        m = [k for k, v in res.items() if v["classe"] == classe]
        if m:
            parts.append(pd.DataFrame({k: res[k][cle] for k in m}).mean(axis=1))
    return pd.concat(parts, axis=1).dropna().mean(axis=1)


def sharpe(s):
    return float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0


def main():
    console.print("[bold]Piste 1 — gestion par la volatilite realisee[/bold]")
    console.print(f"[dim]{N_STRATEGIES_TESTEES}e famille testee sur ces donnees "
                  f"-> seuil corrige p < {SEUIL:.4f} (et non 0,05)[/dim]\n")

    donnees, res = {}, {}
    for classe, cfg in CLASSES.items():
        for t in cfg["actifs"]:
            s = telecharger(t)
            if len(s) < 1500:
                continue
            donnees[t] = s
            for mode in ("binaire", "continu"):
                r = vol_managed(s, cfg["cout"], mode=mode)
                if r:
                    r["classe"] = classe
                    res.setdefault(mode, {})[t] = r

    for mode in ("binaire", "continu"):
        titre = ("A. Regime binaire (ATR20/ATR100 < 1)" if mode == "binaire"
                 else "B. Echelle continue (Moreira-Muir, 1/variance)")
        console.print(f"\n[bold]{titre}[/bold]")

        t = Table(style="cyan")
        for c in ("Classe", "Rdt moy", "B&H moy", "Sharpe", "S.B&H", "DD",
                  "DD B&H", "Expo"):
            t.add_column(c, justify="right")
        classes_ok = 0
        for classe in CLASSES:
            m = [v for v in res[mode].values() if v["classe"] == classe]
            if not m:
                continue
            moy = lambda k: float(np.mean([x[k] for x in m]))  # noqa: E731
            ok = moy("sharpe") > moy("sharpe_bh")
            classes_ok += ok and classe != "Crypto"
            t.add_row(classe, f"{moy('rdt'):+.0f}%", f"{moy('rdt_bh'):+.0f}%",
                      f"[{'green' if ok else 'red'}]{moy('sharpe'):.2f}[/]",
                      f"{moy('sharpe_bh'):.2f}", f"{moy('dd'):.0f}%",
                      f"{moy('dd_bh'):.0f}%", f"{moy('expo'):.2f}")
        console.print(t)

        pf = portefeuille(res[mode])
        pf_bh = portefeuille(res[mode], "brut")
        s_st, s_bh = sharpe(pf), sharpe(pf_bh)
        eq = (1 + pf).cumprod()
        eqb = (1 + pf_bh).cumprod()
        console.print(f"  portefeuille : {(eq.iloc[-1]-1)*100:+.0f} % "
                      f"Sharpe {s_st:.2f}  |  B&H {(eqb.iloc[-1]-1)*100:+.0f} % "
                      f"Sharpe {s_bh:.2f}  |  ecart [bold]{s_st-s_bh:+.3f}[/bold]")

        # ── Permutation ─────────────────────────────────────────────────────
        rng = np.random.default_rng(23)
        tirages = []
        for _ in range(N_PERMUTATIONS):
            faux = {}
            for tick, r in res[mode].items():
                mel = rng.permutation(donnees[tick].pct_change().dropna().to_numpy())
                serie = pd.Series(float(donnees[tick].iloc[0]) * np.cumprod(1 + mel),
                                  index=donnees[tick].index[1:])
                f = vol_managed(serie, CLASSES[r["classe"]]["cout"], mode=mode)
                if f:
                    f["classe"] = r["classe"]
                    faux[tick] = f
            if faux:
                tirages.append(sharpe(portefeuille(faux)) - s_bh)
        tirages = np.array(tirages)
        reel = s_st - s_bh
        p = float((tirages >= reel).mean())

        couleur = "green" if p < SEUIL else "red"
        console.print(f"  plancher du hasard : {tirages.mean():+.3f}   "
                      f"reel : {reel:+.3f}")
        console.print(f"  [bold {couleur}]p = {p:.4f}[/bold {couleur}] "
                      f"(seuil corrige {SEUIL:.4f}) — "
                      f"{'SIGNIFICATIF' if p < SEUIL else 'non significatif'}"
                      f"{'  [mais passerait a 0,05 non corrige]' if SEUIL <= p < 0.05 else ''}")
        console.print(f"  classes hors crypto validant : {classes_ok}/4")


if __name__ == "__main__":
    main()
