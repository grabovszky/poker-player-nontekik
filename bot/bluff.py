"""Bluff / semi-bluff sizing: heads-up only, data-driven, never vs stations or maniacs."""
import random

from . import config

SIZES = ((0.5, 1), (0.75, 1), (1.0, 2))

# From their public source (2026-10-16): all three read our bet size as hand strength and fold
# everything but strong made hands to big bets (bpex even more so to overbets). Pot fraction to bet.
BIG_BET_FOLDERS = {'bpex': 2.0, 'megistekik': 1.0, 'nontechyk': 1.0}  # x EXPLOIT_SIZE; bpex: >pot (live: folds 84-100% to >0.8 pot, widens calls vs <=pot)


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


EXPLOIT_MAX_EQ = 0.35       # only turn hands with no showdown value into bluffs
EXPLOIT_SIZE = 0.6          # scales BIG_BET_FOLDERS pot fractions (sim vs their real code: 0.6 > 1.0)
EXPLOIT_STREETS = (3, 4, 5)
_fired = {}                 # (game_id, round) -> True once we bluffed this hand: never barrel


def exploit(v, ctx, eq, opp):
    """Heads-up big-bet bluff against a known big-bet folder; off once their measured fold rate says no."""
    frac = BIG_BET_FOLDERS.get(opp.get('name'))
    key = (v.game_id, v.round)
    if frac is None or int(opp.get('stack') or 0) == 0 or eq > EXPLOIT_MAX_EQ or v.street not in EXPLOIT_STREETS \
            or key in _fired:
        return None
    f, n = ctx.model(opp.get('name')).fold_to_bet(2)
    if n >= config.min_samples and f < 0.45:
        return None
    if len(_fired) > 5000:
        _fired.clear()
    _fired[key] = True
    b = int(frac * EXPLOIT_SIZE * max(v.pot, 1))
    return v.my_stack if b >= 0.6 * v.my_stack else b
