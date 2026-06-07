#!/usr/bin/env python3
"""
test_strategy_recent.py — test ANY strategy over last N markets.

Handles all three strategy types:
  - Base strategies (cl_age_surge): reads market_recap_history.jsonl
  - FLIP strategies (cl_age_surge_FLIP): reads flip_shadow_log.jsonl
  - _Q variants (cl_age_surge_Q_FOO): reads parameter_history.jsonl

Usage:
  python3 test_strategy_recent.py [strategy_name] [n_markets]
  python3 test_strategy_recent.py deep_dip_scout 20
  python3 test_strategy_recent.py deep_dip_scout_FLIP 20
  python3 test_strategy_recent.py late_dip_recovery_Q_V5_LDR_DEPTH_DROP 20
"""
import sys, json, os
from datetime import datetime
from collections import defaultdict

strategy_name = sys.argv[1] if len(sys.argv) > 1 else 'deep_dip_scout'
n_markets = int(sys.argv[2]) if len(sys.argv) > 2 else 20

is_flip = strategy_name.endswith('_FLIP')
is_q = '_Q_' in strategy_name
base_name = strategy_name[:-len('_FLIP')] if is_flip else strategy_name

print("\n" + "═"*88)
print(f"  STRATEGY BACKTEST — {strategy_name} over LAST {n_markets} MARKETS")
print("═"*88)

RECAP_PATH = 'market_recap_history.jsonl'
if not os.path.exists(RECAP_PATH):
    print(f"  ❌ {RECAP_PATH} not found — run from polymarket-bot directory")
    sys.exit(1)

markets = []
with open(RECAP_PATH) as f:
    for line in f:
        try: markets.append(json.loads(line))
        except: continue

if not markets:
    print("  ❌ No markets in recap history")
    sys.exit(1)

recent = markets[-n_markets:]
recent_ts_min = min((m.get('ts', 0) for m in recent if m.get('ts')), default=0)
recent_ts_max = max((m.get('ts', 0) for m in recent if m.get('ts')), default=0)

print(f"\n  Loaded {len(markets)} total markets, analyzing last {len(recent)}")
print(f"  Strategy type: {'FLIP' if is_flip else ('_Q variant' if is_q else 'BASE')}\n")

# Build per-market structure
per_market = {}
for m in recent:
    slug = m.get('slug', '')
    per_market[slug] = {'UP': [], 'DN': [], 'winner': m.get('winner', '?'),
                        'ts': m.get('ts', 0)}

agg = {
    'UP': {'n': 0, 'w': 0, 'pnl': 0.0, 'wins_pnl': [], 'loss_pnl': []},
    'DN': {'n': 0, 'w': 0, 'pnl': 0.0, 'wins_pnl': [], 'loss_pnl': []},
}

def find_market_slug(rts):
    """Find which recent market this fire belongs to (by timestamp)."""
    best_slug, best_dt = None, 999999
    for slug, mdata in per_market.items():
        mt = mdata['ts']
        if not mt: continue
        dt = abs(rts - mt)
        if dt < best_dt and dt < 600:  # within 10 min
            best_dt = dt
            best_slug = slug
    return best_slug


# ── Load strategy-specific data ──────────────────────────────────────────
if is_flip:
    flip_path = 'flip_shadow_log.jsonl'
    if not os.path.exists(flip_path):
        print(f"  ❌ {flip_path} not found — no FLIP data available")
        sys.exit(1)
    
    with open(flip_path) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get('strategy') != base_name: continue
                rts = r.get('ts', 0)
                if rts < recent_ts_min - 600 or rts > recent_ts_max + 600: continue
                slug = find_market_slug(rts)
                if not slug: continue
                
                # FLIP fires on OPPOSITE side. base side DN → FLIP fires UP.
                base_side = r.get('side', '?')
                flip_side = 'DN' if base_side == 'UP' else 'UP'
                flip_won = r.get('flip_won', False)
                opp_entry = r.get('opp_entry_estimated', 0.5) or 0.5
                shares = 5
                if flip_won:
                    flip_pnl = (1.0 - opp_entry) * shares
                else:
                    flip_pnl = -opp_entry * shares
                
                per_market[slug][flip_side].append(flip_pnl)
                agg[flip_side]['n'] += 1
                if flip_won: agg[flip_side]['w'] += 1
                agg[flip_side]['pnl'] += flip_pnl
                if flip_won: agg[flip_side]['wins_pnl'].append(flip_pnl)
                else: agg[flip_side]['loss_pnl'].append(flip_pnl)
            except: continue
