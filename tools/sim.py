"""In-process NLHE sit'n'go simulator in the Lean Poker game_state shape.

  python tools/sim.py --a current --b baseline --n 2000
  --a/--b: current (working tree) | baseline (= git:HEAD) | git:<ref> | path:<dir> | <BuiltinBot>
Paired comparison: game i uses the same lineup, seats and deck seed for A and B.
"""
import argparse
import importlib.util
import json
import math
import os
import random
import subprocess
import sys
import time
from multiprocessing import Pool

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_spec = importlib.util.spec_from_file_location('sim_eval', os.path.join(ROOT, 'bot', 'evaluator.py'))
EV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EV)

RANK_STR = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUIT_STR = ['clubs', 'diamonds', 'hearts', 'spades']
OUR_NAME = 'nontekik'


def card_json(c):
    return {'rank': RANK_STR[c >> 2], 'suit': SUIT_STR[c & 3]}


def card_int(d):
    r = str(d['rank'])
    return (RANK_STR.index('10' if r == 'T' else r)) * 4 + SUIT_STR.index(d['suit'])


# ---------------------------------------------------------------- built-in opponents

def _chen(hole):
    c = sorted([card_int(x) for x in hole], reverse=True)
    hi, lo = c[0] >> 2, c[1] >> 2
    pts = {12: 10, 11: 8, 10: 7, 9: 6}
    s = pts.get(hi, (hi + 2) / 2.0)
    if hi == lo:
        return max(5, math.ceil(s * 2))
    if c[0] & 3 == c[1] & 3:
        s += 2
    gap = hi - lo - 1
    s -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and hi < 10:
        s += 1
    return math.ceil(s)


def _me(s):
    return s['players'][s['in_action']]


def _call(s):
    return max(0, s['current_buy_in'] - _me(s)['bet'])


def _made(s):
    cards = [card_int(c) for c in _me(s)['hole_cards'] + s['community_cards']]
    return EV.evaluate(cards) >> 20 if len(cards) >= 5 else 0


def b_folder(s):
    return 0


def b_allin(s):
    return _me(s)['stack']


def b_station(s):
    return _call(s)


def b_chenpusher(s):
    if s['community_cards']:
        return 0
    bb = 2 * s['small_blind']
    thr = 7 if _me(s)['stack'] < 15 * bb else 9
    return _me(s)['stack'] if _chen(_me(s)['hole_cards']) >= thr else 0


def b_tightpassive(s):
    if not s['community_cards']:
        return _call(s) if _chen(_me(s)['hole_cards']) >= 9 else 0
    return _call(s) if _made(s) >= 1 else 0


def b_thresholdcaller(s):
    if not s['community_cards']:
        return _call(s) if _chen(_me(s)['hole_cards']) >= 6 else 0
    return _call(s) if _made(s) >= 1 else 0


def b_randomaggro(s):
    r = random.Random('%s|%s|%s|%s' % (s['game_id'], s['round'], s['bet_index'], _me(s)['name'])).random()
    if r < 0.3:
        return 0
    if r < 0.7:
        return _call(s)
    return _call(s) + s['minimum_raise'] + int(r * s['pot'])


def _pct(hole):
    a, b = [card_int(x) for x in hole]
    r1, r2 = max(a >> 2, b >> 2), min(a >> 2, b >> 2)
    if r1 == r2:
        idx = (12 - r1) * 13 + (12 - r1)
    elif (a & 3) == (b & 3):
        idx = (12 - r1) * 13 + (12 - r2)
    else:
        idx = (12 - r2) * 13 + (12 - r1)
    return MIMIC_PCT[idx]


