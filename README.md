# replay-strategy-diagnostics

Offline post-hoc diagnostics over Polymarket 5-minute crypto up/down logs and replays: permutation tests, single-strategy backtests, refire/dedup counterfactuals, and replay-quality audits. Read-only; no network, wallet, or live order flow.

## Scripts

- `strategy_perm_test.py`: Per-strategy permutation test. Shuffles market winners 5000x and reports `p_perm`. Counts a strategy as a real edge only when `p_perm < 0.05` and EV > 0. Parses fire lines from `race_test_*.log`.
- `test_strategy_recent.py`: Single-strategy backtest over the last N markets. Handles BASE, `_FLIP`, and `_Q_` variants (reads recap, flip, and parameter logs respectively). Prints a per-market table, WR, EV/fire, R:R, and a verdict.
- `test_refire_dedup.py`: Counterfactual for gate-blocked, deduped fires. Re-prices a hypothetical re-fire at later `cd` from tick data and reports per-strategy and aggregate NET impact.
- `diagnose.py`: Session verdict from `moves.log` and `mechanisms.log`. Classifies each losing market as MECHANISM_LOSS vs MARKET_LOSS, rolls up EV/market, and shows a 12-market scaling-target window.
- `diagnose_replay_quality.py`: Replay-data audit: tick density, schema evolution (first column appearance), first-tick `cd` coverage, price-extreme reach, and tick-interval gap outliers across time.

## Requirements

Python 3.8+, standard library only.

## Usage

```bash
# Strategies that beat the permuted-winner baseline
python3 strategy_perm_test.py

# Backtest one strategy over the last 20 markets (BASE / _FLIP / _Q_ variants)
python3 test_strategy_recent.py deep_dip_scout 20
python3 test_strategy_recent.py deep_dip_scout_FLIP 20

# Counterfactual: refiring blocked/deduped fires
python3 test_refire_dedup.py

# Per-session verdict
python3 diagnose.py --n 20

# Replay-data quality (defaults to ./replay_*.json)
python3 diagnose_replay_quality.py $DATA_DIR
```

## Data

Inputs are not committed (see `.gitignore`). Provide them from the private `polymarket-data` repo or the engine working dir.

- `strategy_perm_test.py`: `race_test_btc-updown-5m-*.log`. Path constant `PATH_PATTERN`; edit it to point at `$DATA_DIR`.
- `test_strategy_recent.py`, `test_refire_dedup.py`: `market_recap_history.jsonl`, `market_history.jsonl`, `flip_shadow_log.jsonl`, `parameter_history.jsonl`. Run from the directory holding them.
- `diagnose.py`: `moves.log`, `mechanisms.log` in the working dir.
- `diagnose_replay_quality.py`: `replay_*.json` files (directory is the first arg, default `.`).

## Feedback

Suggestions, improvements, or something not working? Please
[open an issue](https://github.com/needmoneyforhoes/replay-strategy-diagnostics/issues/new). Pull requests are welcome too.
