"""Generic, data-driven bluffing (heads-up only). Opponent-specific bluffs live in opponent_map.py.

A pure bluff of size B into pot P breaks even when the opponent folds alpha = B / (P + B) of the time.
We only bluff when the opponent's measured fold rate at that size beats alpha by a margin, or with a
draw (semi-bluff), and never against calling stations or maniacs.
"""
import random

from . import config

# (pot fraction, fold-to-bet bucket in the opponent model)
SIZES = ((0.5, 1), (0.75, 1), (1.0, 2))


def has_draw(hole, board):
    """Flush draw or 4-to-a-straight that uses at least one hole card."""
    cards = hole + board
    for s in range(4):
        suited = [c for c in cards if c & 3 == s]
        if len(suited) == 4 and any(c & 3 == s for c in hole):
            return True
    ranks = set(c >> 2 for c in cards)
    if 12 in ranks:
        ranks.add(-1)   # ace plays low in A-2-3-4-5
    hole_r = set(c >> 2 for c in hole)
    for lo in range(-1, 9):
        run = set(range(lo, lo + 4))
        if run <= ranks and run & hole_r:
            return True
    return False


def decide(v, ctx, eq, opp):
    """Chips to bet as a bluff/semi-bluff, or None to check. Picks the size with the best EV."""
    m = ctx.model(opp.get('name'))
    if m.archetype in ('station', 'maniac'):
        return None
    P, S = float(max(v.pot, 1)), v.my_stack
    draw = v.street < 5 and has_draw(v.hole, v.board)
    semi = draw and 0.25 <= eq <= 0.55
    best, best_ev = None, eq * P            # checking keeps our equity share of the pot
    for frac, bucket in SIZES:
        B = int(frac * P)
        if B <= 0 or B >= S:
            continue
        f, n = m.fold_to_bet(bucket)
        alpha = B / (P + B)
        if n < config.min_samples:
            if not semi:
                continue                    # no data yet: only semi-bluff
        elif f < alpha + config.bluff_fold_margin and not semi:
            continue
        ev = f * P + (1 - f) * (eq * (P + 2 * B) - B)
        if ev > best_ev:
            best, best_ev = B, ev
    if best is None:
        return None
    if random.Random(ctx.seed).random() > 0.75:
        return None                         # mix: don't bluff every time it is +EV
    return best
