"""Fit opponent profiles from downloaded game logs (logs/<tournament>/<game>.json).

  python tools/fit_opps.py [--logs logs] [--last 60]
Writes tools/data/opp_profiles.json (sim Mimic bots) and bot/data/opp_priors.json (bot model seed).
Logs show every player's hole cards, so ranges are measured, not guessed.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
from bot import tables, evaluator  # noqa: E402
from bot.cards import parse_many, hand_class  # noqa: E402
from bot.exploits import k  # noqa: E402

US = 'nontekik'
KIND = re.compile(r'\(([\w ]+)\)')
DEPTHS = (10, 20, 40)          # bb bucket edges: <10, <20, <40, rest
NBINS = 10                     # hand percentile bins
PRIOR_WEIGHT = 60              # bot priors are scaled to at most this many hands


def depth_bucket(bb):
    for i, e in enumerate(DEPTHS):
        if bb < e:
            return i
    return len(DEPTHS)


def pbin(pct):
    return min(NBINS - 1, int(pct * NBINS))


def strength(hole, board):
    """0 = nothing/draw, 1 = one pair, 2 = two pair+, by made category of hole+board."""
    cat = evaluator.category(evaluator.evaluate(parse_many(hole) + parse_many(board)))
    return 0 if cat == 0 else 1 if cat == 1 else 2


def hands(path):
    try:
        d = json.load(open(path))
    except ValueError:
        return
    cur = None
    for x in d:
        t = x.get('type')
        gs = x['game_state']
        if t is None:
            if cur:
                yield cur
            cur = {'game': gs['game_id'], 'round': gs['round'], 'acts': [], 'prev': gs, 'nbets': 0,
                   'start': {p['name']: p['stack'] for p in gs['players']}, 'versions': {p['name']: p.get('version') for p in gs['players']}}
            continue
        if cur is None:
            continue
        if t == 'bet':
            i = x['on_turn']
            p, pp, prev = gs['players'][i], cur['prev']['players'][i], cur['prev']
            m = KIND.search(x['message'])
            cur['nbets'] += 1
            walk = not any(q['status'] == 'active' for j, q in enumerate(gs['players']) if j != i)  # BB acts after all folded
            if not walk and not (len(prev['community_cards']) == 0 and cur['nbets'] <= 2):
                cur['acts'].append({
                    'name': p['name'], 'kind': m.group(1) if m else '?', 'amt': p['bet'] - pp['bet'],
                    'street': len(prev['community_cards']), 'call': max(0, prev['current_buy_in'] - pp['bet']),
                    'stack': pp['stack'], 'pot': prev['pot'], 'bb': prev['small_blind'] * 2,
                    'hole': p['hole_cards'], 'board': prev['community_cards'], 'allin': p['stack'] == 0,
                    'mybet': pp['bet'], 'buyin': prev['current_buy_in']})
        cur['prev'] = gs
    if cur:
        yield cur


class Acc(object):
    def __init__(self):
        z = lambda: [[0, 0] for _ in range(NBINS)]  # noqa: E731
        self.first_in = [[[0, 0, 0] for _ in range(NBINS)] for _ in range(len(DEPTHS) + 1)]  # n, vol, shove
        self.fi_size = [[] for _ in range(len(DEPTHS) + 1)]
        self.vs_raise = [[0, 0, 0] for _ in range(NBINS)]   # n, continue, reraise
        self.vs_allin = z()                                  # n, call
        self.post_open = [[0, 0] for _ in range(3)]          # by strength: n, bet
        self.post_open_size = []
        self.post_face = [[0, 0, 0] for _ in range(3)]       # n, continue, raise
        self.c = collections.Counter()
        self.shove_pcts = []
        self.version = None


def fit(files):
    A = collections.defaultdict(Acc)
    for f in files:
        for h in hands(f):
            for n, ver in h['versions'].items():
                A[n].version = ver
            raised = False
            allin_live = False
            opener, shoved = None, False
            seen = set()
            post_bet = {}
            for a in h['acts']:
                hole = a['hole']
                if len(hole) != 2:
                    continue
                n, acc = a['name'], A[a['name']]
                pct = tables.PCT[hand_class(*parse_many(hole))]
                vol = a['kind'] in ('raise', 'allin') and a['amt'] > a['call']
                if a['street'] == 0:
                    if opener and shoved and n == opener:
                        acc.c['r3_n'] += 1
                        acc.c['r3_c'] += a['kind'] != 'fold'
                        opener = ''
                    if opener is None and vol and not a['allin']:
                        opener = n
                    elif opener and n != opener and a['allin'] and a['amt'] > a['call']:
                        shoved = True
                    if n not in seen:
                        seen.add(n)
                        acc.c['hands'] += 1
                    if not raised:
                        cell = acc.first_in[depth_bucket(a['stack'] / a['bb'])][pbin(pct)]
                        cell[0] += 1
                        if vol:
                            cell[1] += 1
                            if a['allin']:
                                cell[2] += 1
                            else:
                                acc.fi_size[depth_bucket(a['stack'] / a['bb'])].append((a['mybet'] + a['amt']) / a['bb'])
                    elif a['call'] > 0:
                        if allin_live:
                            cell = acc.vs_allin[pbin(pct)]
                            cell[0] += 1
                            cell[1] += a['kind'] != 'fold'
                            acc.c['fts_n'] += 1
                            acc.c['fts_f'] += a['kind'] == 'fold'
                        else:
                            cell = acc.vs_raise[pbin(pct)]
                            cell[0] += 1
                            cell[1] += a['kind'] != 'fold'
                            cell[2] += vol
                    if vol:
                        raised = True
                    if a['allin'] and a['amt'] > a['call']:
                        allin_live = True
                        acc.shove_pcts.append(pct)
                else:
                    s = strength(hole, a['board'])
                    if a['call'] == 0:
                        acc.post_open[s][0] += 1
                        if vol:
                            acc.post_open[s][1] += 1
                            acc.post_open_size.append(a['amt'] / max(1, a['pot']))
                    else:
                        acc.post_face[s][0] += 1
                        acc.post_face[s][1] += a['kind'] != 'fold'
                        acc.post_face[s][2] += vol
                    post_bet[n] = True
            # per-hand flags the bot's live model uses
            mx = collections.defaultdict(int)
            folded, allin = set(), set()
            for a in h['acts']:
                mx[a['name']] = max(mx[a['name']], a['mybet'] + a['amt'])
                if a['kind'] == 'fold':
                    folded.add(a['name'])
                if a['allin']:
                    allin.add(a['name'])
            bb = h['acts'][0]['bb'] if h['acts'] else 2
            for n in seen:
                A[n].c['vpip'] += mx[n] > bb
                A[n].c['aggr'] += mx[n] > 2 * bb or n in allin
                A[n].c['fold'] += n in folded
                A[n].c['allin'] += n in allin
    return A


def rate(k, n, prior, w=3.0):
    return round((k + prior * w) / (n + w), 3)


def profile(acc):
    fi = []
    for d in range(len(DEPTHS) + 1):
        row = acc.first_in[d]
        fi.append({'vol': [rate(c[1], c[0], 0.2) for c in row],
                   'shove': [rate(c[2], c[1], 0.3) for c in row],
                   'size_bb': round(sorted(acc.fi_size[d])[len(acc.fi_size[d]) // 2], 1) if acc.fi_size[d] else 3.0})
    po_sizes = sorted(acc.post_open_size)
    return {
        'first_in': fi,
        'vs_raise_cont': [rate(c[1], c[0], 0.3) for c in acc.vs_raise],
        'vs_raise_reraise': [rate(c[2], c[1], 0.2) for c in acc.vs_raise],
        'vs_allin_call': [rate(c[1], c[0], 0.15) for c in acc.vs_allin],
        'post_bet': [rate(c[1], c[0], 0.3) for c in acc.post_open],
        'post_bet_size': round(po_sizes[len(po_sizes) // 2], 2) if po_sizes else 0.6,
        'post_cont': [rate(c[1], c[0], 0.5) for c in acc.post_face],
        'post_raise': [rate(c[2], c[1], 0.1) for c in acc.post_face],
        'r3_call': rate(acc.c['r3_c'], acc.c['r3_n'], 0.35),
        'n': acc.c['hands'],
    }


def priors(acc):
    n = acc.c['hands']
    if n == 0:
        return None
    k = min(1.0, PRIOR_WEIGHT / float(n))
    s = dict((key, round(acc.c[key] * k, 2)) for key in ('hands', 'allin', 'vpip', 'aggr', 'fold', 'fts_n', 'fts_f'))
    k3 = min(1.0, 15.0 / max(1, acc.c['r3_n']))  # rare spot: keep up to 15 samples
    s['r3_n'], s['r3_c'] = round(acc.c['r3_n'] * k3, 2), round(acc.c['r3_c'] * k3, 2)
    sp = sorted(acc.shove_pcts)
    s['shove_pcts'] = [round(sp[int(q * (len(sp) - 1))], 3) for q in (0.1, 0.3, 0.5, 0.7, 0.9)] if len(sp) >= 5 else []
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logs', default=os.path.join(ROOT, 'logs'))
    ap.add_argument('--last', type=int, default=60, help='newest N game logs')
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.logs, '*', '*.json')), key=os.path.getmtime)[-args.last:]
    A = fit(files)
    names = [n for n, a in A.items() if n != US and a.c['hands']]
    key = lambda n: str(k({'name': n}))  # noqa: E731  no names in the repo
    profs = dict((key(n), profile(A[n])) for n in names)
    pri = dict((key(n), priors(A[n])) for n in names)
    os.makedirs(os.path.join(ROOT, 'tools', 'data'), exist_ok=True)
    json.dump(profs, open(os.path.join(ROOT, 'tools', 'data', 'opp_profiles.json'), 'w'), indent=1)
    json.dump(pri, open(os.path.join(ROOT, 'bot', 'data', 'opp_priors.json'), 'w'), indent=1)
    print('fit %d games' % len(files))
    for n in names:
        p, q = profs[key(n)], pri[key(n)]
        print('%-12s hands=%-5d vpip=%.2f aggr=%.2f allin=%.2f fold_to_allin=%.2f vs_allin_call=%s' % (
            n, p['n'], q['vpip'] / q['hands'], q['aggr'] / q['hands'], q['allin'] / q['hands'],
            q['fts_f'] / max(1, q['fts_n']), p['vs_allin_call']))


if __name__ == '__main__':
    main()
