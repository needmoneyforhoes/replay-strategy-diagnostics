#!/usr/bin/env python3
"""
diagnose_replay_quality.py — check if replay data quality is consistent across time.

Specifically looks for:
  - Tick count per market (are older markets sparser?)
  - Tick interval statistics (are we missing ticks?)
  - Column availability (did the schema change over time?)
  - Price range coverage (are we seeing extreme early prices in older markets?)
  - First-tick cd (are we catching the market from cd=300 or joining late?)

Usage:
  python3 diagnose_replay_quality.py                    # runs on ./replay_*.json
  python3 diagnose_replay_quality.py /path/to/replays
"""
import json, glob, os, sys
from collections import defaultdict

REPLAY_DIR = sys.argv[1] if len(sys.argv) > 1 else '.'

def main():
    replays = sorted(glob.glob(os.path.join(REPLAY_DIR, 'replay_*.json')))
    print(f"Scanning {len(replays)} replays from {REPLAY_DIR}\n")

    records = []  # one per valid replay
    bad = 0

    for path in replays:
        try:
            with open(path) as f: r = json.load(f)
        except Exception:
            bad += 1
            continue
        slug = os.path.basename(path).replace('replay_btc-updown-5m-', '').replace('.json', '')
        try:
            ts = int(slug)
        except ValueError:
            continue

        cols = r.get('tick_columns', [])
        ticks = r.get('ticks', [])
        winner = r.get('winner')

        has_ua = 'up_ask' in cols
        has_da = 'dn_ask' in cols
        has_bn = 'bn_delta_pct' in cols
        has_d3u = 'up_delta_3s' in cols
        has_d10u = 'up_delta_10s' in cols
        has_cv = 'crowd_conviction' in cols

        if not has_ua or not has_da:
            records.append({'slug': slug, 'ts': ts, 'ticks': 0, 'has_ua': has_ua, 'has_da': has_da,
                            'schema_issue': True, 'winner': winner, 'cols': len(cols)})
            continue

        cd_i = cols.index('cd')
        ua_i = cols.index('up_ask')
        da_i = cols.index('dn_ask')

        # Tick-level stats
        valid_ticks = 0
        first_cd = None
        last_cd = None
        cds = []
        min_up, max_up = 1.0, 0.0
        min_dn, max_dn = 1.0, 0.0
        ua_nulls = 0; da_nulls = 0

        for t in ticks:
            if not t or cd_i >= len(t): continue
            cd = t[cd_i]
            if cd is None: continue
            valid_ticks += 1
            cds.append(cd)
            if first_cd is None: first_cd = cd
            last_cd = cd
            ua = t[ua_i] if ua_i < len(t) else None
            da = t[da_i] if da_i < len(t) else None
            if ua is None: ua_nulls += 1
            else:
                if 0 < ua < 1:
                    min_up = min(min_up, ua); max_up = max(max_up, ua)
            if da is None: da_nulls += 1
            else:
                if 0 < da < 1:
                    min_dn = min(min_dn, da); max_dn = max(max_dn, da)

        # Intervals
        intervals = [abs(cds[i] - cds[i+1]) for i in range(len(cds)-1)] if len(cds) > 1 else []
        median_int = sorted(intervals)[len(intervals)//2] if intervals else 0
        max_int = max(intervals) if intervals else 0

        records.append({
            'slug': slug, 'ts': ts, 'winner': winner,
            'ticks': valid_ticks, 'first_cd': first_cd, 'last_cd': last_cd,
            'median_int': median_int, 'max_int': max_int,
            'min_up': min_up if min_up < 1 else None, 'max_up': max_up if max_up > 0 else None,
            'min_dn': min_dn if min_dn < 1 else None, 'max_dn': max_dn if max_dn > 0 else None,
            'ua_nulls': ua_nulls, 'da_nulls': da_nulls,
            'has_bn': has_bn, 'has_d3u': has_d3u, 'has_d10u': has_d10u, 'has_cv': has_cv,
            'schema_issue': False, 'cols': len(cols),
        })

    records.sort(key=lambda r: r['ts'])
    print(f"Parsed {len(records)} replays ({bad} unreadable)")
    print(f"Timestamp range: {records[0]['slug']} → {records[-1]['slug']}\n")

    # ───────── Schema evolution ─────────
    print("="*100)
    print("SCHEMA EVOLUTION — when did each column first appear?")
    print("="*100)
    col_first = {}
    for feat in ['has_bn', 'has_d3u', 'has_d10u', 'has_cv']:
        for r in records:
            if r.get(feat):
                col_first[feat] = r['slug']; break
    col_last_missing = {}
    for feat in ['has_bn', 'has_d3u', 'has_d10u', 'has_cv']:
        last_without = None
        for r in records:
            if not r.get(feat) and not r.get('schema_issue'):
                last_without = r['slug']
        col_last_missing[feat] = last_without
    for feat in ['has_bn', 'has_d3u', 'has_d10u', 'has_cv']:
        first = col_first.get(feat, 'never')
        last_missing = col_last_missing.get(feat, 'never')
        print(f"  {feat}: first present in {first}, last missing in {last_missing}")

    # ───────── Tick density over time ─────────
    print("\n" + "="*100)
    print("TICK DENSITY ACROSS TIME — are older markets sparser?")
    print("="*100)
    # Bin records into chunks of ~20 and show mean stats per chunk
    chunk_size = max(len(records) // 10, 1)
    print(f"{'chunk':<8} {'slug_range':<30} {'N':<4} {'avg_ticks':<10} {'avg_first_cd':<13} "
          f"{'avg_last_cd':<12} {'median_int':<11} {'p90_int':<8}")
    print("-"*95)
    for i in range(0, len(records), chunk_size):
        chunk = records[i:i+chunk_size]
        if not chunk: continue
        ok = [r for r in chunk if not r['schema_issue']]
        if not ok: continue
        avg_ticks = sum(r['ticks'] for r in ok) / len(ok)
        avg_first = sum(r['first_cd'] for r in ok if r['first_cd']) / max(sum(1 for r in ok if r['first_cd']), 1)
        avg_last = sum(r['last_cd'] for r in ok if r['last_cd'] is not None) / max(sum(1 for r in ok if r['last_cd'] is not None), 1)
        all_intervals = []
        for r in ok:
            if r['median_int']: all_intervals.append(r['median_int'])
        med_int = sorted(all_intervals)[len(all_intervals)//2] if all_intervals else 0
        max_ints = sorted([r['max_int'] for r in ok if r['max_int']])
        p90_int = max_ints[int(len(max_ints)*0.9)] if max_ints else 0
        print(f"chunk{i//chunk_size+1:<3}  {chunk[0]['slug']}-{chunk[-1]['slug']}  "
              f"{len(ok):<4} {avg_ticks:<10.0f} {avg_first:<13.1f} {avg_last:<12.1f} "
              f"{med_int:<11.1f} {p90_int:<8.1f}")

    # ───────── Price extreme coverage ─────────
    print("\n" + "="*100)
    print("PRICE EXTREME COVERAGE — did we capture the full price range in each market?")
    print("="*100)
    print("If first_cd is much less than 300, we MISSED the opening — markets may have had more volatile")
    print("early prices we never saw, systematically biasing the bucket analysis.\n")

    first_cd_dist = defaultdict(int)
    for r in records:
        if r['schema_issue'] or r['first_cd'] is None: continue
        fc = r['first_cd']
        if fc >= 290: first_cd_dist['full_market'] += 1
        elif fc >= 270: first_cd_dist['280-290 (~30s late)'] += 1
        elif fc >= 240: first_cd_dist['240-270 (1min late)'] += 1
        elif fc >= 200: first_cd_dist['200-240 (2min late)'] += 1
        else: first_cd_dist['joined_late (<200)'] += 1

    total = sum(first_cd_dist.values())
    print(f"{'first_tick_cd':<25} {'count':<6} {'%':<6}")
    for k in ['full_market', '280-290 (~30s late)', '240-270 (1min late)', '200-240 (2min late)', 'joined_late (<200)']:
        v = first_cd_dist.get(k, 0)
        print(f"  {k:<23} {v:<6} {v/max(total,1)*100:<5.1f}%")

    # Show how many markets reach each ask-price extreme
    print("\nExtreme prices reached — proportion of markets where each side went below a price:")
    print(f"{'threshold':<15} {'UP_reached':<15} {'DN_reached':<15}")
    for thr in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        up_count = sum(1 for r in records if not r['schema_issue'] and r.get('min_up') is not None and r['min_up'] < thr)
        dn_count = sum(1 for r in records if not r['schema_issue'] and r.get('min_dn') is not None and r['min_dn'] < thr)
        total_valid = sum(1 for r in records if not r['schema_issue'])
        print(f"  ask < ${thr:.2f}     {up_count:<4}/{total_valid} ({up_count/max(total_valid,1)*100:.0f}%)  "
              f"{dn_count:<4}/{total_valid} ({dn_count/max(total_valid,1)*100:.0f}%)")

    # ───────── Break down by time-chunk: does coverage improve in recent markets? ─────────
    print("\n" + "="*100)
    print("COVERAGE BY TIME CHUNK — did recent markets see more price extremes?")
    print("="*100)
    print("If older chunks have lower low-price coverage, older first-visit data is biased upward.\n")

    print(f"{'chunk':<8} {'N':<4} {'UP_min_med':<12} {'DN_min_med':<12} "
          f"{'UP<$0.20':<10} {'DN<$0.20':<10} {'UP<$0.10':<10} {'DN<$0.10':<10}")
    for i in range(0, len(records), chunk_size):
        chunk = [r for r in records[i:i+chunk_size] if not r['schema_issue']]
        if not chunk: continue
        up_mins = sorted(r['min_up'] for r in chunk if r.get('min_up') is not None)
        dn_mins = sorted(r['min_dn'] for r in chunk if r.get('min_dn') is not None)
        up_med = up_mins[len(up_mins)//2] if up_mins else 0
        dn_med = dn_mins[len(dn_mins)//2] if dn_mins else 0
        up_20 = sum(1 for m in up_mins if m < 0.20)
        dn_20 = sum(1 for m in dn_mins if m < 0.20)
        up_10 = sum(1 for m in up_mins if m < 0.10)
        dn_10 = sum(1 for m in dn_mins if m < 0.10)
        N = len(chunk)
        print(f"chunk{i//chunk_size+1:<3}  {N:<4} ${up_med:<10.3f} ${dn_med:<10.3f} "
              f"{up_20}/{N}      {dn_20}/{N}      {up_10}/{N}      {dn_10}/{N}")

    # ───────── Tick-interval outliers ─────────
    print("\n" + "="*100)
    print("TICK-INTERVAL OUTLIERS — markets with long gaps (ws-A + ws-B blackout?)")
    print("="*100)
    print("If many markets have gaps > 10s, those periods are BLIND to the bucket analysis.\n")

    big_gaps = [r for r in records if not r['schema_issue'] and r['max_int'] > 10]
    print(f"Markets with max tick-gap > 10s: {len(big_gaps)}/{len(records)}")
    print(f"Markets with max tick-gap > 30s: {sum(1 for r in records if not r['schema_issue'] and r['max_int'] > 30)}/{len(records)}")
    print(f"Markets with max tick-gap > 60s: {sum(1 for r in records if not r['schema_issue'] and r['max_int'] > 60)}/{len(records)}")
    if big_gaps:
        print(f"\nTop 10 worst gaps:")
        for r in sorted(big_gaps, key=lambda x: -x['max_int'])[:10]:
            print(f"  {r['slug']}  max_gap={r['max_int']:.1f}s  ticks={r['ticks']}  first_cd={r['first_cd']}")


if __name__ == '__main__':
    main()
