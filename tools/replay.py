"""Replay our real decision points from cached logs through the current bot.

  python tools/replay.py [--since-version 1.0.0] [--last 40]
Reports: exceptions, latency, how often the current bot would act differently from what was
logged, and net chips of each hand grouped by the reason code of our first logged preflop action.
"""
import argparse
import collections
import contextlib
import io
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import fetch_logs as F  # noqa: E402
from player import Player  # noqa: E402
try:  # replays use real game ids: keep the live-log reader from hitting the Lean Poker API
    from bot import livelog
    livelog.watch = lambda *a, **k: None
except ImportError:
    pass

US = F.US


def our_points(log):
    """Yield (state_for_us, logged_kind, logged_amount, hand) for each of our actions."""
    for h in F.hands(log):
        posted = 0
        for name, kind, amt, street, before in h['actions']:
            if street == 0 and posted < 2 and kind == 'raise':
                posted += 1
                continue
            if name != US or before is None:
                continue
            gs = json.loads(json.dumps(before))
            idx = [i for i, p in enumerate(gs['players']) if p['name'] == US][0]
            gs['in_action'] = idx
            gs.setdefault('minimum_raise', None)
            if gs['minimum_raise'] is None:
                del gs['minimum_raise']
            for i, p in enumerate(gs['players']):
                if i != idx:
                    p['hole_cards'] = []
            yield gs, kind, amt, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tournament', default=None)
    ap.add_argument('--since-version', default='')
    ap.add_argument('--last', type=int, default=40)
    ap.add_argument('--before', default='', help='only games older than this game id (pins a fixed set while live games arrive)')
    ap.add_argument('--preflop', action='store_true', help='with --show: include preflop decisions')
    ap.add_argument('--show', type=float, default=0, help='print postflop decisions of hands we lost >= this many BB')
    args = ap.parse_args()
    tid = args.tournament or F.find_tournament()
    games = F.get('%s/tournament/%s/game' % (F.API, tid))
    if args.since_version:
        games = [g for g in games if any(t['name'] == US and t['version'].startswith(args.since_version) for t in g['teams'])]
    if args.before:
        games = games[:[g['_id'] for g in games].index(args.before)]
    games = games[-args.last:]
    pl = Player()
    lat, diff, n, errs = [], 0, 0, 0
    pnl = collections.defaultdict(lambda: [0, 0])
    newfold = {}  # hand key -> (chips we had in when the new bot folds, hand net)
    for g in games:
        log = F.fetch_log(tid, g)
        done = set()
        for gs, kind, amt, h in our_points(log):
            buf = io.StringIO()
            t = time.perf_counter()
            with contextlib.redirect_stderr(buf):
                a = pl.betRequest(gs)
            lat.append((time.perf_counter() - t) * 1000)
            out = buf.getvalue()
            if 'WARN' in out:
                errs += 1
            n += 1
            if a != amt:
                diff += 1
            if a == 0 and amt > 0 and gs['community_cards'] and gs['current_buy_in'] > gs['players'][gs['in_action']]['bet']:
                k = (g['_id'], h['round'])
                if k not in newfold:
                    st0 = dict((p['name'], p['stack']) for p in h['start']['players'])
                    st1 = dict((p['name'], p['stack'] + p.get('bet', 0)) for p in h['end']['players'])
                    bb = 2.0 * (h['sb'] or 1)
                    newfold[k] = (-gs['players'][gs['in_action']]['bet'] / bb, (st1[US] - st0[US]) / bb)
            if args.show and (gs['community_cards'] or args.preflop):
                st0 = dict((p['name'], p['stack']) for p in h['start']['players'])
                st1 = dict((p['name'], p['stack'] + p.get('bet', 0)) for p in h['end']['players'])
                if (st0[US] - st1[US]) / (2.0 * (h['sb'] or 1)) >= args.show:
                    rec = json.loads(out.splitlines()[-1]) if out.strip() else {}
                    print('  %s r%s %s %s | logged %s %d -> now %s %d | eq %s aggr %s req %s' % (
                        g['_id'][-6:], h['round'], rec.get('hand'), rec.get('board'), kind, amt, rec.get('intent'), a,
                        rec.get('eq'), rec.get('aggr'), rec.get('required')) + (' | %s p_fold %s ranges %s pct %s' % (
                        rec.get('reason_code'), rec.get('p_fold'), rec.get('ranges'), rec.get('pct')) if args.preflop else ''))
            if h['round'] not in done and not gs['community_cards']:
                done.add(h['round'])
                rec = {}
                for line in out.splitlines():
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        pass
                st0 = dict((p['name'], p['stack']) for p in h['start']['players'])
                st1 = dict((p['name'], p['stack'] + p.get('bet', 0)) for p in h['end']['players'])
                bb = 2 * (h['sb'] or 1)
                key = (rec.get('reason_code', '?'), kind)
                pnl[key][0] += 1
                pnl[key][1] += (st1[US] - st0[US]) / float(bb)
        end = log[-1]['game_state'] if log else None
        if end:
            pl.showdown(dict(end, in_action=[i for i, p in enumerate(end['players']) if p['name'] == US][0]))
    lat.sort()
    print('decisions %d  exceptions %d  differs-from-logged %d (%.0f%%)  ms p50 %.1f p99 %.1f' % (
        n, errs, diff, 100.0 * diff / max(1, n), lat[len(lat) // 2] if lat else 0, lat[int(len(lat) * .99)] if lat else 0))
    if newfold:
        fold_bb = sum(x[0] for x in newfold.values())
        real_bb = sum(x[1] for x in newfold.values())
        print('postflop spots where now FOLD but logged continued: %d hands, real result %.1f BB, folding gives %.1f BB -> %+.1f BB' % (
            len(newfold), real_bb, fold_bb, fold_bb - real_bb))
    print('net BB by (current reason code, logged first preflop action):')
    for k, (c, bbs) in sorted(pnl.items(), key=lambda x: x[1][1]):
        print('  %-22s %-6s n=%4d  net %8.1f BB  per hand %6.2f' % (k[0], k[1], c, bbs, bbs / c))


if __name__ == '__main__':
    main()
