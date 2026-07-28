"""
backtest_regimes.py — La grille tient-elle dans tous les régimes de marché ?

Le backtest de juillet portait sur UNE fenêtre de 90 j. Optimiser l'espacement
dessus revient à épouser les accidents de cette période : c'est exactement ce
qui produisait la courbe non monotone (1,0 % → +1,71 $ mais 1,5 % → +0,34 $).

Ici on découpe l'historique en fenêtres non chevauchantes, on classe chacune
par son régime constaté (hausse / baisse / range), et on evalue chaque
espacement sur TOUTES. Le critere retenu n'est pas le profit moyen — une seule
fenetre extraordinaire suffit a le gonfler — mais la **robustesse** : combien
de fenetres finissent positives, et quelle est la pire.

    python backtest_regimes.py --jours 1095 --fenetre 90

Les donnees viennent des endpoints PUBLICS Bybit (non geo-bloques au Canada),
les frais simules sont ceux de Kraken, ou l'execution aura lieu.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd
from rich.console import Console
from rich.table import Table

from grid_sim import simuler

console = Console()
CACHE = Path(__file__).resolve().parent / "donnees"
CACHE.mkdir(exist_ok=True)

# Kraken, palier de base (verifie via ccxt le 2026-07-27)
FRAIS_MAKER = 0.0025
FRAIS_TAKER = 0.0040

# Seuils de classement d'un regime, sur le rendement de la fenetre
SEUIL_TENDANCE = 15.0  # +/- 15 % sur la fenetre


def charger_donnees(symbole: str, jours: int, timeframe: str = "1h") -> pd.DataFrame:
    """Telecharge et met en cache. Refaire 18 appels reseau a chaque essai de
    parametre est le meilleur moyen de ne pas relancer le test."""
    cache = CACHE / f"ohlcv_{symbole.replace('/', '')}_{timeframe}_{jours}j.csv"
    if cache.exists():
        age_h = (datetime.now().timestamp() - cache.stat().st_mtime) / 3600
        if age_h < 24:
            df = pd.read_csv(cache, index_col="time", parse_dates=True)
            console.print(f"[green]{len(df)} bougies (cache, {age_h:.1f} h)[/green]")
            return df

    console.print(f"[cyan]Telechargement {symbole} {jours}j ({timeframe})...[/cyan]")
    ex = ccxt.bybit({"enableRateLimit": True})
    depuis = ex.parse8601(
        (datetime.now(timezone.utc) - timedelta(days=jours)).strftime("%Y-%m-%dT00:00:00Z")
    )

    # Ne PAS s'arreter sur `len(lot) < limit` : Bybit renvoie 999 des la 2e page
    # (decalage du `since + 1`), ce qui tronquait silencieusement l'historique a
    # ~2000 bougies. On s'arrete quand le lot est vide ou n'avance plus.
    tout = []
    maintenant = ex.milliseconds()
    while depuis < maintenant:
        lot = ex.fetch_ohlcv(symbole, timeframe, since=depuis, limit=1000)
        if not lot:
            break
        tout.extend(lot)
        suivant = lot[-1][0] + 1
        if suivant <= depuis:  # pas de progression : on tourne en rond
            break
        depuis = suivant

    df = pd.DataFrame(tout, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df.set_index("time")
    df.to_csv(cache)
    console.print(f"[green]{len(df)} bougies chargees[/green]")
    return df


def decouper(df: pd.DataFrame, jours_fenetre: int, timeframe_h: int = 1) -> list:
    """Fenetres non chevauchantes. Le chevauchement gonflerait artificiellement
    le nombre d'observations en reutilisant les memes bougies."""
    taille = jours_fenetre * 24 // timeframe_h
    fenetres = []
    for debut in range(0, len(df) - taille + 1, taille):
        f = df.iloc[debut:debut + taille]
        rendement = (f["close"].iloc[-1] - f["close"].iloc[0]) / f["close"].iloc[0] * 100
        if rendement > SEUIL_TENDANCE:
            regime = "hausse"
        elif rendement < -SEUIL_TENDANCE:
            regime = "baisse"
        else:
            regime = "range"
        fenetres.append({
            "df": f,
            "debut": f.index[0],
            "fin": f.index[-1],
            "buy_hold_pct": rendement,
            "regime": regime,
        })
    return fenetres


