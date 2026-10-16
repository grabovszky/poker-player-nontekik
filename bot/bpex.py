"""bpex preflop ranges, computed from its source (Chen-score thresholds), for exact equity.

Unopened, bpex shoves at <= 15bb effective when chen + bonus >= threshold; deeper it raises to ~4-4.5bb
with chen 8..11 ("medium") and pot + 3bb (5-5.5bb total) with chen >= 12 ("big"). bonus: +3 heads-up,
+1 three-handed. Facing our non-all-in re-raise after it opened deep (> 25bb) it assumes our top 3%
and folds unless its equity beats pot odds + 0.04 (about QQ+ / AK).
"""
import math
from functools import lru_cache

from . import tables
from .cards import class_combos, class_name

NAME = 'bpex'
MEDIUM_MAX_BB = 4.75   # its medium open is <= 4.5bb total, big open >= 5bb


def _points(v):
    return 10 if v == 14 else 8 if v == 13 else 7 if v == 12 else 6 if v == 11 else v / 2.0


def chen(cls):
    """bpex's Chen score for a hand class (rank values 2..14)."""
    a, b = class_combos(cls)[0]
    hi, lo = max(a >> 2, b >> 2) + 2, min(a >> 2, b >> 2) + 2
    s = _points(hi)
    if hi == lo:
        return int(math.ceil(max(5, s * 2)))
    gap = hi - lo - 1
    if (a & 3) == (b & 3):
        s += 2
    s -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and hi < 12:
        s += 1
    return int(math.ceil(s))


CHEN = [chen(i) for i in range(169)]
RERAISE = tuple(i for i in range(169) if class_name(i) in ('AA', 'KK', 'QQ', 'AKs', 'AKo'))  # its 4-bet / re-shove


def bonus(players_left):
    return 3 if players_left <= 2 else 1 if players_left == 3 else 0


def shove_at(eff_bb):
    return -99 if eff_bb <= 3 else 5 if eff_bb <= 6 else 6 if eff_bb <= 10 else 7


@lru_cache(maxsize=256)
def _classes(lo, hi):
    return tuple(i for i in range(169) if lo <= CHEN[i] < hi)


def shove_range(eff_bb, players_left):
    return _classes(shove_at(eff_bb) - bonus(players_left), 99)


def open_range(big, players_left):
    b = bonus(players_left)
    return _classes(12 - b, 99) if big else _classes(8 - b, 12 - b)


@lru_cache(maxsize=4096)
def eq(cls, classes):
    """Our class vs a set of their classes, combo-weighted with card removal."""
    if not classes:
        return 0.5
    rep = class_combos(cls)[0]
    num = den = 0.0
    for v in classes:
        n = sum(1 for c in class_combos(v) if rep[0] not in c and rep[1] not in c)
        num += tables.HU[cls][v] * n
        den += n
    return num / den if den else 0.5


def spot(v):
    """('shove' | 'medium' | 'big', classes, its effective bb) when bpex is the lone preflop raiser, else None."""
    if tables.HU is None or v.street:
        return None
    raisers = [p for p in v.opps if int(p.get('bet') or 0) > v.bb]
    if len(raisers) != 1 or raisers[0].get('name') != NAME:
        return None
    b = raisers[0]
    tot = lambda p: int(p.get('stack') or 0) + int(p.get('bet') or 0)  # noqa: E731
    others = [tot(p) for i, p in enumerate(v.players) if i in v.alive and p is not b]
    eff = min(tot(b), max(others or [0])) / float(v.bb)
    left = v.n_alive
    if v.my_bet > v.bb:
        # re-raise of our deep 3-bet: AA-QQ / AK. Short, it re-shoves our opens far wider (vs our open rate).
        return ('reraise', RERAISE, eff) if eff > 25 else None
    if int(b.get('stack') or 0) == 0 and eff <= 15:
        return 'shove', shove_range(eff, left), eff
    if int(b.get('stack') or 0) > 0 and eff > 15:
        big = int(b.get('bet') or 0) > MEDIUM_MAX_BB * v.bb
        return ('big' if big else 'medium'), open_range(big, left), eff
    return None
