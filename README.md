# An honest backtest — and a negative result

I spent months running a grid trading bot that a backtest said was profitable.
It wasn't. The backtest had a look-ahead bug.

This repo contains the tooling I built to find that out, and the negative
results it produced. **I am publishing this to be told what I got wrong.**

*(Code comments are in French — I'm a francophone from Montréal. The README,
the claims and the methodology notes are in English. Version française :
[LISEZMOI.md](LISEZMOI.md).)*

---

## The claim, stated so it can be falsified

> On daily bars, across 13 assets and up to 33 years of history, **there is no
> exploitable structure large enough to cover retail transaction costs.**
>
> Concretely, on BTC: exploiting the measured autocorrelation **with perfect
> foresight** yields a theoretical gross **0.126 % per trade**, against
> **0.720 %** round-trip cost. It is short by a factor of 5.

Every number here is reproducible with the scripts in this repo.

If this claim is wrong, it should be possible to say precisely where — a bug,
a bad assumption, a missing test. That's what I'm asking for.

---

## Quick start

```bash
pip install -r requirements.txt
python test_predictibilite.py
```

Downloads data on first run (a few minutes), caches it, and prints the core
result. No API keys needed — everything uses public endpoints.

---

## What went wrong in the original backtest

Three bugs, **all** biased in the favourable direction — which is the classic
signature of a result that is too good.

| Bug | Effect |
|---|---|
| **Look-ahead** — the grid was re-centred on the candle's `close`, then filled against the `low`/`high` of *that same candle* | Orders were placed knowing the closing price. The tighter the re-centring threshold, the more the bias was exploited — an artefact masquerading as an optimal parameter. |
| **Gross double-counted** — buy at `centre×(1−s)`, sell at `centre×(1+s)` = 2 spacings | Production placed its take-profit at `entry×(1+s)` = **one** spacing. Per-cycle gross was overstated 2×. |
| **Truncated pagination** — loop stopped on `len(batch) < 1000`, but Bybit returns 999 from page 2 onwards | Any history request was silently cut to ~2000 candles. A 90-day request returned 83 days. |

Once fixed, the result **inverts**: the grid loses money even at **0 % fees**.

---

## The finding I think is most reusable

**Any strategy that modulates its exposure improves Sharpe mechanically, with
no signal whatsoever.** Floors measured by permutation (shuffled returns, same
distribution, time structure destroyed):

| Structure | Random-data floor | Mechanism |
|---|---|---|
| Long / cash | **+0.130** | invested ~50 % of the time → lower volatility |
| Continuous vol-scaling | **+0.463** | exposure falls when vol rises → variance drops faster than return |
| Permanent long / short | **−0.634** | constant exposure → the artefact disappears |

**The comparison baseline is never 0. It is this floor.**

Three times out of five, this test — and only this test — caught a false
positive. The volatility-managed strategy showed **4/4 asset classes beating
buy & hold** with drawdowns halved; the permutation floor was **+0.463**
against a real **+0.057**. It performed *worse than random*.

---

## Results summary

| Strategy family | Verdict |
|---|---|
| Grid trading | **Refuted** — loses at 0 % fees. 96 configurations, none beats buy & hold. Asymmetric payoff: gains capped at +1 spacing, losses unbounded. |
| Momentum, EMA crossover, long/cash | Not detected — p = 0.096; 3/6 sub-periods; noise 8.7× the signal |
| Momentum, Moskowitz-Ooi-Pedersen style, long/short + vol-scaling | Not detected — Sharpe 0.76 vs 0.85 buy & hold. Beats random, loses to holding. |
| Funding carry | **Real premium** (3.08 %/yr, positive 76 % of the time) but not executable: spot accounts have no perpetuals |
| Volatility-managed | **False positive**, caught by permutation |

Then, instead of testing a sixth strategy, I asked the **data** directly
(`test_predictibilite.py`, no tunable parameters, so no overfitting possible):

- Random walk rejected in **19/52** cases — but always with **VR < 1**, i.e.
  *mean reversion*, the opposite of what momentum needs. This explains all
  five failures at once.