def evaluer(fenetres: list, capital: float, niveaux: int, espacement: float,
            frais: float, rebuild: float) -> dict:
    """Joue un espacement sur toutes les fenetres et agrege la robustesse.

    Utilise `grid_sim.simuler` (machine a etats fidele, sans lookahead) et non
    l'ancien backtest simplifie, qui surestimait le brut d'un facteur 2 et se
    remplissait avec de l'information future."""
    resultats = []
    for f in fenetres:
        r = simuler(f["df"], capital=capital, niveaux=niveaux,
                    espacement_pct=espacement, frais=frais,
                    rebuild_pct=rebuild, abandon_au_rebuild=False)
        resultats.append({
            "regime": f["regime"],
            "debut": str(f["debut"].date()),
            "profit": r.profit,
            "trades": r.cycles,
            "rendement_pct": r.rendement_pct,
            "buy_hold_pct": round(f["buy_hold_pct"], 2),
        })

    profits = [r["profit"] for r in resultats]
    positives = sum(1 for p in profits if p > 0)
    return {
        "espacement": espacement,
        "profit_total": round(sum(profits), 2),
        "profit_median": round(sorted(profits)[len(profits) // 2], 2),
        "pire": round(min(profits), 2),
        "meilleure": round(max(profits), 2),
        "fenetres_positives": positives,
        "fenetres": len(profits),
        "trades_moyen": round(sum(r["trades"] for r in resultats) / len(resultats)),
        "detail": resultats,
    }


def main():
    p = argparse.ArgumentParser(description="Backtest multi-regimes")
    p.add_argument("--symbole", default="BTC/USDT")
    p.add_argument("--jours", type=int, default=1095)
    p.add_argument("--fenetre", type=int, default=90, help="taille d'une fenetre en jours")
    p.add_argument("--capital", type=float, default=20.0)
    p.add_argument("--niveaux", type=int, default=2)
    p.add_argument("--rebuild", type=float, default=1.5)
    p.add_argument("--frais", type=float, default=FRAIS_MAKER)
    args = p.parse_args()

    df = charger_donnees(args.symbole, args.jours)
    fenetres = decouper(df, args.fenetre)

    if not fenetres:
        console.print("[red]Pas assez de donnees pour une seule fenetre.[/red]")
        return

    # ── Inventaire des regimes ───────────────────────────────────────────────
    t = Table(title=f"Fenetres de {args.fenetre} j — {len(fenetres)} observations",
              style="cyan")
    for col in ("Debut", "Fin", "Buy & Hold", "Regime"):
        t.add_column(col)
    for f in fenetres:
        couleur = {"hausse": "green", "baisse": "red", "range": "yellow"}[f["regime"]]
        t.add_row(str(f["debut"].date()), str(f["fin"].date()),
                  f"{f['buy_hold_pct']:+.1f}%", f"[{couleur}]{f['regime']}[/{couleur}]")
    console.print(t)

    comptes = {}
    for f in fenetres:
        comptes[f["regime"]] = comptes.get(f["regime"], 0) + 1
    console.print(f"Repartition : {comptes}\n")

    # ── Balayage de l'espacement ─────────────────────────────────────────────
    espacements = [0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0]
    console.print(f"[yellow]Balayage sur {len(fenetres)} fenetres, "
                  f"frais {args.frais*100:.2f} %/ordre, "
                  f"recentrage {args.rebuild} %, capital {args.capital} $[/yellow]\n")

    agrege = []
    for esp in espacements:
        agrege.append(evaluer(fenetres, args.capital, args.niveaux, esp,
                              args.frais, args.rebuild))

    t = Table(title="Robustesse par espacement", style="cyan")
    for col, just in (("Espac.", "right"), ("Positives", "right"), ("Total", "right"),
                      ("Median", "right"), ("Pire", "right"), ("Meilleure", "right"),
                      ("Trades/fen.", "right")):
        t.add_column(col, justify=just)
    for a in agrege:
        ratio = a["fenetres_positives"] / a["fenetres"]
        couleur = "green" if ratio >= 0.6 else ("yellow" if ratio >= 0.4 else "red")
        t.add_row(
            f"{a['espacement']:.1f}%",
            f"[{couleur}]{a['fenetres_positives']}/{a['fenetres']}[/{couleur}]",
            f"{a['profit_total']:+.2f}$",
            f"{a['profit_median']:+.2f}$",
            f"{a['pire']:+.2f}$",
            f"{a['meilleure']:+.2f}$",
            str(a["trades_moyen"]),
        )
    console.print(t)

    # ── Detail par regime, pour le meilleur candidat robuste ─────────────────
    meilleur = max(agrege, key=lambda a: (a["fenetres_positives"], a["profit_median"]))
    console.print(f"\n[bold]Plus robuste : espacement {meilleur['espacement']}% "
                  f"({meilleur['fenetres_positives']}/{meilleur['fenetres']} fenetres "
                  f"positives)[/bold]")

    t = Table(title=f"Detail a {meilleur['espacement']}% par regime", style="cyan")
    for col in ("Debut", "Regime", "Buy & Hold", "Grille", "Profit", "Trades"):
        t.add_column(col, justify="right")
    for d in meilleur["detail"]:
        couleur = "green" if d["profit"] > 0 else "red"
        t.add_row(d["debut"], d["regime"], f"{d['buy_hold_pct']:+.1f}%",
                  f"{d['rendement_pct']:+.2f}%",
                  f"[{couleur}]{d['profit']:+.2f}$[/{couleur}]", str(d["trades"]))
    console.print(t)

    # ── Stress test : et si les fills partent en taker ? ─────────────────────
    console.print(f"\n[yellow]Stress test — memes espacements aux frais taker "
                  f"({FRAIS_TAKER*100:.2f} %)[/yellow]")
    t = Table(style="cyan")
    for col in ("Espac.", "Positives", "Total", "Pire"):
        t.add_column(col, justify="right")
    for esp in espacements:
        a = evaluer(fenetres, args.capital, args.niveaux, esp, FRAIS_TAKER, args.rebuild)
        ratio = a["fenetres_positives"] / a["fenetres"]
        couleur = "green" if ratio >= 0.6 else ("yellow" if ratio >= 0.4 else "red")
        t.add_row(f"{esp:.1f}%",
                  f"[{couleur}]{a['fenetres_positives']}/{a['fenetres']}[/{couleur}]",
                  f"{a['profit_total']:+.2f}$", f"{a['pire']:+.2f}$")
    console.print(t)

    sortie = CACHE / f"regimes_{args.symbole.replace('/', '')}_{args.fenetre}j.json"
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump({
            "parametres": vars(args),
            "regimes": comptes,
            "resultats": agrege,
        }, f, indent=2, ensure_ascii=False, default=str)
    console.print(f"\n[blue]Resultats : {sortie}[/blue]")


if __name__ == "__main__":
    main()