def mimic(prof):
    """Opponent fitted from real logs (tools/fit_opps.py): action probabilities by hand percentile bin."""
    def bot(s):
        me = _me(s)
        r = random.Random('%s|%s|%s|%s' % (s['game_id'], s['round'], s['bet_index'], me['name']))
        bb = 2 * s['small_blind']
        call, stack = _call(s), me['stack']
        raise_to = lambda total: max(call + s['minimum_raise'], total - me['bet'])  # noqa: E731
        if not s['community_cards']:
            b = min(9, int(_pct(me['hole_cards']) * 10))
            allin_live = any(p['status'] == 'active' and p['stack'] == 0 and p['bet'] > bb for p in s['players'])
            if s['current_buy_in'] <= bb:
                d = 0 if stack < 10 * bb else 1 if stack < 20 * bb else 2 if stack < 40 * bb else 3
                fi = prof['first_in'][d]
                if r.random() < fi['vol'][b]:
                    return stack if r.random() < fi['shove'][b] else raise_to(int(fi['size_bb'] * bb))
                return call if call == 0 else 0
            if allin_live:
                if me['bet'] > bb and 'r3_call' in prof:  # we opened: defend at the measured rate, best hands first
                    d = 0 if stack < 10 * bb else 1 if stack < 20 * bb else 2 if stack < 40 * bb else 3
                    width = sum(prof['first_in'][d]['vol']) / 10.0
                    return call if _pct(me['hole_cards']) <= prof['r3_call'] * width else 0
                return call if r.random() < prof['vs_allin_call'][b] else 0
            if r.random() < prof['vs_raise_cont'][b]:
                return raise_to(3 * s['current_buy_in']) if r.random() < prof['vs_raise_reraise'][b] else call
            return 0
        m = _made(s)
        st = 0 if m == 0 else 1 if m == 1 else 2
        if call == 0:
            return raise_to(int(prof['post_bet_size'] * s['pot'])) if r.random() < prof['post_bet'][st] else 0
        if r.random() < prof['post_cont'][st]:
            return raise_to(int(2.5 * s['current_buy_in'])) if r.random() < prof['post_raise'][st] else call
        return 0
    return bot


# ---- profile bots fitted to live opponents (tools/fetch_logs.py preflop profile)

_PF = json.load(open(os.path.join(ROOT, 'bot', 'data', 'preflop.json')))


def _cls(c1, c2):
    r1, r2 = c1 >> 2, c2 >> 2
    hi, lo = max(r1, r2), min(r1, r2)
    if hi == lo:
        return (12 - hi) * 14
    if (c1 & 3) == (c2 & 3):
        return (12 - hi) * 13 + (12 - lo)
    return (12 - lo) * 13 + (12 - hi)


def _w(i):
    row, col = divmod(i, 13)
    return 6 if row == col else 4 if row < col else 12


PCT = [0.0] * 169
_acc = 0
for _i in _PF['order']:
    PCT[_i] = (_acc + _w(_i) / 2.0) / 1326.0
    _acc += _w(_i)


def _hand_pct(s):
    h = [card_int(c) for c in _me(s)['hole_cards']]
    return PCT[_cls(h[0], h[1])] if len(h) == 2 else 1.0


def _strength(s):
    hole = [card_int(c) for c in _me(s)['hole_cards']]
    board = [card_int(c) for c in s['community_cards']]
    cat = EV.evaluate(hole + board) >> 20
    cnt = sorted([sum(1 for c in board if c >> 2 == r) for r in set(c >> 2 for c in board)], reverse=True)
    bcat = 3 if cnt[0] >= 3 else 2 if cnt[0] == 2 and len(cnt) > 1 and cnt[1] == 2 else 1 if cnt[0] == 2 else 0
    return max(0, cat - bcat)


