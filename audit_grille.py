"""
audit_grille.py — La grille est-elle irrecuperable, ou juste mal simulee ?

Rejoue la grille REELLE (grid_sim, machine a etats de strategy.py) sur les 12
fenetres de regime, en croisant :
  - l'espacement
  - le bug du recentrage (positions orphelines) vs son correctif
  - hypothese de remplissage conservatrice vs optimiste

Le benchmark n'est pas zero mais le BUY & HOLD : la grille est long-only, elle
finit toujours par detenir du BTC. La comparer a zero reviendrait a lui
attribuer la performance du marche.

    python audit_grille.py
"""

import itertools
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from rich.console import Console
from rich.table import Table

from backtest_regimes import charger_donnees, decouper
from grid_sim import simuler

console = Console()

CAPITAL = 20.0
NIVEAUX = 2
FRAIS_KRAKEN = 0.0025
ESPACEMENTS = [0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
REBUILDS = [1.5, 3.0, 5.0, 20.0]


def _tache(args):
    df, esp, reb, abandon, tp_meme = args
    r = simuler(df, capital=CAPITAL, niveaux=NIVEAUX, espacement_pct=esp,
                frais=FRAIS_KRAKEN, rebuild_pct=reb,
                tp_meme_bougie=tp_meme, abandon_au_rebuild=abandon)
    return {
        "esp": esp, "reb": reb, "abandon": abandon, "tp_meme": tp_meme,
        "profit": r.profit, "rendement": r.rendement_pct,
        "buy_hold": r.buy_hold_pct, "cycles": r.cycles,
        "orphelin": r.valeur_orpheline, "frais": r.frais,
        "dd": r.max_drawdown_pct,
    }


def agreger(lignes):
    """Regroupe les 12 fenetres d'une meme combinaison de parametres."""
    n = len(lignes)
    surperf = [l["rendement"] - l["buy_hold"] for l in lignes]
    return {
        "profit_total": round(sum(l["profit"] for l in lignes), 2),
        "profit_median": round(sorted(l["profit"] for l in lignes)[n // 2], 2),
        "positives": sum(1 for l in lignes if l["profit"] > 0),
        "bat_bh": sum(1 for s in surperf if s > 0),
        "surperf_moy": round(sum(surperf) / n, 2),
        "cycles_moy": round(sum(l["cycles"] for l in lignes) / n),
        "orphelin_moy": round(sum(l["orphelin"] for l in lignes) / n, 2),
        "frais_moy": round(sum(l["frais"] for l in lignes) / n, 2),
        "dd_moy": round(sum(l["dd"] for l in lignes) / n, 1),
        "n": n,
    }


def main():
    df = charger_donnees("BTC/USDT", 1095)
    fenetres = decouper(df, 90)
    console.print(f"[green]{len(fenetres)} fenetres[/green] "
                  f"(frais Kraken maker {FRAIS_KRAKEN*100:.2f} %, capital {CAPITAL} $)\n")

    combos = list(itertools.product(ESPACEMENTS, REBUILDS, [True, False], [False, True]))
    taches = [(f["df"], esp, reb, ab, tp)
              for esp, reb, ab, tp in combos for f in fenetres]
    console.print(f"[cyan]{len(taches)} simulations sur "
                  f"{len(combos)} combinaisons...[/cyan]")

    with ProcessPoolExecutor() as pool:
        brut = list(pool.map(_tache, taches, chunksize=8))

    # Regroupement par combinaison
    groupes = {}
    for l in brut:
        cle = (l["esp"], l["reb"], l["abandon"], l["tp_meme"])
        groupes.setdefault(cle, []).append(l)
    agrege = {cle: agreger(v) for cle, v in groupes.items()}

    # ── Surperformance vs buy & hold : la seule metrique qui tranche ─────────
    # La grille est long-only. Face a zero elle encaisserait la hausse du BTC
    # comme si c'etait son merite ; face au B&H on mesure ce qu'elle APPORTE.
    for tp_meme in (False, True):
        t = Table(
            title=("Surperformance vs buy & hold — fill conservateur"
                   if not tp_meme else
                   "Surperformance vs buy & hold — fill optimiste (TP meme bougie)"),
            style="cyan")
        t.add_column("Espac.", justify="right")
        for reb in REBUILDS:
            t.add_column(f"recentr. {reb:.0f}%", justify="right")
        for esp in ESPACEMENTS:
            for abandon in (True, False):
                cellules = []
                for reb in REBUILDS:
                    a = agrege[(esp, reb, abandon, tp_meme)]
                    couleur = "green" if a["surperf_moy"] > 0 else "red"
                    cellules.append(
                        f"[{couleur}]{a['surperf_moy']:+6.1f}pt[/{couleur}] "
                        f"{a['bat_bh']}/{a['n']}")
                etiquette = (f"{esp:.1f}% actuel" if abandon else f"{esp:.1f}% corrige")
                t.add_row(etiquette, *cellules)
        console.print(t)
        console.print()

    # ── Meilleure combinaison selon le seul critere qui compte ───────────────
    meilleur = max(agrege.items(), key=lambda kv: kv[1]["surperf_moy"])
    (esp, reb, abandon, tp_meme), a = meilleur
    console.print(f"[bold]Meilleure surperformance vs buy & hold :[/bold] "
                  f"espacement {esp}%, recentrage {reb}%, "
                  f"{'code actuel' if abandon else 'corrige'}, "
                  f"fill {'optimiste' if tp_meme else 'conservateur'}")
    console.print(f"  surperformance moyenne {a['surperf_moy']:+.2f} pt, "
                  f"bat le B&H dans {a['bat_bh']}/{a['n']} fenetres, "
                  f"{a['cycles_moy']} cycles/fenetre")

    dossier = Path(__file__).resolve().parent / "donnees"
    dossier.mkdir(exist_ok=True)
    import json
    sortie = dossier / "audit_grille.json"
    sortie.write_text(json.dumps(
        [{"esp": k[0], "rebuild": k[1], "abandon": k[2], "tp_meme_bougie": k[3], **v}
         for k, v in agrege.items()], indent=2), encoding="utf-8")
    console.print(f"\n[blue]Detail : {sortie}[/blue]")


if __name__ == "__main__":
    main()
