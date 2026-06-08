#!/usr/bin/env python3
"""strategy_perm_test.py — proper quantitative analysis of strategies.

For each strategy:
  1. Compute observed total PnL across all fires
  2. Permutation test: shuffle the market WINNERS (UP/DN), recompute PnL N times
  3. p_perm = fraction of permutations where permuted_PnL >= observed_PnL
  4. Only strategies with p_perm < 0.05 are statistically real edges
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = './data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
N_PERMUTATIONS = 5000


def load_all_fires():
    pattern = re.compile(
        r'(\d+)\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    winner_pattern = re.compile(r'MARKET RECAP.*\(winner=(\w+)\)')

    paths = sorted(set(glob.glob(PATH_PATTERN)))
    random.seed(42)
    if len(paths) > 500:
        paths = random.sample(paths, 500)

    all_fires = []
    mkt_winners = {}

    for p in paths:
        try:
            text = open(p).read()
        except Exception:
            continue
        m = winner_pattern.search(text)
        if not m:
            continue
        winner = m.group(1)
        if winner not in ('UP', 'DN'):
            continue
        slug = p.split('-')[-1].replace('.log', '')
        mkt_winners[slug] = winner

        for fm in pattern.finditer(text):
            try:
                strat = fm.group(2)
                side = fm.group(3)
                price = float(fm.group(4))
                cd = int(fm.group(5))
            except Exception:
                continue
            if price <= 0 or price >= 1:
                continue
            if cd <= MIN_CD:
                continue
            all_fires.append((slug, strat, side, price, cd, winner))

    return all_fires, mkt_winners


def fire_pnl(side, price, winner, size=1.0):
    if side == winner:
        return size * (1.0 / price - 1)
    return -size


def perm_test_strategy(fires, mkt_winners, n_perms=N_PERMUTATIONS):
    observed = sum(fire_pnl(side, price, winner)
                   for _, _, side, price, _, winner in fires)
    n = len(fires)
    if n < 20:
        return observed, None

    slugs = list(mkt_winners.keys())
    winners_list = list(mkt_winners.values())
    extreme_count = 0
    for _ in range(n_perms):
        random.shuffle(winners_list)
        perm_winner = dict(zip(slugs, winners_list))
        perm_pnl = sum(fire_pnl(side, price, perm_winner.get(slug, winner))
                       for slug, _, side, price, _, winner in fires)
        if perm_pnl >= observed:
            extreme_count += 1
    return observed, extreme_count / n_perms


def main():
    print("Loading fires...")
    all_fires, mkt_winners = load_all_fires()
    print(f"  {len(all_fires)} fires (cd>{MIN_CD}) across {len(mkt_winners)} markets\n")

    by_strat = defaultdict(list)
    for f in all_fires:
        by_strat[f[1]].append(f)

    print(f"Running permutation tests on {len(by_strat)} strategies ({N_PERMUTATIONS} perms)...\n")
    print(f"{'':2s}{'strategy':<38} {'n':>4} {'WR':>5} {'EV/fire':>9} {'total':>9} {'p_perm':>7}")
    print('-' * 80)

    results = []
    for strat, fires in by_strat.items():
        if len(fires) < 20:
            continue
        wins = sum(1 for _, _, side, _, _, winner in fires if side == winner)
        wr = wins / len(fires)
        ev_per_fire = sum(fire_pnl(side, price, winner)
                          for _, _, side, price, _, winner in fires) / len(fires)
        observed_pnl, p_perm = perm_test_strategy(fires, mkt_winners)
        results.append((strat, len(fires), wr, ev_per_fire, observed_pnl, p_perm))

    results.sort(key=lambda x: -x[3])

    significant = []
    for strat, n, wr, ev, total, p in results:
        marker = '⭐' if p is not None and p < 0.05 else '  '
        p_str = f"{p:.4f}" if p is not None else "—"
        print(f"{marker}{strat:<38} {n:>4} {wr:>5.1%} {ev:>+9.3f} {total:>+9.1f} {p_str:>7}")
        if p is not None and p < 0.05 and ev > 0:
            significant.append((strat, n, wr, ev, total, p))

    print(f"\n{'='*80}")
    print(f"STATISTICALLY SIGNIFICANT POSITIVE-EV (p_perm < 0.05):")
    print(f"{'='*80}")
    if not significant:
        print("  NONE — no strategy beats permuted-winners baseline at α=0.05")
        print("\n  THIS MEANS: even our 'top EV' strategies are no better than")
        print("  randomly firing on cheap-side prices. Cheap-side bias alone gives")
        print("  positive EV (asymmetric payoff), so positive EV != real edge.")
    else:
        for s, n, wr, ev, total, p in significant:
            print(f"  {s:<40} n={n:4d}  EV=${ev:+.3f}/fire  total=${total:+.1f}  p={p:.4f}")
        print(f"\n  Total: {len(significant)} strategies with REAL edge")


if __name__ == "__main__":
    random.seed(42)
    main()
