# replay-strategy-diagnostics

Offline log/replay strategy diagnostics for Polymarket: permutation tests, single-strategy backtests, refire/dedup counterfactuals, and replay-quality audits.

## Why it exists

The live trading engine fires hundreds of named strategies against Polymarket 5-minute crypto up/down markets and writes verbose logs and per-market recaps. These standalone, read-only scripts answer the questions you ask *after* a session: which strategies have a statistically real edge (vs. cheap-side payoff luck), how a single strategy performed in the recent window, whether clearing dedup on blocked fires would have added PnL, and whether the replay data itself is clean enough to trust. Nothing here touches the network, a wallet, or live order flow — it is pure post-hoc analysis.

## What's inside

| Script | Purpose | Invocation |
| --- | --- | --- |
| `strategy_perm_test.py` | Per-strategy permutation test: shuffles market winners 5000× and reports `p_perm`, so only strategies that beat the permuted-winner baseline (p < 0.05, EV > 0) count as real edges. Parses `race_test_*.log` fire lines. | `python3 strategy_perm_test.py` |
| `test_strategy_recent.py` | Single-strategy backtest over the last N markets. Handles BASE, `_FLIP`, and `_Q_` variants (reads recap / flip / parameter logs respectively); prints per-market table, WR, EV/fire, R:R, and a verdict. | `python3 test_strategy_recent.py <strategy> [n]` |
| `test_refire_dedup.py` | Counterfactual: for fires that were gate-blocked and deduped, re-prices a hypothetical re-fire at later `cd` using tick-level data, and reports per-strategy and aggregate NET impact. | `python3 test_refire_dedup.py` |
| `diagnose.py` | Session verdict from `moves.log` + `mechanisms.log`: classifies each losing market as MECHANISM_LOSS vs. MARKET_LOSS, rolls up EV/market, and shows a 1-hour (12-market) scaling-target window. | `python3 diagnose.py [--n N] [--all]` |
| `diagnose_replay_quality.py` | Replay-data audit: tick density, schema evolution (when columns first appear), first-tick `cd` coverage, price-extreme reach, and tick-interval gap outliers across time. | `python3 diagnose_replay_quality.py [replay_dir]` |

## Requirements

- Python 3 (3.8+); standard library only — no third-party packages, no `pip install` step.
- No wallet, private key, or API credentials are used. These tools are strictly offline.

## Usage

```bash
# Find strategies with a statistically real edge
python3 strategy_perm_test.py

# Backtest one strategy over the last 20 markets (BASE / _FLIP / _Q_ variants)
python3 test_strategy_recent.py deep_dip_scout 20
python3 test_strategy_recent.py deep_dip_scout_FLIP 20

# Counterfactual: would re-firing blocked/deduped fires have helped?
python3 test_refire_dedup.py

# Per-session verdict from moves.log + mechanisms.log
python3 diagnose.py --n 20

# Audit replay-data quality (defaults to ./replay_*.json)
python3 diagnose_replay_quality.py /path/to/replays
```

## Data

These scripts read but never write trading data, and the inputs are **not** committed here (see `.gitignore`). Provide them from the private `polymarket-data` repo / your engine's working dir:

- `strategy_perm_test.py` — `race_test_btc-updown-5m-*.log` (path constant `PATH_PATTERN`; edit to point at your log dir).
- `test_strategy_recent.py` / `test_refire_dedup.py` — `market_recap_history.jsonl`, `market_history.jsonl`, `flip_shadow_log.jsonl`, `parameter_history.jsonl`; run from the directory containing them.
- `diagnose.py` — `moves.log`, `mechanisms.log` in the working directory.
- `diagnose_replay_quality.py` — `replay_*.json` files (directory passed as the first arg, default `.`).

> Private research software. No warranty; trades/handles real funds at your own risk.
