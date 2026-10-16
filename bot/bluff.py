"""Bluff / semi-bluff sizing: heads-up only, data-driven, never vs stations or maniacs."""
import random

from . import config
from .exploits import k

SIZES = ((0.5, 1), (0.75, 1), (1.0, 2))

_W = {30710: 2.0, 76900: 1.0, 75655: 1.0}


def has_draw(hole, board):
    cards = hole + board
    for s in range(4):
        suited = [c for c in cards if c & 3 == s]
        if len(suited) == 4 and any(c & 3 == s for c in hole):
            return True
    ranks = set(c >> 2 for c in cards)
    if 12 in ranks:
        ranks.add(-1)
    hole_r = set(c >> 2 for c in hole)
    for lo in range(-1, 9):
        run = set(range(lo, lo + 4))
        if run <= ranks and run & hole_r:
            return True
    return False


def decide(v, ctx, eq, opp):
    """Returns chips to bet, or None to check."""
    m = ctx.model(opp.get('name'))
    if m.archetype in ('station', 'maniac'):
        return None
    P, S = float(max(v.pot, 1)), v.my_stack
    draw = v.street < 5 and has_draw(v.hole, v.board)
    semi = draw and 0.25 <= eq <= 0.55
    best, best_ev = None, eq * P
    for frac, bucket in SIZES:
        B = int(frac * P)
        if B <= 0 or B >= S:
            continue
        f, n = m.fold_to_bet(bucket)
        alpha = B / (P + B)
        if n < config.min_samples:
            if not semi:
                continue
        elif f < alpha + config.bluff_fold_margin and not semi:
            continue
        ev = f * P + (1 - f) * (eq * (P + 2 * B) - B)
        if ev > best_ev:
            best, best_ev = B, ev
    if best is None:
        return None
    if random.Random(ctx.seed).random() > 0.75:
        return None
    return best


M = 0.35
Z = 0.6
ST = (3, 4, 5)
_f = {}


def exploit(v, ctx, eq, opp):
    kk = k(opp)
    frac = _W.get(kk)
    key = (v.game_id, v.round)
    if frac is None or int(opp.get('stack') or 0) == 0 or eq > M or v.street not in ST or key in _f:
        return None
    f, n = ctx.model(opp.get('name')).fold_to_bet(2)
    if n >= config.min_samples and f < 0.45:
        return None
    if len(_f) > 5000:
        _f.clear()
    _f[key] = True
    b = int(frac * Z * max(v.pot, 1))
    if kk == 76900:
        b = max(int(0.75 * v.pot), int(opp.get('stack') or 0) // 4 + 1)
        if b > 1.2 * v.pot:
            _f.pop(key, None)
            return None
    return v.my_stack if b >= 0.6 * v.my_stack else b


S2 = True


def stab(v, opp):
    if not S2 or k(opp) != 75655 or v.call or int(opp.get('stack') or 0) == 0:
        return None
    if any(p is opp for p in v.behind):
        return None
    b = int(0.75 * max(v.pot, 1))
    return v.my_stack if b >= 0.6 * v.my_stack else b
