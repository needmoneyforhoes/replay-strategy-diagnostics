#!/usr/bin/env python3
"""
diagnose.py — read moves.log and mechanisms.log and give a clear verdict.

Usage:
    python3 diagnose.py           # last 4 markets
    python3 diagnose.py --n 20    # last N markets
    python3 diagnose.py --all     # all markets in log
"""
import re, sys, os, argparse
from collections import defaultdict

MOVES_LOG      = "moves.log"
MECH_LOG       = "mechanisms.log"
PHASE1_TARGET  = 0.05
SCALE_WARNING  = -0.10
SLUG_RE        = re.compile(r'[a-z]+-updown-5m-\d+')

def parse_moves(path):
    markets    = []
    slug_index = {}
    current    = None

    if not os.path.exists(path):
        print(f"[diagnose] {path} not found")
        return []

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if not line.strip():
                continue
            if "SESSION TOTAL" in line or line.strip().startswith("─") or line.strip().startswith("═"):
                current = None
                continue

            # NEW format: bare slug header
            if SLUG_RE.fullmatch(line.strip()):
                slug = line.strip()
                if slug not in slug_index:
                    m = {"slug": slug, "trades": [], "final_pnl": 0.0}
                    markets.append(m)
                    slug_index[slug] = m
                current = slug_index[slug]
                continue

            # NEW format: indented trade line
            if current is not None and " | " in line and line.startswith("  "):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    try:
                        action   = parts[1].strip()
                        detail   = parts[2].strip()
                        usdc_str = parts[3].replace("USDC","").strip()
                        run_str  = parts[4].replace("running:","").replace("USDC","").strip()
                        note     = parts[6].strip() if len(parts) > 6 else ""
                        current["trades"].append({
                            "ts": parts[0].strip(), "action": action,
                            "detail": detail, "note": note,
                            "usdc": float(usdc_str), "running": float(run_str),
                        })
                        current["final_pnl"] = float(run_str)
                    except (ValueError, IndexError):
                        pass
                continue

            # OLD format: slug embedded in line
            old = re.match(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*\|\s*'
                r'([a-z]+-updown-5m-\d+)\s*\|\s*(.+)', line)
            if old:
                ts_str, slug, rest = old.groups()
                if slug not in slug_index:
                    m = {"slug": slug, "trades": [], "final_pnl": 0.0}
                    markets.append(m)
                    slug_index[slug] = m
                mkt   = slug_index[slug]
                current = None
                parts = [p.strip() for p in rest.split("|")]
                if len(parts) >= 4:
                    try:
                        action   = parts[0].strip()
                        detail   = parts[1].strip()
                        usdc_str = parts[2].replace("USDC","").strip()
                        run_str  = parts[3].replace("running:","").replace("USDC","").strip()
                        note     = parts[5].strip() if len(parts) > 5 else ""
                        mkt["trades"].append({
                            "ts": ts_str, "action": action,
                            "detail": detail, "note": note,
                            "usdc": float(usdc_str), "running": float(run_str),
                        })
                        mkt["final_pnl"] = float(run_str)
                    except (ValueError, IndexError):
                        pass

    return markets


def parse_mechanisms(path):
    result       = defaultdict(list)
    current_slug = None
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line.strip():
                continue
            if SLUG_RE.fullmatch(line.strip()):
                current_slug = line.strip()
                continue
            if current_slug and line.startswith("  "):
                parts = line.strip().split(None, 2)
                if len(parts) >= 2 and re.match(r'\d{2}:\d{2}:\d{2}', parts[0]):
                    result[current_slug].append({
                        "ts":     parts[0],
                        "event":  parts[1],
                        "detail": parts[2] if len(parts) > 2 else "",
                    })
    return result


def classify_loss(market, mechs):
    """
    Rules:
    - Trail with 'dual-factor' or 'hard' in detail = BN confirmed = MARKET_LOSS
    - Trail without either = fired without confirmation = MECHANISM_LOSS
    - BN_STICKY = retry working = NOT a mechanism loss
    - LOSER_BLEED without preceding divergence = MECHANISM_LOSS
    - LOSER_BLEED with divergence = dump missed, bleed caught it = acceptable
    - DROP_UP / DROP_DN = premature classifier sell = MECHANISM_LOSS
    - Winner exit < 0.55 after divergence = exited too early = MECHANISM_LOSS
    """
    slug      = market["slug"]
    events    = mechs.get(slug, [])
    event_map = {e["event"]: e["detail"] for e in events}
    names     = list(event_map.keys())

    has_div = any(e in names for e in (
        "DIV_DOWN_WIN","DIV_UP_WIN","DIV_LOSER_UP","DIV_LOSER_DN",
        "PROFIT_DIV_UP","PROFIT_DIV_DN"))

    issues = []

    # Trail stops — check detail for confirmation
    for te in [e for e in names if e.startswith("TRAIL_")]:
        detail = event_map.get(te, "")
        if "dual-factor" not in detail and "hard" not in detail:
            issues.append(f"{te} fired without BN confirmation")

    # Loser bleed without divergence
    bleeds = [e for e in names if "BLEED" in e]
    if bleeds and not has_div:
        issues.append(f"loser bleed without divergence: {bleeds}")

    # DROP signal
    drops = [e for e in names if e in ("DROP_UP","DROP_DN")]
    if drops:
        issues.append(f"DROP signal sold: {drops}")

    # Winner exit too low after divergence
    if has_div and not issues:
        winner_exit = max(
            (t["usdc"] for t in market["trades"]
             if "SELL-FLAT" in t["action"] and t["usdc"] > 0.20),
            default=0)
        if 0 < winner_exit < 0.55:
            issues.append(f"winner exited too low ({winner_exit:.2f}) after divergence")

    if issues:
        return "MECHANISM_LOSS", " | ".join(issues)

    if has_div:
        return "MARKET_LOSS", "direction wrong, exits correct"

    if not names:
        return "MARKET_LOSS", "no mech events (old format or entry-only)"

    return "MARKET_LOSS", "no mechanism failures"


