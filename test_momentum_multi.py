"""
test_momentum_multi.py — Le momentum tient-il sur PLUSIEURS actifs ?

Etend `test_momentum.py` a un panier crypto, en bougies JOURNALIERES (l'unite
naturelle d'un EMA 10/30 "jours" — l'approximation horaire 240/720 introduisait
du bruit inutile).

PIEGE CENTRAL, et c'est la raison d'etre de ce script :

    Tester 10 cryptos n'est PAS 10 tests independants.

Elles montent et descendent ensemble. Une regle du type "credible si 4 actifs
sur 6 battent le B&H" parait rigoureuse mais ne l'est pas : si les actifs sont
correles a 0,8, on n'a pas 6 observations, on en a environ 1,5. Le script
mesure donc la correlation reelle et en deduit le **nombre effectif de tests
independants**, avant de conclure quoi que ce soit.

    python test_momentum_multi.py
"""

from datetime import datetime, timedelta, timezone

import ccxt
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

# Momentum a signal quotidien : le croisement est constate a la cloture et
# l'ordre part au marche -> taker, pas maker. Plus une marge de slippage.
FRAIS = 0.0026          # Kraken taker, palier de base
SLIPPAGE = 0.0010
COUT = FRAIS + SLIPPAGE

RAPIDE, LENT = 10, 30   # en JOURS, fixes a priori
CAPITAL = 20.0

PAIRES = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOT/USDT", "ADA/USDT",
          "XRP/USDT", "LTC/USDT", "LINK/USDT", "AVAX/USDT", "ATOM/USDT"]