class Profile(object):
    def __init__(self, open_, shove, shove_bb, call_allin, threebet, callr, post_aggr, post_bluff, raise_x):
        self.__dict__.update(locals())

    def __call__(self, s):
        me = _me(s)
        stack, call, bb = me['stack'], _call(s), 2 * s['small_blind']
        rng = random.Random('%s|%s|%s|%s' % (s['game_id'], s['round'], s['bet_index'], me['name'])).random()
        if not s['community_cards']:
            pct = _hand_pct(s)
            if call >= 0.4 * stack and s['current_buy_in'] > bb:
                return stack if pct <= self.call_allin else 0
            if s['current_buy_in'] <= bb:
                if pct <= self.shove or (stack <= self.shove_bb * bb and pct <= max(self.shove, 0.35)):
                    return stack
                if pct <= self.open_:
                    return call + max(s['minimum_raise'], int((self.raise_x - 1) * bb))
                return 0
            if pct <= self.threebet:
                return call + max(s['minimum_raise'], 2 * s['current_buy_in'])
            if pct <= self.callr and call <= 0.2 * stack:
                return call
            return 0
        st = _strength(s)
        pot = s['pot']
        if call == 0:
            if st >= 2 or (st == 1 and rng < self.post_aggr) or rng < self.post_bluff:
                return max(s['minimum_raise'], int(pot * 0.6))
            return 0
        if st >= 2:
            return call + max(s['minimum_raise'], pot) if rng < self.post_aggr else call
        if st == 1 and call <= 0.6 * pot:
            return call
        return call if rng < self.post_bluff * 0.5 else 0


LIVE = {'Bpex': Profile(0.24, 0.12, 15, 0.10, 0.06, 0.20, 0.6, 0.15, 3.0),
        'Megis': Profile(0.20, 0.04, 10, 0.06, 0.05, 0.10, 0.4, 0.05, 3.0),
        'Techyk': Profile(0.25, 0.03, 8, 0.28, 0.10, 0.35, 0.8, 0.30, 1.5)}

BUILTINS = {'Folder': b_folder, 'AllIn': b_allin, 'CallingStation': b_station, 'ChenPusher': b_chenpusher,
            'TightPassive': b_tightpassive, 'RandomAggro': b_randomaggro, 'ThresholdCaller': b_thresholdcaller}