def run(n_markets):
    markets = parse_moves(MOVES_LOG)
    mechs   = parse_mechanisms(MECH_LOG)

    if not markets:
        print("No markets found in moves.log"); return

    traded = [m for m in markets if any("SELL" in t["action"] for t in m["trades"])]
    if not traded:
        print("No completed trades found yet."); return

    sample = traded[-n_markets:]

    print(f"\n{'═'*68}")
    print(f"  DIAGNOSTIC — last {len(sample)} traded markets")
    print(f"{'─'*68}")

    total_pnl = mech_losses = market_losses = wins = 0

    for m in sample:
        pnl        = m["final_pnl"]
        total_pnl += pnl
        names      = [e["event"] for e in mechs.get(m["slug"], [])]

        if pnl > 0.01:
            verdict = "✅ WIN"; wins += 1
        elif pnl > -0.02:
            verdict = "〰 BREAK"
        else:
            ltype, reason = classify_loss(m, mechs)
            if ltype == "MECHANISM_LOSS":
                verdict = "❌ MECH LOSS"; mech_losses += 1
            else:
                verdict = "📉 MKT LOSS";  market_losses += 1

        key = [e for e in names if e not in ("ENTRY","ARMED_UP","ARMED_DN")][:4]
        ev_str = " → ".join(key) if key else "no mech events"
        print(f"  {m['slug'][-13:]:<14} {verdict:<13}  PnL:{pnl:>+7.3f}  |  {ev_str}")

        if "MECH" in verdict:
            _, reason = classify_loss(m, mechs)
            print(f"  {'':14}  {'':13}  ↳ {reason}")

    n  = len(sample)
    ev = total_pnl / n

    print(f"{'─'*68}")
    print(f"  Markets:{n}  Wins:{wins}  Mech-losses:{mech_losses}  Mkt-losses:{market_losses}")
    print(f"  Total PnL: ${total_pnl:>+.4f}   EV/market: ${ev:>+.4f}")
    print(f"{'─'*68}\n")

    if mech_losses > 0:
        print(f"  🔧 CHANGE NEEDED — {mech_losses} mechanism loss(es)")
        print(f"     Find in mechanisms.log and fix root cause. Target: zero.")
    elif ev >= PHASE1_TARGET:
        stake = 30 / (12 * ev)
        print(f"  🎯 ON TRACK — EV ${ev:+.4f} >= Phase 1 target ${PHASE1_TARGET}")
        print(f"     Sustained over 20 markets → scale to ${stake:.0f}/market for $30/hr")
    elif ev >= 0:
        print(f"  📈 POSITIVE — EV ${ev:+.4f} (target ${PHASE1_TARGET})")
        print(f"     Keep running. Push winner exits higher (target avg 0.80+).")
    elif ev >= SCALE_WARNING:
        print(f"  ⚠️  NEGATIVE EV — ${ev:+.4f}/market")
        if mech_losses == 0:
            print(f"     All market losses — acceptable variance. Keep running.")
        else:
            print(f"     Fix mechanism losses before next session.")
    else:
        print(f"  🚨 URGENT — EV ${ev:+.4f}/market  Stop and diagnose.")

    # ── 1-hour window (last 12 markets) ──────────────────────────────────────
    # 12 markets = 1 hour. This is the scaling milestone.
    # Target: total PnL >= +$0.60 over 12 markets at $1 = Phase 1 confirmed.
    if len(traded) >= 12:
        last12     = traded[-12:]
        pnl_12     = sum(m["final_pnl"] for m in last12)
        ev_12      = pnl_12 / 12
        wins_12    = sum(1 for m in last12 if m["final_pnl"] > 0.01)
        target_pnl = PHASE1_TARGET * 12  # +$0.60
        bar_filled = int(max(0, min(20, (pnl_12 / target_pnl) * 20)))
        bar        = "█" * bar_filled + "░" * (20 - bar_filled)
        status     = "🎯" if pnl_12 >= target_pnl else ("📈" if pnl_12 >= 0 else "⚠️ ")
        print(f"\n  ── 1-HOUR WINDOW (last 12 markets) ──────────────────────────")
        print(f"  {status} PnL: ${pnl_12:>+.4f}  EV/mkt: ${ev_12:>+.4f}  "
              f"Wins: {wins_12}/12")
        print(f"     [{bar}] ${pnl_12:>+.2f} / ${target_pnl:>+.2f} target")
        if pnl_12 >= target_pnl:
            stake = 30 / (12 * ev_12)
            print(f"     ✅ Phase 1 target hit! Scale to ${stake:.0f}/market → $30/hr")
        elif pnl_12 >= 0:
            remaining = target_pnl - pnl_12
            print(f"     ${remaining:.2f} away from Phase 1 target (+$0.60/hr)")
        else:
            print(f"     Keep running — 0 mechanism losses = variance, not a code problem"
                  if mech_losses == 0 else
                  f"     Fix mechanism losses first")
        print(f"  ──────────────────────────────────────────────────────────────")

    print(f"{'═'*68}\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Bot session diagnostic")
    p.add_argument("--n",   type=int, default=4, help="Last N traded markets (default: 4)")
    p.add_argument("--all", action="store_true",  help="Analyze all markets in log")
    args = p.parse_args()
    run(9999 if args.all else args.n)
