# Un backtest honnête — et un résultat négatif

*(English version: [README.md](README.md) — c'est celle à lire si vous voulez
comprendre la démarche, elle est plus complète et destinée à la relecture
internationale. Le post-mortem détaillé est dans
[POSTMORTEM.fr.md](POSTMORTEM.fr.md).)*

---

J'ai fait tourner un bot de grille pendant des mois, validé par un backtest qui
le disait rentable. Il ne l'était pas : le backtest contenait un biais de
lookahead.

Ce dépôt contient les outils que j'ai construits pour m'en rendre compte, et les
résultats négatifs qu'ils ont produits. **Je le publie pour qu'on me dise ce que
j'ai raté.**

## L'affirmation, énoncée pour être réfutée

> En données journalières, sur 13 actifs et jusqu'à 33 ans d'historique, **il
> n'existe pas de structure exploitable suffisante pour couvrir les coûts de
> transaction d'un particulier.**
>
> Concrètement sur BTC : exploiter l'autocorrélation mesurée **avec une
> prévision parfaite** rapporte théoriquement **0,126 % par transaction**,
> contre **0,720 %** de coûts aller-retour. Il manque un facteur 5.

Tous les chiffres sont reproductibles avec les scripts du dépôt.

## Démarrage

```bash
pip install -r requirements.txt
python test_predictibilite.py
```

Aucune clé API nécessaire — tout passe par des endpoints publics.

## Le résultat le plus réutilisable

**Toute stratégie qui module son exposition améliore le Sharpe mécaniquement,
sans le moindre signal.** Planchers mesurés par permutation :

| Structure | Plancher sur données aléatoires |
|---|---|
| Long / cash | **+0,130** |
| Vol-scaling continu | **+0,463** |
| Long / short permanent | **−0,634** |

**Le seuil de comparaison n'est jamais 0. C'est ce plancher.**

Trois fois sur cinq, ce test — et lui seul — a évité une fausse validation.

## Cinq familles testées, zéro avantage

Grille (**réfutée**, perd même à 0 % de frais) · Momentum EMA long/cash (non
détecté) · Momentum MOP long/short (non détecté) · Carry sur funding (prime
réelle mais inexécutable) · Vol-managed (**faux positif** rattrapé par la
permutation).

Puis, au lieu d'une sixième stratégie, la question a été posée aux **données** :
la marche aléatoire est rejetée dans 19/52 cas, mais toujours en **retour à la
moyenne** — l'inverse de ce dont le momentum a besoin. Cela explique les cinq
échecs d'un seul coup.

## Où je peux me tromper

Le momentum **transversal** n'est pas testé. Mon test de permutation détruit
aussi le clustering de volatilité et peut être trop sévère. Rien en intraday.
Les contrats à terme enchaînés (`CL=F`) ont des artefacts de roulement. Et j'ai
trouvé **deux bugs dans mon propre code** en écrivant ces tests — il en reste
peut-être un troisième.

Le détail complet de ces réserves est dans le [README anglais](README.md),
section *Where I might be wrong*.

---

*Le dry-run disait la vérité depuis des mois — zéro cycle bouclé. C'est le
backtest qui mentait. Quand la simulation et la réalité divergent, c'est la
réalité qui a raison.*

## Licence

MIT.
