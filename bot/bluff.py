"""Bluff / semi-bluff sizing: heads-up only, data-driven, never vs stations or maniacs."""
import random

from . import config

SIZES = ((0.5, 1), (0.75, 1), (1.0, 2))


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
