# TradingBot — Post-mortem

**Date : 27 juillet 2026** · Projet arrêté après validation méthodique.
Capital engagé : **0 $**.

---

## Résumé en une ligne

Le bot de grille tournait depuis des mois sur une stratégie **structurellement
perdante**, validée à l'origine par un backtest **biaisé**. Cinq familles de
stratégies ont été testées avec un protocole rigoureux : aucune ne dégage
d'avantage exploitable. Aucun argent n'a été perdu.

---

## 1. Ce qui a été découvert

### Trois bugs dans le backtest d'origine
Ils allaient **tous** dans le sens favorable, ce qui est le motif classique
d'un résultat trop beau.

| Bug | Effet |
|---|---|
| **Lookahead** — grille recentrée sur le `close` de la bougie, puis remplie contre le `low`/`high` de **cette même** bougie | Les ordres étaient placés en connaissant le prix de fin. Plus le recentrage était serré, plus le biais était exploité — un artefact déguisé en réglage optimal. |
| **Brut compté en double** — achat à `centre×(1−esp)`, vente à `centre×(1+esp)` = 2 espacements | La production pose son TP à `prix_achat×(1+esp)` = **1** espacement (`strategy.py:115`). Gain par cycle surestimé ×2. |
| **Pagination tronquée** — arrêt sur `len(lot) < 1000` alors que Bybit renvoie 999 dès la 2ᵉ page | Toute demande d'historique était silencieusement coupée à ~2000 bougies. Une demande de 90 j n'en ramenait que 83. |

Corrigé, le résultat s'inverse : **la grille perd même à 0 % de frais.**

### Un bug de production, jamais détecté
`bot.py:141` — au recentrage, `build_grid()` **remplace l'état complet** de la
grille et détruit les ventes take-profit en attente. Les BTC achetés restent
sur le compte mais le bot **les oublie définitivement**.

Simulation sur 90 j avec la config réelle : **105 recentrages**, et **99 % du
capital immobilisé en BTC orphelins** — le cash tombe à presque zéro.

→ C'est l'explication du dry-run figé à 0 cycle depuis des mois. Le signal
était là ; il a été attribué au marché plat.

**Non corrigé volontairement** : réparer le moteur d'une stratégie abandonnée
n'a pas de sens, et la correction la rend mesurablement **plus** perdante
(le bug la transformait de facto en buy & hold).

---

## 2. Les cinq familles testées

| Famille | Verdict | Base |
|---|---|---|
| Grille | **Réfutée** | Perd même à 0 % de frais. 96 configurations, aucune ne bat le buy & hold. Cause : payoff asymétrique (gains plafonnés à +1 espacement, pertes non bornées). |
| Momentum EMA long/cash | Non détecté | +18,8 pt vs B&H mais p = 0,096 ; 3/6 sous-périodes ; bruit 8,7× le signal. |
| Momentum MOP long/short | Non détecté | Sharpe 0,76 contre 0,85 en B&H. Le signal bat le hasard mais pas l'achat-conservation. |
| Carry sur funding | **Prime réelle, inexécutable** | 3,08 %/an, positive 76 % du temps. Mais un compte spot n'a aucun perpétuel, les dérivés crypto sont largement fermés au particulier dans plusieurs juridictions, et la taille minimale d'un perpétuel BTC (0,001 BTC) impose un capital hors de portée à petite échelle. |
| Vol-managed (Moreira-Muir) | **Faux positif** | 4/4 classes validaient, drawdowns divisés par deux. Le test de permutation l'a tué : plancher du hasard **+0,463** contre réel **+0,057**. |

---

## 3. Le résultat le plus réutilisable

**Toute stratégie qui module son exposition améliore le Sharpe mécaniquement,
sans le moindre signal.** Planchers mesurés par permutation :

| Structure | Plancher | Mécanisme |
|---|---|---|
| Long / cash | **+0,130** | investi ~50 % du temps → volatilité réduite |
| Vol-scaling continu | **+0,463** | l'exposition baisse quand la vol monte → la variance chute plus vite que le rendement |
| Long / short permanent | **−0,634** | exposition constante → l'artefact disparaît |

→ **Le seuil de comparaison n'est jamais 0. C'est ce plancher.**
Trois fois sur cinq, c'est ce test — et lui seul — qui a évité une fausse
validation.

---

## 4. Pourquoi tout a échoué — la mesure directe

Plutôt que de tester une sixième stratégie, la question a été posée aux
**données** (`test_predictibilite.py`, aucun paramètre optimisable) :