- That mean reversion is driven by lag-1 negative autocorrelation (−0.08 to
  −0.18) — the signature of **bid-ask bounce**, not capturable without
  trading inside the spread.
- **11 of 13 assets** fall below their transaction costs even under perfect
  foresight.

---

## Where I might be wrong

This is the section I care most about.

1. **Cross-sectional momentum is untested.** I tested *time-series* momentum
   (each asset against its own past). Cross-sectional momentum (long the
   strongest, short the weakest at a point in time) is a distinct phenomenon
   with stronger academic support. I believe it hits the same cost wall, but
   I have not shown it.

2. **My permutation test may be too harsh.** Shuffling returns destroys
   volatility clustering as well as autocorrelation, and trend-following
   draws part of its real benefit from clustering.

3. **Daily frequency only.** Nothing intraday, where microstructure effects
   and costs behave differently.

4. **Futures continuation contracts.** `CL=F` shows a lag-1 autocorrelation
   of +0.234, implausible for a liquid market. Almost certainly a roll
   artefact rather than signal — but I have not proven that either.

5. **`grid_sim.py` reproduces the production state machine as I read it.**
   A divergence between my simulator and the real bot is possible.

6. **Fee assumptions.** ccxt reports two contradictory figures for Kraken's
   base tier (0.25 %/0.40 % via market metadata, 0.16 %/0.26 % via the tier
   table). I used both; results hold either way, but the discrepancy is
   unresolved.

7. **I found two bugs in my own code while writing these tests** — an extra
   `n` factor that flattened every variance-ratio z-statistic to zero, and a
   flag that silently had no effect. There may be a third I did not catch.

---

## Scripts

| File | What it does |
|---|---|
| `test_predictibilite.py` | Autocorrelation, Lo-MacKinlay variance ratio, **economic translation** to cost. Start here. |
| `mur_de_frais.py` | Screening tool: what edge must a strategy have to survive given fees. Run *before* coding anything. |
| `grid_sim.py` | Faithful grid state machine. **Validated on 4 synthetic markets** with known outcomes. |
| `audit_grille.py` | Parallel parameter sweep (1152 simulations). |
| `backtest_regimes.py` | Window splitting, regime classification, robustness. |
| `test_momentum.py` | Parameter surface + **permutation test**. Template for any new strategy. |
| `test_momentum_multi.py` | Multi-asset + **effective number of independent tests**. |
| `test_momentum_cross_asset.py` | Cross-asset via yfinance, decisions **by asset class**. |
| `test_momentum_mop.py` | Long/short + volatility scaling. |
| `test_vol_managed.py` | Volatility-managed portfolios + project-level significance correction. |

---

## Method rules I'd keep

- Never validate on "beats buy & hold on N periods" — that's a coin flip for a
  strategy with no edge.
- Never benchmark against **zero**. The benchmark is buy & hold.
- Never read an improved Sharpe without measuring the **mechanical floor** by
  permutation.
- Testing N strategies on the same data means dividing your threshold by N.
- Never assume the data exists where you think: Bybit only goes back to 2021,
  Kraken caps at 721 candles, MATIC was renamed POL.
- More assets ≠ more tests. Ten cryptos correlated at 0.70 are worth
  **1.4 independent tests**.

---

## Context

Retail scale, and a jurisdiction where crypto derivatives are largely closed
to retail investors. That constrains what is executable — it is part of why
several avenues die on arithmetic rather than on statistics. The funding-carry
premium, for instance, is real and measurable, but requires perpetuals a spot
account simply does not have.

Costs used throughout are retail exchange fees, stated per asset class in each
script. If you trade at institutional cost, several conclusions here weaken —
that is the point of publishing the numbers rather than the verdict.

The dry-run had been telling the truth for months — zero completed cycles. It
was the backtest that was lying. **When the simulation and reality disagree,
reality is right.**

---

## License

MIT. Use it, break it, tell me where it's wrong.
