"""
grid_sim.py — Simulateur FIDELE de la grille reellement implementee.

`backtest.backtest_grid` simulait une grille idealisee qui n'a jamais existe
dans le bot. Trois ecarts majeurs, tous dans le sens favorable :

  1. LOOKAHEAD (corrige le 27/07 dans backtest.py) — la grille etait recentree
     sur le `close` puis remplie contre le `low`/`high` de la MEME bougie.

  2. BRUT DOUBLE — le backtest achetait a `centre*(1-esp)` et vendait a
     `centre*(1+esp)`, soit 2 espacements d'ecart. La production pose sa vente
     take-profit a `prix_achat*(1+esp)` (strategy.py:115) : UN espacement.
     Le gain brut par cycle etait donc surestime d'un facteur 2.

  3. AUCUN SUIVI D'ETAT — un niveau se remplissait a chaque bougie qui touchait
     son prix, sans qu'un achat doive etre revendu avant d'etre repris, et les
     ventes n'etaient pas appariees a leur prix d'achat.

Ce module reproduit la machine a etats reelle : build_grid -> on_buy_filled ->
on_sell_filled -> rearmement de l'achat au prix d'entree.

Il modelise aussi le comportement du recentrage tel qu'il est CODE aujourd'hui
(bot.py:141) : `build_grid` remplace l'etat complet, donc **les ventes
take-profit en attente sont detruites et les BTC deja achetes deviennent
orphelins** — le bot ne les revendra jamais. C'est un bug de production, pas
une approximation de simulation ; l'option `abandon_au_rebuild=False` permet
de mesurer ce que vaudrait la strategie une fois ce bug corrige.
"""

import itertools
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


_compteur_uid = itertools.count()


@dataclass
class Niveau:
    prix: float
    side: str                       # "Buy" | "Sell"
    qty: float
    entry_price: Optional[float] = None
    actif_des: int = 0              # index de bougie a partir duquel l'ordre repose
    # Identifiant explicite : `id()` serait reutilise apres liberation d'un
    # niveau supprime, ce qui ferait ignorer a tort un ordre nouvellement cree.
    uid: int = field(default_factory=lambda: next(_compteur_uid))


@dataclass
class Resultat:
    capital_initial: float
    capital_final: float
    profit: float
    rendement_pct: float
    buy_hold_pct: float
    cycles: int                     # allers-retours complets
    achats: int
    ventes: int
    frais: float
    recentrages: int
    qty_orpheline: float            # BTC abandonnes par les recentrages
    valeur_orpheline: float         # ... valorises au dernier prix
    cash_final: float
    max_drawdown_pct: float
    equity: List[float] = field(default_factory=list)