elif is_q:
    print(f"  ⚠️  _Q variants don't store $ PnL — using approximate (+$2 win, -$1 loss)")
    ph_path = 'parameter_history.jsonl'
    if not os.path.exists(ph_path):
        print(f"  ❌ {ph_path} not found")
        sys.exit(1)
    
    with open(ph_path) as f:
        for line in f:
            try:
                r = json.loads(line)
                if r.get('strategy') != strategy_name: continue
                rts = r.get('ts', 0)
                slug = find_market_slug(rts)
                if not slug: continue
                side = r.get('side', '?')
                won = r.get('won', False)
                pnl = 2.0 if won else -1.0  # approximate
                per_market[slug][side].append(pnl)
                if side in agg:
                    agg[side]['n'] += 1
                    if won: agg[side]['w'] += 1
                    agg[side]['pnl'] += pnl
                    if won: agg[side]['wins_pnl'].append(pnl)
                    else: agg[side]['loss_pnl'].append(pnl)
            except: continue
else:
    # BASE strategy
    for m in recent:
        slug = m.get('slug', '')
        for fire in m.get('fires', []):
            if fire.get('strategy') != strategy_name: continue
            side = fire.get('side', '?')
            pnl = fire.get('hypo_pnl', 0) or 0
            won = pnl > 0
            per_market[slug][side].append(pnl)
            if side in agg:
                agg[side]['n'] += 1
                if won: agg[side]['w'] += 1
                agg[side]['pnl'] += pnl
                if won: agg[side]['wins_pnl'].append(pnl)
                else: agg[side]['loss_pnl'].append(pnl)


# ── Per-market table ─────────────────────────────────────────────────────
print(f"  {'MARKET':<35s} {'WIN':<5s} {'UP fires':<28s} {'DN fires':<28s} {'TOTAL'}")
print("  " + "─"*98)

shown = 0
for slug, mdata in per_market.items():
    up_fires = mdata['UP']
    dn_fires = mdata['DN']
    if not up_fires and not dn_fires: continue
    shown += 1
    
    winner = mdata['winner']
    up_n, up_pnl = len(up_fires), sum(up_fires)
    up_w = sum(1 for x in up_fires if x > 0)
    dn_n, dn_pnl = len(dn_fires), sum(dn_fires)
    dn_w = sum(1 for x in dn_fires if x > 0)
    total_pnl = up_pnl + dn_pnl
    
    up_str = f"{up_n}f {up_w}W ${up_pnl:>+6.2f}" if up_n else "—"
    dn_str = f"{dn_n}f {dn_w}W ${dn_pnl:>+6.2f}" if dn_n else "—"
    total_str = f"${total_pnl:>+7.2f}"
    if total_pnl > 0: total_str += " 📈"
    elif total_pnl < 0: total_str += " 📉"
    print(f"  {slug[:33]:<35s} {winner:<5s} {up_str:<28s} {dn_str:<28s} {total_str}")

if shown == 0:
    print("  (no fires in this window)")


# ── Aggregate ────────────────────────────────────────────────────────────
print("\n  " + "═"*86)
print(f"  AGGREGATE — {strategy_name} over last {len(recent)} markets")
print("  " + "═"*86)

for side in ['UP', 'DN']:
    a = agg[side]
    if a['n'] == 0:
        print(f"\n  {side}: no fires this window")
        continue
    wr = a['w'] / a['n']
    avg_pnl = a['pnl'] / a['n']
    avg_win = sum(a['wins_pnl']) / len(a['wins_pnl']) if a['wins_pnl'] else 0
    avg_loss = sum(a['loss_pnl']) / len(a['loss_pnl']) if a['loss_pnl'] else 0
    max_win = max(a['wins_pnl']) if a['wins_pnl'] else 0
    worst_loss = min(a['loss_pnl']) if a['loss_pnl'] else 0
    
    status = "✅ PROFITABLE" if a['pnl'] > 0 else ("⚠️ BREAKEVEN" if abs(a['pnl']) < 1 else "❌ LOSING")
    
    print(f"\n  {side} side ({status}):")
    print(f"    Fires:        {a['n']}")
    print(f"    Wins/Losses:  {a['w']}W / {a['n']-a['w']}L  (WR: {wr*100:.1f}%)")
    print(f"    Total PnL:    ${a['pnl']:+.2f}")
    print(f"    Avg per fire: ${avg_pnl:+.3f}")
    print(f"    Avg win:      ${avg_win:+.3f}     Best win: ${max_win:+.2f}")
    print(f"    Avg loss:     ${avg_loss:+.3f}    Worst loss: ${worst_loss:+.2f}")
    if a['wins_pnl'] and avg_loss < 0:
        rr = abs(avg_win / avg_loss)
        print(f"    Reward:Risk:  {rr:.2f}:1")

