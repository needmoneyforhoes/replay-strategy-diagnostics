#!/usr/bin/env python3
"""
test_refire_dedup.py — Test if clearing dedup for blocked fires improves PnL.
Uses tick-level data for accurate re-fire prices.

For each blocked fire: find the NEXT time that strategy's conditions
would be met (from later fires in recap), check if it would pass gates
at that later time, and compute PnL at the later entry price.

Usage:
    cd .
    python3 test_refire_dedup.py
"""

import json, math, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
RECAP = os.path.join(BASE, "market_recap_history.jsonl")
MKT_HIST = os.path.join(BASE, "market_history.jsonl")

STRATEGY_SIDE_MAP = {
    "depth_collapse_mid": "DN", "depth_surge": "DN", "fake_train_detector": "DN",
    "up_deep_spread_collapse": "UP", "up_depth_collapse_mid_high": "UP",
    "cl_gated_cheap": "UP", "cl_tight": "UP", "t4_late": "UP",
}


def load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except:
                    pass
    return out


def main():
    print("Loading market_recap_history.jsonl ...")
    recaps = load_jsonl(RECAP)
    print(f"  {len(recaps)} markets")

    print("Loading market_history.jsonl (tick data) ...")
    tick_by_slug = {}
    count = 0
    with open(MKT_HIST) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except:
                continue
            s = m.get("slug", "")
            if "ticks" in m and m["ticks"]:
                tick_by_slug[s] = m["ticks"]
            count += 1
            if count % 50 == 0:
                print(f"  ... {count} records", end="\r")
    print(f"  {count} records, {len(tick_by_slug)} with ticks")

    # CD, UP_BID, UP_ASK, DN_BID, DN_ASK = 0, 1, 2, 3, 4
    CD, UP_BID, UP_ASK, DN_BID, DN_ASK = 0, 1, 2, 3, 4

    def get_price_at(ticks, cd, side):
        """Get ask price for side at given cd."""
        best, best_d = None, 999
        for t in ticks:
            d = abs(t[CD] - cd)
            if d < best_d:
                best_d = d
                best = t
        if best is None:
            return None
        return best[UP_ASK] if side == "UP" else best[DN_ASK]

    # ═══════════════════════════════════════════════════════════════
    # SIMULATION: For each blocked fire, simulate re-fire at cd<210
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'='*110}")
    print("SIMULATION: What if blocked strategies could re-fire after gate release?")
    print(f"{'='*110}")

    # Current system: fire at cd=X, blocked, deduped, never fires again
    # New system: fire at cd=X, blocked, dedup cleared at cd=210,
    #             strategy re-checks at cd=200,190,180,...
    #             IF conditions still met AND passes gates → fire at later price

    # We approximate: blocked fire would re-fire at cd=200 (gate release)
    # using the tick price at cd=200

    refire_cds = [200, 180, 150, 120, 100, 80, 60]

    for mode_label, mode_filter in [
        ("ALL fires", lambda s, si: True),
        ("LIVE-eligible", lambda s, si: s in STRATEGY_SIDE_MAP and 
         STRATEGY_SIDE_MAP[s] in ("BOTH", si)),
    ]:
        print(f"\n{'─'*100}")
        print(f"  {mode_label}")
        print(f"{'─'*100}")

        # For each re-fire cd, compute total PnL difference
        print(f"\n  {'Re-fire CD':>10} | {'Blocked':>7} {'Re-fired':>8} | "
              f"{'Won':>4} {'Lost':>5} {'Win PnL':>9} {'Loss PnL':>10} {'NET':>9} | {'$/mkt':>7}")
        print(f"  {'-'*85}")

        for refire_cd in refire_cds:
            n_blocked = 0
            n_refired = 0
            n_won = 0
            n_lost = 0
            win_pnl = 0.0
            loss_pnl = 0.0

            for r in recaps:
                w = r.get("winner")
                if not w or w not in ("UP", "DN"):
                    continue
                slug = r["slug"]
                ticks = tick_by_slug.get(slug)
                fires = r.get("fires", [])

                # Find blocked fires (in map, correct side)
                blocked_strats = set()
                for f in fires:
                    s, si = f["strategy"], f["side"]
                    if not mode_filter(s, si):
                        continue
                    is_blocked = (f.get("pre_gate_held") or f.get("opp_gate_held")
                                  or f.get("cl_pass") == "FAIL"
                                  or f.get("opp_gate_blocked"))
                    if is_blocked:
                        blocked_strats.add((s, si))
                        n_blocked += 1

                # Check if blocked strategy also fired unheld
                for f in fires:
                    s, si = f["strategy"], f["side"]
                    is_blocked = (f.get("pre_gate_held") or f.get("opp_gate_held")
                                  or f.get("cl_pass") == "FAIL"
                                  or f.get("opp_gate_blocked"))
                    if not is_blocked and (s, si) in blocked_strats:
                        blocked_strats.discard((s, si))  # already fired, no dedup issue

                # For remaining blocked-only strategies, simulate re-fire
                for s, si in blocked_strats:
                    if not ticks:
                        continue
                    # Get price at re-fire cd
                    ask = get_price_at(ticks, refire_cd, si)
                    if ask is None or ask <= 0.01 or ask >= 0.99:
                        continue

                    n_refired += 1
                    # PnL: if winner matches side, win. Else lose.
                    if si == w:
                        pnl = (1.0 - ask) * 5 - 0.10  # 5 shares, $0.10 fee
                        win_pnl += pnl
                        n_won += 1
                    else:
                        pnl = -ask * 5 - 0.10
                        loss_pnl += pnl
                        n_lost += 1

            net = win_pnl + loss_pnl
            per_mkt = net / len(recaps) if recaps else 0
            mark = "✅" if net > 10 else "⚠️" if net > 0 else "❌"
            print(f"  cd={refire_cd:>3}      | {n_blocked:>7} {n_refired:>8} | "
                  f"{n_won:>4} {n_lost:>5} ${win_pnl:>+8.2f} ${loss_pnl:>+9.2f} ${net:>+8.2f} | "
                  f"${per_mkt:>+6.3f} {mark}")

    # ═══════════════════════════════════════════════════════════════
    # PER-STRATEGY: which strategies benefit from re-fire?
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'='*110}")
    print("PER-STRATEGY IMPACT @ re-fire cd=150 (LIVE-eligible only)")
    print(f"{'='*110}")

    refire_cd = 150
    strat_impact = defaultdict(lambda: {"n": 0, "won": 0, "lost": 0, "win_pnl": 0.0, "loss_pnl": 0.0})

    for r in recaps:
        w = r.get("winner")
        if not w or w not in ("UP", "DN"):
            continue
        slug = r["slug"]
        ticks = tick_by_slug.get(slug)
        fires = r.get("fires", [])

        blocked_strats = set()
        for f in fires:
            s, si = f["strategy"], f["side"]
            if s not in STRATEGY_SIDE_MAP:
                continue
            if STRATEGY_SIDE_MAP[s] not in ("BOTH", si):
                continue
            is_blocked = (f.get("pre_gate_held") or f.get("opp_gate_held")
                          or f.get("cl_pass") == "FAIL"
                          or f.get("opp_gate_blocked"))
            if is_blocked:
                blocked_strats.add((s, si))

        for f in fires:
            s, si = f["strategy"], f["side"]
            is_blocked = (f.get("pre_gate_held") or f.get("opp_gate_held")
                          or f.get("cl_pass") == "FAIL"
                          or f.get("opp_gate_blocked"))
            if not is_blocked and (s, si) in blocked_strats:
                blocked_strats.discard((s, si))

        for s, si in blocked_strats:
            if not ticks:
                continue
            ask = get_price_at(ticks, refire_cd, si)
            if ask is None or ask <= 0.01 or ask >= 0.99:
                continue

            key = f"{s}|{si}"
            strat_impact[key]["n"] += 1
            if si == w:
                pnl = (1.0 - ask) * 5 - 0.10
                strat_impact[key]["won"] += 1
                strat_impact[key]["win_pnl"] += pnl
            else:
                pnl = -ask * 5 - 0.10
                strat_impact[key]["lost"] += 1
                strat_impact[key]["loss_pnl"] += pnl

    print(f"\n  {'Strategy':<35} {'n':>4} {'W':>3} {'L':>3} {'WinPnL':>9} {'LossPnL':>10} {'NET':>9} | {'Verdict'}")
    print(f"  {'-'*90}")
    for key in sorted(strat_impact, key=lambda k: strat_impact[k]["win_pnl"] + strat_impact[k]["loss_pnl"], reverse=True):
        d = strat_impact[key]
        net = d["win_pnl"] + d["loss_pnl"]
        mark = "✅ helps" if net > 2 else "❌ hurts" if net < -2 else "≈"
        print(f"  {key:<35} {d['n']:>4} {d['won']:>3} {d['lost']:>3} ${d['win_pnl']:>+8.2f} ${d['loss_pnl']:>+9.2f} ${net:>+8.2f} | {mark}")

    # ═══════════════════════════════════════════════════════════════
    # COMPARE: current vs re-fire at best cd
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'='*110}")
    print("FINAL COMPARISON")
    print(f"{'='*110}")

    # Current LIVE hypo
    current = 0.0
    for r in recaps:
        for f in r.get("fires", []):
            s, si = f["strategy"], f["side"]
            if s not in STRATEGY_SIDE_MAP:
                continue
            if STRATEGY_SIDE_MAP[s] not in ("BOTH", si):
                continue
            if f.get("pre_gate_held") or f.get("opp_gate_held"):
                continue
            if f.get("cl_pass") == "FAIL":
                continue
            if f.get("opp_gate_blocked"):
                continue
            current += f.get("hypo_pnl", 0)

    print(f"\n  Current LIVE hypo: ${current:+.2f} (${current/len(recaps):+.3f}/mkt)")
    print(f"  Re-fire would ADD the NET from above")
    print(f"  Decision: implement ONLY if NET > 0 with tick-level verification")

    print(f"\n{'='*110}")
    print("DONE")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