def simuler(
    df: pd.DataFrame,
    capital: float = 20.0,
    niveaux: int = 2,
    espacement_pct: float = 0.5,
    frais: float = 0.0025,
    rebuild_pct: float = 1.5,
    tp_meme_bougie: bool = False,
    abandon_au_rebuild: bool = True,
    autorisation_achat=None,
) -> Resultat:
    """
    tp_meme_bougie     : la vente TP peut-elle etre remplie dans la bougie ou
                         son achat vient d'etre execute ? False = hypothese
                         conservatrice (le bot doit d'abord constater le fill).
                         True = borne optimiste (le bot boucle a la minute).
    abandon_au_rebuild : True reproduit le code actuel (positions orphelines).
                         False simule le correctif.
    autorisation_achat : sequence de bool alignee sur df (ou None = toujours).
                         False a l'index i = les ACHATS ne se remplissent pas a
                         cette bougie (filtre de regime : la grille est en
                         pause). Les ventes TP restent actives : on ne bloque
                         que l'ouverture de nouvelles positions, jamais la
                         fermeture de positions existantes.
    """
    esp = espacement_pct / 100
    capital_par_niveau = capital / niveaux          # comme strategy.py (pas /half)
    demi = max(1, niveaux // 2)

    cash = capital
    btc = 0.0
    btc_orphelin = 0.0
    frais_total = 0.0
    profit_realise = 0.0
    cycles = achats = ventes = recentrages = 0

    ouverts: List[Niveau] = []
    centre = float(df["close"].iloc[0])

    def construire(prix_centre: float, index: int) -> List[Niveau]:
        lots = []
        for i in range(1, demi + 1):
            p = round(prix_centre * (1 - i * esp), 2)
            lots.append(Niveau(prix=p, side="Buy",
                               qty=round(capital_par_niveau / p, 6),
                               actif_des=index))
        return lots

    ouverts = construire(centre, 0)

    equity = []
    pic = capital
    max_dd = 0.0

    for idx, (_, bougie) in enumerate(df.iterrows()):
        bas = float(bougie["low"])
        haut = float(bougie["high"])
        cloture = float(bougie["close"])

        # ── Remplissages, sur les ordres deja en place au debut de la bougie ──
        # `a_traiter` est reconstitue tant que de nouveaux ordres deviennent
        # actifs dans cette bougie : sans cela, une vente TP creee pendant la
        # boucle ne serait jamais testee et `tp_meme_bougie` resterait sans effet.
        deja_vus = set()
        while True:
            a_traiter = [n for n in ouverts
                         if n.uid not in deja_vus and n.actif_des <= idx]
            if not a_traiter:
                break

            for niveau in a_traiter:
                deja_vus.add(niveau.uid)
                if niveau not in ouverts:
                    continue

                if niveau.side == "Buy":
                    if autorisation_achat is not None and not autorisation_achat[idx]:
                        continue
                    if bas > niveau.prix:
                        continue
                    cout = niveau.qty * niveau.prix
                    f = cout * frais
                    if cash < cout + f:        # fonds insuffisants : ordre rejete
                        continue
                    cash -= cout + f
                    btc += niveau.qty
                    frais_total += f
                    achats += 1
                    ouverts.remove(niveau)
                    # La vente take-profit part a UN espacement du prix d'achat.
                    ouverts.append(Niveau(
                        prix=round(niveau.prix * (1 + esp), 2),
                        side="Sell",
                        qty=niveau.qty,
                        entry_price=niveau.prix,
                        actif_des=idx if tp_meme_bougie else idx + 1,
                    ))

                else:  # Sell
                    if haut < niveau.prix:
                        continue
                    produit = niveau.qty * niveau.prix
                    f = produit * frais
                    cash += produit - f
                    btc -= niveau.qty
                    frais_total += f
                    ventes += 1
                    cycles += 1
                    entree = niveau.entry_price or niveau.prix
                    profit_realise += niveau.qty * (niveau.prix - entree) - f - (
                        niveau.qty * entree * frais)
                    ouverts.remove(niveau)
                    # Rearmement de l'achat au prix d'entree (strategy.py:136)
                    ouverts.append(Niveau(prix=entree, side="Buy",
                                          qty=round(capital_par_niveau / entree, 6),
                                          actif_des=idx + 1))

        # ── Recentrage, APRES les fills, sur le close de cette bougie ─────────
        if abs(cloture - centre) / centre > rebuild_pct / 100:
            if abandon_au_rebuild:
                # build_grid() remplace l'etat : les ventes TP en attente sont
                # perdues et les BTC correspondants ne seront jamais revendus.
                for niveau in ouverts:
                    if niveau.side == "Sell":
                        btc_orphelin += niveau.qty
                ouverts = construire(cloture, idx + 1)
            else:
                # Correctif : on garde les ventes TP, on ne refait que les achats.
                ventes_en_cours = [n for n in ouverts if n.side == "Sell"]
                ouverts = ventes_en_cours + construire(cloture, idx + 1)
            centre = cloture
            recentrages += 1

        valeur = cash + btc * cloture
        equity.append(valeur)
        pic = max(pic, valeur)
        if pic > 0:
            max_dd = max(max_dd, (pic - valeur) / pic * 100)

    prix_final = float(df["close"].iloc[-1])
    valeur_finale = cash + btc * prix_final
    prix_initial = float(df["close"].iloc[0])

    return Resultat(
        capital_initial=capital,
        capital_final=round(valeur_finale, 4),
        profit=round(valeur_finale - capital, 4),
        rendement_pct=round((valeur_finale - capital) / capital * 100, 2),
        buy_hold_pct=round((prix_final - prix_initial) / prix_initial * 100, 2),
        cycles=cycles,
        achats=achats,
        ventes=ventes,
        frais=round(frais_total, 4),
        recentrages=recentrages,
        qty_orpheline=round(btc_orphelin, 8),
        valeur_orpheline=round(btc_orphelin * prix_final, 4),
        cash_final=round(cash, 4),
        max_drawdown_pct=round(max_dd, 2),
        equity=equity,
    )
