"""Range-weighted Monte Carlo equity, deadline-bounded; exact on heads-up river."""
import random
import time

from .evaluator import RK, SK, NONFLUSH, flush_value
from . import tables


def _value(cards):
    rk = 0
    sk = 0
    for c in cards:
        rk += RK[c]
        sk += SK[c]
    if (sk + 0x3333) & 0x8888:
        return flush_value(cards, sk)
    return NONFLUSH[rk]


def equity(hero, board, opp_ranges, deadline, max_iters, seed=None):
    """opp_ranges: list of pct (0..1) or combo lists (duplicates = weight). Returns (equity, iterations)."""
    if not opp_ranges:
        return 1.0, 0
    dead = 0
    for c in hero + board:
        dead |= 1 << c
    ranges = []
    for p in opp_ranges:
        src = p if isinstance(p, list) else tables.range_combos(p)
        live = [cb for cb in src if not (dead >> cb[0] & 1 or dead >> cb[1] & 1)]
        if not live:
            live = [cb for cb in tables.ORDERED_COMBOS if not (dead >> cb[0] & 1 or dead >> cb[1] & 1)]
        ranges.append(live)
    need = 5 - len(board)

    if need == 0 and len(ranges) == 1:
        a = _value(hero + board)
        win = 0.0
        for cb in ranges[0]:
            o = _value([cb[0], cb[1]] + board)
            win += 1.0 if a > o else (0.5 if a == o else 0.0)
        return win / len(ranges[0]), len(ranges[0])

    rng = random.Random(seed).random
    win = 0.0
    n = 0
    now = time.perf_counter
    while n < max_iters:
        if n & 31 == 0 and now() > deadline:
            break
        used = dead
        hands = []
        ok = True
        for live in ranges:
            for _ in range(12):
                cb = live[int(rng() * len(live))]
                if not (used >> cb[0] & 1 or used >> cb[1] & 1):
                    used |= (1 << cb[0]) | (1 << cb[1])
                    hands.append(cb)
                    break
            else:
                ok = False
                break
        if not ok:
            n += 1
            continue
        b = list(board)
        while len(b) < 5:
            c = int(rng() * 52)
            if not used >> c & 1:
                used |= 1 << c
                b.append(c)
        a = _value(hero + b)
        best = -1
        ties = 0
        for cb in hands:
            o = _value([cb[0], cb[1]] + b)
            if o > best:
                best, ties = o, 1
            elif o == best:
                ties += 1
        if a > best:
            win += 1.0
        elif a == best:
            win += 1.0 / (ties + 1)
        n += 1
    return (win / n if n else 0.5), n