total_n = agg['UP']['n'] + agg['DN']['n']
total_w = agg['UP']['w'] + agg['DN']['w']
total_pnl = agg['UP']['pnl'] + agg['DN']['pnl']
if total_n > 0:
    total_wr = total_w / total_n
    total_avg = total_pnl / total_n
    print(f"\n  COMBINED (UP + DN):")
    print(f"    Total fires:  {total_n}")
    print(f"    Total wins:   {total_w}  WR: {total_wr*100:.1f}%")
    print(f"    Total PnL:    ${total_pnl:+.2f}  (${total_pnl/len(recent):+.3f}/market on avg)")
    print(f"    $/fire:       ${total_avg:+.3f}")


# ── Verdict ──────────────────────────────────────────────────────────────
print("\n  " + "═"*86)
print(f"  VERDICT for {strategy_name} over last {len(recent)} markets")
print("  " + "═"*86)

if total_n == 0:
    print("  ⚠️  Strategy didn't fire in last N markets")
    if is_q:
        print(f"     For _Q variants, check if it ever fired:")
        print(f"     grep -c '\"{strategy_name}\"' parameter_history.jsonl")
    elif is_flip:
        print(f"     For FLIP, base '{base_name}' must have fired:")
        print(f"     grep -c '\"strategy\": \"{base_name}\"' flip_shadow_log.jsonl")
elif total_pnl > 5:
    print(f"  ✅ PROFITABLE: ${total_pnl:+.2f} total  (${total_pnl/len(recent):+.2f}/market)")
    print(f"     This strategy is CURRENTLY making money in recent markets.")
elif total_pnl > 0:
    print(f"  🟡 MILDLY PROFITABLE: ${total_pnl:+.2f} total")
elif total_pnl > -5:
    print(f"  🟡 BREAKEVEN-ISH: ${total_pnl:+.2f} total")
else:
    print(f"  ❌ LOSING: ${total_pnl:+.2f} total  (${total_pnl/len(recent):+.2f}/market)")
print()


# ── If FLIP, compare to base ─────────────────────────────────────────────
if is_flip and total_n > 0:
    print("  " + "─"*86)
    print(f"  COMPARISON: {strategy_name} vs {base_name} (base)")
    print("  " + "─"*86)
    base_pnl, base_n, base_w = 0, 0, 0
    for m in recent:
        for fire in m.get('fires', []):
            if fire.get('strategy') == base_name:
                base_n += 1
                pnl = fire.get('hypo_pnl', 0) or 0
                base_pnl += pnl
                if pnl > 0: base_w += 1
    if base_n > 0:
        base_wr = base_w/base_n*100
        flip_wr = total_w/total_n*100
        print(f"    BASE: n={base_n:<3d}  WR={base_wr:>5.1f}%  PnL=${base_pnl:+.2f}")
        print(f"    FLIP: n={total_n:<3d}  WR={flip_wr:>5.1f}%  PnL=${total_pnl:+.2f}")
        edge_pnl = total_pnl - base_pnl
        edge_wr = flip_wr - base_wr
        print(f"    EDGE: WR Δ={edge_wr:+.1f}pp  PnL Δ=${edge_pnl:+.2f}  (${edge_pnl/len(recent):+.2f}/market)")
        if edge_pnl > 5:
            print(f"    ✅ FLIP would have made ${edge_pnl:+.2f} more than BASE in this window")
        elif edge_pnl < -5:
            print(f"    ❌ FLIP would have done WORSE than BASE")
        print()
