"""
mur_de_frais.py — Toute strategie candidate doit franchir CE mur.

Outil de tri, a passer AVANT de coder ou de backtester quoi que ce soit trouve
dans un livre ou un depot GitHub. Il repond a une seule question :

    "Avec les frais de MA plateforme, quel avantage brut par trade cette
     strategie doit-elle avoir pour seulement ne pas perdre ?"

Le frottement ne depend pas du capital : il est proportionnel. Multiplier son
capital par cent ne change RIEN au pourcentage. Le seul levier est de trader
moins souvent, ou d'avoir un avantage plus gros par trade.

    python mur_de_frais.py

Cas d'usage : un depot annonce "65 % de reussite, TP 1 %, SL 1 %, 400 trades
par mois". Entre ces chiffres ici. Si la colonne 'net' est negative, inutile
d'aller plus loin — quel que soit le reste du code.
"""

from rich.console import Console
from rich.table import Table

console = Console()

# ATTENTION — ccxt donne DEUX chiffres contradictoires pour le palier de base :
#   market['maker']/['taker']        -> 0,25 % / 0,40 %
#   fees['trading']['tiers'][0]      -> 0,16 % / 0,26 %
# La table de paliers est la plus credible (elle correspond au bareme Kraken Pro),
# mais SEUL ton compte fait foi : Kraken affiche ton palier reel dans
# Parametres > Frais. Verifie avant de te fier a ces chiffres.
#
# Cela dit, la conclusion sur la grille NE DEPEND PAS de ce choix : testee a
# 0,25 %, a 0,16 % et meme a 0 % de frais, elle ne bat jamais le buy & hold.
MAKER = 0.0016
TAKER = 0.0026


def cout_aller_retour(entree_maker: bool, sortie_maker: bool) -> float:
    return (MAKER if entree_maker else TAKER) + (MAKER if sortie_maker else TAKER)


def net_par_trade(taux_reussite: float, gain_pct: float, perte_pct: float,
                  cout_ar: float) -> float:
    """Esperance nette par aller-retour, en % du notionnel."""
    brut = taux_reussite * gain_pct - (1 - taux_reussite) * perte_pct
    return brut - cout_ar * 100


def main():
    console.print("[bold]Le mur des frais — Kraken palier de base[/bold]")
    console.print(f"maker {MAKER*100:.2f} % | taker {TAKER*100:.2f} %\n")

    t = Table(title="Cout d'un aller-retour selon l'execution", style="cyan")
    t.add_column("Entree"); t.add_column("Sortie")
    t.add_column("Cout A/R", justify="right")
    t.add_column("Il faut gagner au moins", justify="right")
    for e_m, s_m, libelle in ((True, True, "limite / limite"),
                              (True, False, "limite / marche"),
                              (False, False, "marche / marche")):
        c = cout_aller_retour(e_m, s_m)
        t.add_row("limite" if e_m else "marche", "limite" if s_m else "marche",
                  f"{c*100:.2f} %", f"> {c*100:.2f} % brut par cycle")
    console.print(t)

    console.print("\n[bold]Avantage minimum requis, selon le profil annonce[/bold]")
    console.print("[dim]Un TP et un SL de meme taille = il faut un taux de "
                  "reussite bien superieur a 50 % juste pour payer les frais.[/dim]\n")

    t = Table(style="cyan")
    t.add_column("TP / SL", justify="right")
    t.add_column("Reussite requise\n(limite/limite)", justify="right")
    t.add_column("Reussite requise\n(limite/marche)", justify="right")
    t.add_column("Reussite requise\n(marche/marche)", justify="right")

    for cible in (0.5, 1.0, 2.0, 3.0, 5.0):
        cellules = []
        for e_m, s_m in ((True, True), (True, False), (False, False)):
            cout = cout_aller_retour(e_m, s_m) * 100
            # w*cible - (1-w)*cible = cout  ->  w = (cout + cible) / (2*cible)
            w = (cout + cible) / (2 * cible)
            couleur = "green" if w < 0.60 else ("yellow" if w < 0.70 else "red")
            texte = f"[{couleur}]{w*100:.1f} %[/{couleur}]" if w < 1 else "[red]impossible[/red]"
            cellules.append(texte)
        t.add_row(f"{cible:.1f} % / {cible:.1f} %", *cellules)
    console.print(t)

    console.print("\n[bold]Traduction en cout annuel selon la frequence[/bold]")
    console.print("[dim]Base 100 unites de capital, notionnel 50 par trade "
                  "(la moitie du capital travaille a chaque position). Le "
                  "frottement seul, avant meme de parler de gains ou de "
                  "pertes.[/dim]\n")

    CAPITAL, NOTIONNEL = 100.0, 50.0
    t = Table(style="cyan")
    t.add_column("Trades / mois", justify="right")
    t.add_column("Frais / an", justify="right")
    t.add_column("En % du capital", justify="right")
    for par_mois in (10, 50, 100, 400, 1000):
        cout_an = par_mois * 12 * NOTIONNEL * cout_aller_retour(True, True)
        pct = cout_an / CAPITAL * 100
        couleur = "green" if pct < 20 else ("yellow" if pct < 100 else "red")
        t.add_row(str(par_mois), f"{cout_an:.2f}",
                  f"[{couleur}]{pct:.0f} %[/{couleur}]")
    console.print(t)

    console.print("\n[bold yellow]Comment s'en servir[/bold yellow]")
    console.print("1. Une strategie annonce ses chiffres -> verifie qu'ils passent "
                  "le mur AVANT de coder quoi que ce soit.")
    console.print("2. Si elle ne publie pas taux de reussite, TP/SL et frequence, "
                  "elle n'est pas evaluable. Passe ton chemin.")
    console.print("3. Si elle les publie mais sans frais dans son backtest, "
                  "refais le calcul toi-meme : c'est la ligne 'net' qui compte.")
    console.print("4. Fais tourner la strategie dans grid_sim / ta chaine de test "
                  "avant tout argent reel. Le backtest de l'auteur ne vaut rien.")


if __name__ == "__main__":
    main()
