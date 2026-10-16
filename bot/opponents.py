"""Per-opponent model keyed by name. Correct with empty memory; decays on redeploy."""
import threading
import time

from . import config, tables
from .cards import parse_many, hand_class

_lock = threading.Lock()
STATS = {}
HANDS = {}
LOG_FED = set()   # game ids whose card-based stats come from bot/livelog.py
COUNTS = ('hands', 'allin', 'vpip', 'aggr', 'fold', 'fts_n', 'fts_f', 'big_n', 'big_weak')
_last_cleanup = [0.0]


def _new():
    s = dict((k, 0.0) for k in COUNTS)
    s['ftb_n'] = [0.0] * 4
    s['ftb_f'] = [0.0] * 4
    s['shove_pcts'] = []
    s['version'] = None
    return s


def _stat(name):
    s = STATS.get(name)
    if s is None:
        s = STATS[name] = _new()
    return s


def _rate(k, n, prior):
    m = config.min_samples
    return (k + prior * m) / (n + m)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Opp(object):
    def __init__(self, s):
        self.s = s
        self.n = s['hands']

    @property
    def allin_rate(self):
        return _rate(self.s['allin'], self.n, config.prior_shove_range)

    @property
    def shove_range(self):
        r = self.allin_rate
        p = sorted(self.s['shove_pcts'])
        if len(p) >= 3:
            r = max(r, p[int(0.9 * (len(p) - 1))])
        return _clamp(r, 0.04, 1.0)

    @property
    def call_range(self):
        fold = _rate(self.s['fts_f'], self.s['fts_n'], 1 - config.prior_call_range_vs_shove)
        return _clamp(1 - fold, 0.05, 1.0)

    @property
    def aggr_range(self):
        return _clamp(_rate(self.s['aggr'], self.n, config.prior_aggr_range), 0.05, 1.0)

    @property
    def vpip_range(self):
        return _clamp(_rate(self.s['vpip'], self.n, 0.45), 0.10, 1.0)

    def fold_to_bet(self, bucket):
        n = self.s['ftb_n'][bucket]
        return _rate(self.s['ftb_f'][bucket], n, config.prior_fold_to_bet), n

    @property
    def bluff_p(self):
        """Share of big bets/shoves shown down with weak hands (prior 0.3)."""
        return _rate(self.s['big_weak'], self.s['big_n'], 0.3)

    @property
    def archetype(self):
        if self.n < config.min_samples:
            return 'unknown'
        s = self.s
        if s['allin'] / self.n >= 0.5:
            return 'maniac'
        if s['big_n'] >= 4 and s['big_weak'] / s['big_n'] >= 0.5:
            return 'maniac'
        if s['fold'] / self.n >= 0.85 and s['vpip'] / self.n <= 0.1:
            return 'folder'
        if (s['fts_n'] >= 4 and self.call_range >= 0.7) or (s['vpip'] / self.n >= 0.6 and s['aggr'] / self.n <= 0.25):
            return 'station'
        if s['vpip'] / self.n <= 0.15:
            return 'nit'
        return 'regular'


def get(name):
    with _lock:
        return Opp(_stat(name))


def _decay(s):
    d = config.version_change_decay
    for k in COUNTS:
        s[k] *= d
    s['ftb_n'] = [x * d for x in s['ftb_n']]
    s['ftb_f'] = [x * d for x in s['ftb_f']]
    s['shove_pcts'] = []


def observe(gs, final=False):
    gid = str(gs.get('game_id', ''))
    rnd = gs.get('round', 0)
    key = (gid, rnd)
    me = gs.get('in_action')
    now = time.time()
    board = bool(gs.get('community_cards'))
    bb = 2 * max(1, int(gs.get('small_blind') or 1))
    with _lock:
        tr = HANDS.get(key)
        if tr is None:
            for k in [k for k in HANDS if k[0] == gid and k[1] != rnd]:
                _finalize(k, False)
            tr = HANDS[key] = {'t': now, 'bb': bb, 'p': {}, 'ours': []}
        if not board:
            tr['pf_level'] = max(tr.get('pf_level', 0), int(gs.get('current_buy_in') or 0))
        elif 'pf_level' not in tr and me is not None and not final:
            tr['pf_level'] = int(gs['players'][me].get('bet') or 0)  # our bet = level before this street's action
        for i, p in enumerate(gs.get('players') or []):
            if i == me or p.get('status') == 'out':
                continue
            name = p.get('name')
            s = _stat(name)
            ver = p.get('version')
            if s['version'] is not None and ver != s['version']:
                _decay(s)
            s['version'] = ver
            pt = tr['p'].setdefault(name, {'max_bet': 0, 'allin': False, 'folded': False, 'cards': None})
            bet = int(p.get('bet') or 0)
            pt['max_bet'] = max(pt['max_bet'], bet)
            if p.get('status') == 'active' and int(p.get('stack') or 0) == 0 and bet > 0:
                pt['allin'] = True
                if not board:
                    pt['pf_allin'] = True
            pt['folded'] = p.get('status') == 'folded'
            hc = p.get('hole_cards') or []
            if len(hc) == 2:
                pt['cards'] = hc
        if final:
            _finalize(key, True)
        if now - _last_cleanup[0] > 60:
            _last_cleanup[0] = now
            for k in [k for k, t in HANDS.items() if now - t['t'] > config.state_ttl_s]:
                _finalize(k, False)


def pf_level(gid, rnd):
    tr = HANDS.get((gid, rnd))
    return tr.get('pf_level') if tr else None


def _bucket(frac):
    return 0 if frac <= 0.4 else 1 if frac <= 0.8 else 2 if frac <= 1.5 else 3


def record_ours(v, amount):
    """Remember our aggressive actions so showdown can score fold-to-shove / fold-to-bet."""
    if amount <= v.call:
        return
    shove = amount >= v.my_stack
    frac = (amount - v.call) / float(max(v.pot, 1))
    with _lock:
        tr = HANDS.get((v.game_id, v.raw.get('round', 0)))
        if tr is not None:
            tr['ours'].append({'shove': shove, 'bucket': 3 if shove else _bucket(frac),
                               'opps': [p.get('name') for p in v.opps_live]})


def _finalize(key, complete):
    tr = HANDS.pop(key, None)
    if tr is None:
        return
    bb = tr['bb']
    for name, pt in tr['p'].items():
        s = _stat(name)
        s['hands'] += 1
        s['allin'] += 1 if pt['allin'] else 0
        s['vpip'] += 1 if pt['max_bet'] > bb else 0
        s['aggr'] += 1 if (pt['max_bet'] > 2 * bb or pt['allin']) else 0
        s['fold'] += 1 if pt['folded'] else 0
        if not complete:
            continue
        last = None
        for a in tr['ours']:
            if name in a['opps']:
                last = a
        if last is not None:
            f = 1 if pt['folded'] else 0
            if last['shove']:
                s['fts_n'] += 1
                s['fts_f'] += f
            s['ftb_n'][last['bucket']] += 1
            s['ftb_f'][last['bucket']] += f
        if key[0] in LOG_FED:
            continue  # livelog counts big bets/shoves with every hand's cards, not just showdowns
        if pt['cards'] and (pt['allin'] or pt['max_bet'] > 4 * bb):
            try:
                c = parse_many(pt['cards'])
                pct = tables.PCT[hand_class(c[0], c[1])]
            except Exception:
                continue
            s['big_n'] += 1
            s['big_weak'] += 1 if pct > 0.5 else 0
            if pt.get('pf_allin'):
                s['shove_pcts'] = (s['shove_pcts'] + [pct])[-30:]
