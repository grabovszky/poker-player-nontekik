"""Download Lean Poker game logs for our tournament and summarize what happened.

  python tools/fetch_logs.py                 # latest tournament we're in, last 40 games
  python tools/fetch_logs.py --last 100 --since-version 1.1
Logs are cached in logs/<tournament>/<game>.json (gitignored).
"""
import argparse
import collections
import gzip
import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from bot import tables  # noqa: E402
from bot.cards import parse_many, hand_class, class_name  # noqa: E402

API = 'https://live.leanpoker.org/api'
US = 'nontekik'


def get(url):
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'gzip', 'User-Agent': 'nontekik-logfetch'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        if r.headers.get('Content-Encoding') == 'gzip' or data[:2] == b'\x1f\x8b':
            data = gzip.decompress(data)
    return json.loads(data)


def find_tournament():
    for t in get(API + '/tournament'):
        if any(tm.get('name') == US for tm in t.get('teams', [])):
            return t['id']
    raise SystemExit('no tournament with team %s' % US)


def fetch_log(tid, game):
    gid = game['_id']
    d = os.path.join(ROOT, 'logs', tid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, gid + '.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    base = '%s/tournament/%s/game/%s' % (API, tid, gid)
    if game.get('fragments') or get(base).get('fragments'):
        log, i = [], 0
        while True:
            try:
                log += get('%s/log?fragment=%d' % (base, i))
            except Exception:
                break
            i += 1
    else:
        log = get(base + '/log')
    with open(path, 'w') as f:
        json.dump(log, f)
    return log


def hands(log):
    """Split a log into hands: {'round', 'sb', 'start', 'end', 'actions': [(name, kind, amount, street, state_before)]}"""
    out, cur, prev = [], None, None
    for e in log:
        gs = e.get('game_state') or {}
        t = e.get('type')
        if t is None:
            cur = {'round': gs.get('round'), 'sb': gs.get('small_blind'), 'start': gs, 'actions': [], 'end': gs}
            out.append(cur)
        elif cur is not None:
            if t == 'bet':
                msg = e.get('message', '')
                kind = msg[msg.rfind('(') + 1:msg.rfind(')')] if '(' in msg else '?'
                try:
                    amt = int(msg.split('made a bet of ')[1].split(' ')[0])
                except Exception:
                    amt = 0
                name = gs['players'][e['on_turn']]['name'] if 'on_turn' in e else msg.split(' ')[0]
                cur['actions'].append((name, kind, amt, len(gs.get('community_cards') or []), prev))
            if t in ('showdown', 'bet', 'card_deal', 'winner_announcement'):
                cur['end'] = gs
        prev = gs
    return out


def pct_of(cards):
    if not cards or len(cards) != 2:
        return None
    c = parse_many(cards)
    return tables.PCT[hand_class(c[0], c[1])]


def name_of(cards):
    c = parse_many(cards)
    return class_name(hand_class(c[0], c[1]))


def analyze(games_logs):
    S = collections.defaultdict(lambda: collections.Counter())
    shove_pcts = collections.defaultdict(list)
    callallin_pcts = collections.defaultdict(list)
    raise_sizes = collections.defaultdict(list)
    our_big = []
    n_hands = 0
    for game, log in games_logs:
        for h in hands(log):
            n_hands += 1
            end = h['end']
            holes = {}
            for p in end.get('players', []):
                holes[p['name']] = p.get('hole_cards')
            bb = 2 * (h['sb'] or 1)
            posted = 0
            seen_pf = set()
            facing_allin = False
            for name, kind, amt, street, before in h['actions']:
                if street == 0 and posted < 2 and kind == 'raise':
                    posted += 1
                    continue
                s = S[name]
                if street == 0:
                    if name not in seen_pf:
                        seen_pf.add(name)
                        s['pf_hands'] += 1
                        if kind in ('call', 'raise', 'allin'):
                            s['vpip'] += 1
                        if kind in ('raise', 'allin'):
                            s['pfr'] += 1
                        if kind == 'allin':
                            s['pf_allin'] += 1
                        if kind == 'fold':
                            s['pf_fold'] += 1
                    if facing_allin and kind in ('fold', 'call', 'allin'):
                        s['vs_allin'] += 1
                        if kind == 'fold':
                            s['vs_allin_fold'] += 1
                        else:
                            p = pct_of(holes.get(name))
                            if p is not None:
                                callallin_pcts[name].append(p)
                    if kind == 'allin':
                        p = pct_of(holes.get(name))
                        if p is not None:
                            shove_pcts[name].append(p)
                        facing_allin = True
                    if kind == 'raise' and before:
                        raise_sizes[name].append(round((amt + 0.0) / bb, 1))
                else:
                    s['post_act'] += 1
                    if kind in ('raise', 'allin'):
                        s['post_aggr'] += 1
                    if kind == 'fold':
                        s['post_fold'] += 1
            # our chip result this hand
            st0 = dict((p['name'], p['stack']) for p in h['start'].get('players', []))
            st1 = dict((p['name'], p['stack'] + p.get('bet', 0)) for p in end.get('players', []))
            if US in st0 and US in st1:
                our_big.append((st1[US] - st0[US], game['_id'][-6:], h['round'], name_of(holes[US]) if holes.get(US) else '?',
                                [(a[0][:8], a[1], a[2], a[3]) for a in h['actions'] if a[1] != 'fold']))
    return S, shove_pcts, callallin_pcts, raise_sizes, our_big, n_hands


def q(xs, f):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(f * len(xs)))] if xs else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tournament')
    ap.add_argument('--last', type=int, default=40)
    ap.add_argument('--since-version', default='', help='only games where our version starts with this')
    ap.add_argument('--losses', type=int, default=8, help='print our N biggest losing hands')
    args = ap.parse_args()
    tid = args.tournament or find_tournament()
    games = [g for g in get('%s/tournament/%s/game' % (API, tid)) if g.get('status', 'done') == 'done' or 'teams' in g]
    if args.since_version:
        games = [g for g in games if any(t['name'] == US and t['version'].startswith(args.since_version) for t in g['teams'])]
    games = games[-args.last:]

    print('== scoreboard (%d games, tournament %s)' % (len(games), tid))
    sc = collections.defaultdict(lambda: [0, 0, 0, 0])
    for g in games:
        for t in g['teams']:
            k = (t['name'], t['version'][:45])
            sc[k][0] += 1
            sc[k][1] += t['gained']
            sc[k][2] += t['gained'] == 5
            sc[k][3] += t['gained'] == 3
    for (nm, ver), (n, pts, w, s2) in sorted(sc.items(), key=lambda x: -x[1][1] / max(1, x[1][0])):
        print('  %-11s %-46s games %3d  pts/game %.2f  win %3.0f%%  2nd %3.0f%%' % (nm, ver, n, pts / float(n), 100.0 * w / n, 100.0 * s2 / n))

    gl = []
    for g in games:
        try:
            gl.append((g, fetch_log(tid, g)))
        except Exception as e:
            print('  ! failed', g['_id'], e)
    S, shove, callai, rs, our, n_hands = analyze(gl)
    lens = [max([h['round'] for h in hands(l)] or [0]) + 1 for _, l in gl]
    print('== %d hands, hands/game median %d max %d' % (n_hands, q(lens, 0.5), max(lens or [0])))
    print('== preflop profile (pct = combo-weighted hand percentile, 0 = AA)')
    for nm, s in sorted(S.items()):
        n = max(1, s['pf_hands'])
        print('  %-11s hands %4d vpip %3.0f%% pfr %3.0f%% allin %3.0f%% fold %3.0f%% | vs-allin fold %3.0f%% (n=%d) | '
              'shove pct p50 %.2f p90 %.2f | call-allin pct p50 %.2f p90 %.2f | raise BB p50 %.1f | post aggr %3.0f%% fold %3.0f%%' % (
                  nm, s['pf_hands'], 100.0 * s['vpip'] / n, 100.0 * s['pfr'] / n, 100.0 * s['pf_allin'] / n, 100.0 * s['pf_fold'] / n,
                  100.0 * s['vs_allin_fold'] / max(1, s['vs_allin']), s['vs_allin'], q(shove[nm], .5), q(shove[nm], .9),
                  q(callai[nm], .5), q(callai[nm], .9), q(rs[nm], .5),
                  100.0 * s['post_aggr'] / max(1, s['post_act']), 100.0 * s['post_fold'] / max(1, s['post_act'])))
    our.sort(key=lambda x: x[0])
    print('== our %d biggest losses' % args.losses)
    for d, gid, rnd, hand, acts in our[:args.losses]:
        print('  %6d  game %s r%-3s %-4s %s' % (d, gid, rnd, hand, acts[:14]))
    print('== our net chips by hand: won %d hands, lost %d, net %d' % (
        sum(1 for x in our if x[0] > 0), sum(1 for x in our if x[0] < 0), sum(x[0] for x in our)))


if __name__ == '__main__':
    main()