BUILTINS.update(LIVE)
_PROF = os.path.join(ROOT, 'tools', 'data', 'opp_profiles.json')
MIMICS = json.load(open(_PROF)) if os.path.exists(_PROF) else {}
_tab = json.load(open(os.path.join(ROOT, 'bot', 'data', 'preflop.json'))) if MIMICS else None
MIMIC_PCT = [0.0] * 169
if _tab:
    _w = [6 if i // 13 == i % 13 else 4 if i % 13 > i // 13 else 12 for i in range(169)]
    _acc = 0
    for _i in _tab['order']:
        MIMIC_PCT[_i] = (_acc + _w[_i] / 2.0) / 1326.0
        _acc += _w[_i]
for _n, _p in MIMICS.items():
    BUILTINS[_n] = mimic(_p)


# ---------------------------------------------------------------- engine

class Game(object):
    def __init__(self, gid, seats, rng, args, clock):
        self.gid, self.rng, self.args, self.clock = gid, rng, args, clock
        self.seats = seats  # list of (name, bet_fn, showdown_fn)
        self.players = [{'id': i, 'name': nm, 'status': 'active', 'version': '1', 'stack': args.chips,
                         'bet': 0, 'hole_cards': []} for i, (nm, _, _) in enumerate(seats)]
        self.dealer = rng.randrange(len(seats))
        self.busted = []  # names, first busted first
        self.errors = 0
        self.lat = []

    def state(self, i, reveal=False):
        ps = []
        for j, p in enumerate(self.players):
            q = dict(p)
            q['hole_cards'] = [card_json(c) for c in p['hole_cards']] if (j == i or (reveal and p['status'] == 'active')) else []
            ps.append(q)
        return {'tournament_id': 'sim', 'game_id': self.gid, 'round': self.round, 'bet_index': self.bet_index,
                'small_blind': self.sb, 'current_buy_in': self.cbi, 'pot': sum(p['bet'] for p in self.players),
                'minimum_raise': self.min_raise, 'dealer': self.dealer, 'orbits': self.round // max(1, len(self.alive)),
                'in_action': i, 'players': ps, 'community_cards': [card_json(c) for c in self.board]}

    def ask(self, i):
        name, fn, _ = self.seats[i]
        t = time.perf_counter()
        try:
            a = fn(self.state(i))
        except Exception:
            a = None
        if name == OUR_NAME:
            self.lat.append((time.perf_counter() - t) * 1000)
        if not isinstance(a, int) or a < 0:
            if name == OUR_NAME:
                self.errors += 1
            return 0
        return a

    def put(self, p, amt):
        amt = min(amt, p['stack'])
        p['stack'] -= amt
        p['bet'] += amt

    def run(self):
        sbs = [int(x) for x in self.args.blinds.split(',')]
        for self.round in range(self.args.max_hands):
            self.alive = [i for i, p in enumerate(self.players) if p['stack'] > 0]
            if len(self.alive) <= 1:
                break
            self.clock[0] = self.clock_base + self.round * self.args.hand_sec
            self.sb = sbs[min(self.round // self.args.blind_hands, len(sbs) - 1)]
            before = dict((i, self.players[i]['stack']) for i in self.alive)
            self.hand()
            assert sum(p['stack'] for p in self.players) == self.args.chips * len(self.players), 'chips leaked'
            gone = [i for i in self.alive if self.players[i]['stack'] == 0]
            for i in sorted(gone, key=lambda k: before[k]):
                self.busted.append(self.players[i]['name'])
            n = len(self.players)
            for k in range(1, n + 1):
                d = (self.dealer + k) % n
                if self.players[d]['stack'] > 0:
                    self.dealer = d
                    break
        live = sorted([p for p in self.players if p['stack'] > 0], key=lambda p: -p['stack'])
        return [p['name'] for p in live] + self.busted[::-1]

    def hand(self):
        n = len(self.players)
        for p in self.players:
            p['bet'] = 0
            p['hole_cards'] = []
            p['status'] = 'active' if p['stack'] > 0 else 'out'
        if self.players[self.dealer]['stack'] == 0:
            self.dealer = self.alive[0]
        a = [(self.dealer + k) % n for k in range(n) if self.players[(self.dealer + k) % n]['stack'] > 0]
        deck = list(range(52))
        self.rng.shuffle(deck)
        self.board = []
        self.bet_index = 0
        bb = 2 * self.sb
        sbi, bbi = (a[0], a[1]) if len(a) == 2 else (a[1], a[2])
        self.put(self.players[sbi], self.sb)
        self.put(self.players[bbi], bb)
        for i in a:
            self.players[i]['hole_cards'] = [deck.pop(), deck.pop()]
        pre = [a[0], a[1]] if len(a) == 2 else a[3:] + a[:3]
        post = a[1:] + a[:1]
        for street, order in ((0, pre), (3, post), (4, post), (5, post)):
            if street:
                while len(self.board) < street:
                    self.board.append(deck.pop())
            in_hand = [i for i in a if self.players[i]['status'] == 'active']
            if len(in_hand) <= 1:
                break
            can_act = [i for i in in_hand if self.players[i]['stack'] > 0]
            top = max(self.players[i]['bet'] for i in in_hand)
            if len(can_act) == 0 or (len(can_act) == 1 and self.players[can_act[0]]['bet'] >= top):
                continue
            self.betting(order, bb)
        while len(self.board) < 5 and sum(1 for i in a if self.players[i]['status'] == 'active') > 1:
            self.board.append(deck.pop())
        self.payout(a)

    def betting(self, order, bb):
        self.cbi = max(p['bet'] for p in self.players)
        self.min_raise = bb
        acted = set()
        k = 0
        while True:
            act = [i for i in order if self.players[i]['status'] == 'active']
            if len(act) <= 1:
                return
            todo = [i for i in act if self.players[i]['stack'] > 0 and (i not in acted or self.players[i]['bet'] < self.cbi)]
            if not todo:
                return
            i = order[k % len(order)]
            k += 1
            if i not in todo:
                continue
            p = self.players[i]
            call = self.cbi - p['bet']
            amt = min(self.ask(i), p['stack'])
            self.bet_index += 1
            acted.add(i)
            if amt == p['stack'] and amt > 0:
                self.put(p, amt)
                if p['bet'] > self.cbi:
                    self.min_raise = max(self.min_raise, p['bet'] - self.cbi)
                    self.cbi = p['bet']
                    acted = set([i])
            elif amt < call:
                p['status'] = 'folded'
            elif amt < call + self.min_raise:
                self.put(p, call)
            else:
                self.put(p, amt)
                self.min_raise = amt - call
                self.cbi = p['bet']
                acted = set([i])

    def payout(self, a):
        live = [i for i in a if self.players[i]['status'] == 'active']
        showdown = len(live) > 1
        vals = dict((i, EV.evaluate(self.players[i]['hole_cards'] + self.board)) for i in live) if showdown else {}
        bets = [p['bet'] for p in self.players]
        levels = sorted(set(b for b in bets if b > 0))
        prev = 0
        for lv in levels:
            layer = sum(min(b, lv) - min(b, prev) for b in bets)
            elig = [i for i in live if bets[i] >= lv] or [i for i in range(len(bets)) if bets[i] >= lv]
            if showdown and len(elig) > 1:
                best = max(vals.get(i, -1) for i in elig)
                win = [i for i in elig if vals.get(i, -1) == best]
            else:
                win = elig[:1]
            share, odd = divmod(layer, len(win))
            for j, i in enumerate(win):
                self.players[i]['stack'] += share + (1 if j < odd else 0)
            prev = lv
        if showdown:
            for i, (_, _, sd) in enumerate(self.seats):
                if sd and self.players[i]['status'] != 'out':
                    try:
                        sd(self.state(i, reveal=True))
                    except Exception:
                        pass
        for p in self.players:
            p['bet'] = 0


# ---------------------------------------------------------------- candidates & workers

def snapshot(ref):
    sha = subprocess.check_output(['git', '-C', ROOT, 'rev-parse', '--short', ref]).decode().strip()
    d = os.path.join(ROOT, '.sim_cache', sha)
    if not os.path.isdir(d):
        os.makedirs(d)
        arc = subprocess.check_output(['git', '-C', ROOT, 'archive', sha, 'bot', 'player.py'])
        subprocess.run(['tar', '-x', '-C', d], input=arc, check=True)
    return d


def resolve(spec):
    if spec in BUILTINS:
        return spec
    if spec == 'current':
        return ROOT
    if spec == 'baseline':
        spec = 'git:HEAD'
    if spec.startswith('git:'):
        return snapshot(spec[4:])
    if spec.startswith('path:') and os.path.isfile(os.path.join(spec[5:], 'player.py')):
        return os.path.abspath(spec[5:])
    raise SystemExit('unknown candidate %r' % spec)


W = {}


def init(cand, args):
    W['args'] = args
    W['clock'] = [0.0]
    if cand in BUILTINS:
        W['ours'] = (BUILTINS[cand], None)
        return
    sys.path.insert(0, cand)
    import player
    try:
        from bot import config, tournament
        config.decision_budget_ms = args.budget_ms
        config.mc_max_iters = args.iters
        tournament.now = lambda: W['clock'][0]
    except Exception:
        pass
    pl = player.Player()
    W['ours'] = (pl.betRequest, pl.showdown)


def lineup(i, args):
    rng = random.Random(args.seed * 100003 + i)
    if args.opps == 'live':  # the real table: us + the three live opponents, random seats
        names = sorted(LIVE)
        names.insert(rng.randrange(len(names) + 1), OUR_NAME)
        return names, rng.randrange(1 << 30)
    pool = args.opps.split(',')
    k = rng.randint(args.min_players, args.max_players) - 1
    names = []
    for _ in range(k):
        b = rng.choice(pool)
        nm = b
        j = 2
        while nm in names:
            nm = '%s%d' % (b, j)
            j += 1
        names.append(nm)
    pos = rng.randrange(k + 1)
    names.insert(pos, OUR_NAME)
    return names, rng.randrange(1 << 30)


def play(i):
    args = W['args']
    names, deck_seed = lineup(i, args)
    seats = []
    for nm in names:
        if nm == OUR_NAME:
            seats.append((nm,) + W['ours'])
        else:
            seats.append((nm, BUILTINS[nm.rstrip('0123456789')], None))
    g = Game('sim-%d' % i, seats, random.Random(deck_seed), args, W['clock'])
    g.clock_base = i * 100000.0
    places = g.run()
    place = places.index(OUR_NAME) + 1
    pts = 5 if place == 1 else 3 if place == 2 else 0
    return i, pts, place, len(names), g.errors, g.lat


def run(cand, args):
    out = {}
    lat = []
    errors = 0
    with Pool(args.procs, initializer=init, initargs=(cand, args)) as pool:
        for i, pts, place, n, err, l in pool.imap_unordered(play, range(args.n), chunksize=8):
            out[i] = (pts, place, n)
            errors += err
            lat.extend(l)
    return out, lat, errors


def summary(label, res, lat, errors):
    pts = [r[0] for r in res.values()]
    n = len(pts)
    m = sum(pts) / float(n)
    sd = math.sqrt(sum((x - m) ** 2 for x in pts) / max(1, n - 1))
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else 0.0
    print('%-12s pts/game %.3f ±%.3f  win %.1f%%  2nd %.1f%%  errors %d  ms p50 %.1f p99 %.1f' % (
        label, m, 1.96 * sd / math.sqrt(n), 100.0 * pts.count(5) / n, 100.0 * pts.count(3) / n, errors, p(0.5), p(0.99)))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default='current')
    ap.add_argument('--b', default='baseline')
    ap.add_argument('--n', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--procs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--opps', default=','.join(sorted(MIMICS)) or ','.join(sorted(BUILTINS)),
                    help='default: the log-fitted real opponents if tools/data/opp_profiles.json exists')
    ap.add_argument('--min-players', type=int, default=4)
    ap.add_argument('--max-players', type=int, default=4)
    ap.add_argument('--chips', type=int, default=1000)
    ap.add_argument('--blinds', default='2,3,5,10,15,20,30,40,50,70,100,150,200,300,400,500,600,800,1000',
                    help='small blind schedule per 10 rounds (from live logs up to 300)')
    ap.add_argument('--blind-hands', type=int, default=10, help='hands per blind level')
    ap.add_argument('--max-hands', type=int, default=400, help='safety cap; live games end in 73-133 rounds')
    ap.add_argument('--hand-sec', type=float, default=0.2, help='simulated seconds per hand (live: ~100 rounds in ~25s)')
    ap.add_argument('--budget-ms', type=float, default=3)
    ap.add_argument('--iters', type=int, default=400)
    args = ap.parse_args()

    t = time.time()
    ra, la, ea = run(resolve(args.a), args)
    ma = summary('A ' + args.a, ra, la, ea)
    if args.b and args.b != 'none':
        rb, lb, eb = run(resolve(args.b), args)
        mb = summary('B ' + args.b, rb, lb, eb)
        d = [ra[i][0] - rb[i][0] for i in ra]
        md = sum(d) / float(len(d))
        sd = math.sqrt(sum((x - md) ** 2 for x in d) / max(1, len(d) - 1))
        print('A-B paired diff %.3f ±%.3f pts/game (95%% CI)%s' % (
            md, 1.96 * sd / math.sqrt(len(d)), '  -> A better' if md - 1.96 * sd / math.sqrt(len(d)) > 0 else ''))
    print('%.0fs' % (time.time() - t))


if __name__ == '__main__':
    main()