def charger_journalier(ex, paire: str) -> pd.Series:
    depuis = ex.parse8601((datetime.now(timezone.utc) - timedelta(days=2200))
                          .strftime("%Y-%m-%dT00:00:00Z"))
    tout = []
    maintenant = ex.milliseconds()
    while depuis < maintenant:
        lot = ex.fetch_ohlcv(paire, "1d", since=depuis, limit=1000)
        if not lot:
            break
        tout.extend(lot)
        suivant = lot[-1][0] + 1
        if suivant <= depuis:
            break
        depuis = suivant
    df = pd.DataFrame(tout, columns=["ts", "o", "h", "l", "c", "v"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms")
    return df.set_index("time")["c"]


def momentum(prix: pd.Series, rapide=RAPIDE, lent=LENT, cout=COUT) -> dict:
    """Long si EMA rapide > EMA lente, cash sinon. Signal decale d'une barre :
    la decision prise a la cloture du jour J ne s'applique qu'a partir de J+1."""
    er = prix.ewm(span=rapide, adjust=False).mean()
    el = prix.ewm(span=lent, adjust=False).mean()
    pos = (er > el).shift(1).fillna(False).astype(float)

    rdt = prix.pct_change().fillna(0.0)
    net = pos * rdt - pos.diff().abs().fillna(0.0) * cout

    eq = (1 + net).cumprod()
    bh = (1 + rdt).cumprod()

    def _dd(serie):
        return float(((serie.cummax() - serie) / serie.cummax()).max() * 100)

    ecart = net.std()
    ecart_bh = rdt.std()
    return {
        "rdt_pct": float((eq.iloc[-1] - 1) * 100),
        "bh_pct": float((bh.iloc[-1] - 1) * 100),
        "sharpe": float(net.mean() / ecart * np.sqrt(365)) if ecart > 0 else 0.0,
        "sharpe_bh": float(rdt.mean() / ecart_bh * np.sqrt(365)) if ecart_bh > 0 else 0.0,
        "dd": _dd(eq),
        "dd_bh": _dd(bh),
        "trades": int(pos.diff().abs().sum()),
        "jours": len(prix),
        "net": net,
    }


def main():
    ex = ccxt.bybit({"enableRateLimit": True})
    ex.load_markets()
    console.print(f"[cyan]Chargement journalier de {len(PAIRES)} actifs...[/cyan]")

    series, resultats = {}, {}
    for p in PAIRES:
        try:
            prix = charger_journalier(ex, p)
        except Exception as e:
            console.print(f"  [red]{p} : {e}[/red]")
            continue
        if len(prix) < 400:
            console.print(f"  [yellow]{p} ignore ({len(prix)} jours)[/yellow]")
            continue
        series[p] = prix
        resultats[p] = momentum(prix)

    console.print(f"[green]{len(resultats)} actifs retenus[/green]\n")

    # ── Resultats par actif, avec les 3 criteres du plan ─────────────────────
    t = Table(title=f"EMA {RAPIDE}/{LENT} jours — cout {COUT*100:.2f} %/trade",
              style="cyan")
    for c in ("Actif", "Jours", "Strategie", "Buy & Hold", "Sharpe", "S. B&H",
              "DD", "DD B&H", "Trades", "3 criteres"):
        t.add_column(c, justify="right")

    valides = 0
    for p, r in resultats.items():
        c1 = r["rdt_pct"] > r["bh_pct"]
        c2 = r["sharpe"] > 1.0
        c3 = r["dd"] < r["dd_bh"]
        ok = c1 and c2 and c3
        valides += ok
        marques = ("V" if c1 else "x") + ("V" if c2 else "x") + ("V" if c3 else "x")
        couleur = "green" if ok else "red"
        t.add_row(p.replace("/USDT", ""), str(r["jours"]),
                  f"{r['rdt_pct']:+.0f}%", f"{r['bh_pct']:+.0f}%",
                  f"{r['sharpe']:.2f}", f"{r['sharpe_bh']:.2f}",
                  f"{r['dd']:.0f}%", f"{r['dd_bh']:.0f}%", str(r["trades"]),
                  f"[{couleur}]{marques}[/{couleur}]")
    console.print(t)
    console.print("[dim]criteres : rendement > B&H | Sharpe > 1,0 | drawdown < B&H[/dim]")
    console.print(f"\n  [bold]{valides}/{len(resultats)} actifs passent les 3 criteres"
                  f"[/bold]  (regle du plan : >= 4/6)\n")

    # ── Le point que le plan ignore : les actifs ne sont pas independants ────
    rendements = pd.DataFrame({p: s.pct_change() for p, s in series.items()}).dropna()
    corr = rendements.corr()
    hors_diag = corr.to_numpy()[np.triu_indices(len(corr), k=1)]
    corr_moy = float(hors_diag.mean())

    # Nombre effectif de tests independants (approximation classique) :
    # n_eff = n / (1 + (n-1) * correlation moyenne)
    n = len(resultats)
    n_eff = n / (1 + (n - 1) * corr_moy)

    console.print("[bold]Independance des tests[/bold]")
    console.print(f"  correlation moyenne entre actifs : [bold]{corr_moy:.2f}[/bold]")
    console.print(f"  correlation min / max            : {hors_diag.min():.2f} / "
                  f"{hors_diag.max():.2f}")
    console.print(f"  -> {n} actifs testes, mais seulement "
                  f"[bold red]{n_eff:.1f} test(s) reellement independant(s)[/bold red]")
    console.print("[dim]  Une regle « 4 actifs sur 6 » suppose 6 observations "
                  "independantes. Avec cette correlation, elles n'en valent qu'une "
                  "poignee : le critere est bien plus faible qu'il n'en a l'air.[/dim]")

    # ── Portefeuille equipondere : la seule agregation honnete ───────────────
    net_moyen = pd.DataFrame({p: r["net"] for p, r in resultats.items()}).mean(axis=1)
    bh_moyen = rendements.mean(axis=1)
    eq = (1 + net_moyen).cumprod()
    bh = (1 + bh_moyen).cumprod()
    sh = net_moyen.mean() / net_moyen.std() * np.sqrt(365)
    sh_bh = bh_moyen.mean() / bh_moyen.std() * np.sqrt(365)
    dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
    dd_bh = float(((bh.cummax() - bh) / bh.cummax()).max() * 100)

    console.print("\n[bold]Portefeuille equipondere sur les actifs communs[/bold]")
    console.print(f"  momentum   : {(eq.iloc[-1]-1)*100:+.0f} %  "
                  f"Sharpe {sh:.2f}  DD {dd:.0f} %")
    console.print(f"  buy & hold : {(bh.iloc[-1]-1)*100:+.0f} %  "
                  f"Sharpe {sh_bh:.2f}  DD {dd_bh:.0f} %")
    ecart = (eq.iloc[-1] - bh.iloc[-1]) * 100
    couleur = "green" if ecart > 0 else "red"
    console.print(f"  [{couleur}]ecart : {ecart:+.0f} pt[/{couleur}]")


if __name__ == "__main__":
    main()