- **Marche aléatoire rejetée dans 19/52 cas** — mais toujours avec **VR < 1**,
  c'est-à-dire du **retour à la moyenne**, l'inverse de ce dont le momentum a
  besoin. Cela explique les échecs d'un seul coup.
- Ce retour à la moyenne vient des autocorrélations négatives à retard 1
  (−0,08 à −0,18) : signature du **rebond bid-ask**, non capturable sans
  traiter à l'intérieur du spread.
- **Traduction économique, avec prévision parfaite** : sur BTC, gain maximal
  **0,126 %** contre **0,720 %** de coûts. Il manque un facteur **5**.
  11 actifs sur 13 sont sous leurs coûts.

**Conclusion : il n'existe pas, à fréquence journalière et avec des coûts de
particulier, de structure suffisante pour couvrir les frais.**

---

## 5. Outils laissés en place (réutilisables)

| Fichier | Rôle |
|---|---|
| `grid_sim.py` | Simulateur fidèle à `strategy.py`. **Validé sur 4 marchés synthétiques** à résultat connu (oscillation, baisse et hausse rectilignes). |
| `backtest_regimes.py` | Découpage en fenêtres, classement par régime, robustesse. |
| `audit_grille.py` | Balayage massif parallélisé (1152 simulations). |
| `test_momentum.py` | Surface de paramètres + **test de permutation**. Base pour toute stratégie future. |
| `test_momentum_multi.py` | Multi-actifs + **nombre effectif de tests indépendants**. |
| `test_momentum_cross_asset.py` | Cross-asset via yfinance, décision **par classe**. |
| `test_vol_managed.py` | Vol-managed + correction du seuil au niveau projet. |
| `test_predictibilite.py` | Autocorrélation, ratio de variance (Lo-MacKinlay), **traduction économique**. |
| `mur_de_frais.py` | Tri rapide : quel avantage une stratégie doit-elle avoir pour survivre aux frais. |
| `check_api_keys.py` | Validation lecture seule des clés d'exchange. |

**Infrastructure conservée** : compte Kraken vérifié, clés API cloisonnées
(4 permissions, aucun retrait), couche `ccxt` portable (`EXCHANGE_ID` dans
`.env`), données de marché sur Bybit public.

---

## 6. Ce qui devrait changer pour rouvrir le dossier

Rouvrir **sans** qu'au moins un de ces points ait changé serait refaire le
même chemin :

1. **Coûts divisés par 5 au minimum** — il manque un facteur 5 sur BTC, et
   les paliers de volume Kraken exigent 50 000 $ de volume sur 30 jours.
2. **Accès à d'autres marchés** — perpétuels (carry), options (prime de
   variance), actions. Tous fermés ou douteux depuis le Québec.
3. **Position de teneur de marché** plutôt que preneur — encaisser le spread
   au lieu de le payer. C'est le seul côté du carnet qui gagne.
4. **Une fréquence plus basse** où les coûts pèsent moins.
5. **Une idée réellement nouvelle** — et non une variante de ce qui est
   au-dessus. À passer par `mur_de_frais.py` **avant** d'écrire une ligne.

Piste non testée, par honnêteté : le momentum **transversal** (acheter les
actifs les plus forts, vendre les plus faibles) est un phénomène distinct du
momentum de série temporelle testé ici, et mieux documenté. Il se heurterait
au même mur de coûts, mais ce n'est pas démontré.

---

## 7. Erreurs de méthode à ne pas refaire

- Ne jamais valider sur « bat le buy & hold sur N périodes » — un faux positif
  une fois sur deux.
- Ne jamais comparer une stratégie à **zéro** : le benchmark est le buy & hold.
- Ne jamais interpréter un Sharpe amélioré sans mesurer le **plancher
  mécanique** par permutation.
- Ne jamais tester N stratégies sur les mêmes données sans **diviser le seuil
  par N** (5 familles ici → seuil 0,01, pas 0,05).
- Ne jamais supposer que les données existent : Bybit ne remonte qu'à 2021,
  Kraken plafonne à 721 bougies, MATIC a été renommé POL.
- Plus d'actifs ≠ plus de tests : 10 cryptos corrélées à 0,70 valent
  **1,4 test indépendant**.

---

*Le dry-run a dit la vérité pendant des mois — 0 cycle bouclé. C'est le
backtest qui mentait. Quand la simulation et la réalité divergent, c'est la
réalité qui a raison.*
