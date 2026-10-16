"""Precomputed preflop tables (bot/data/preflop.json, built by tools/gen_tables.py)."""
import json
import os
from functools import lru_cache

from .cards import class_combos, chen

COMBOS = [class_combos(i) for i in range(169)]
WEIGHTS = [len(c) for c in COMBOS]

_path = os.path.join(os.path.dirname(__file__), 'data', 'preflop.json')
try:
    with open(_path) as _f:
        _D = json.load(_f)
    ORDER, T1, HU = _D['order'], _D['t1'], _D['hu']
    LOADED = True
except Exception:  # missing table must never take the service down: Chen-based stand-in
    _ch = [chen(*COMBOS[i][0]) for i in range(169)]
    ORDER = sorted(range(169), key=lambda i: -_ch[i])
    T1 = [[min(0.85, 0.30 + 0.027 * _ch[i]) ** (1 + 0.6 * n) for n in range(5)] for i in range(169)]
    HU = None
    LOADED = False

# combo-weighted percentile (midpoint) of each class, 0 = best
PCT = [0.0] * 169
ORDERED_COMBOS = []
_acc = 0
for _i in ORDER:
    PCT[_i] = (_acc + WEIGHTS[_i] / 2.0) / 1326.0
    _acc += WEIGHTS[_i]
    ORDERED_COMBOS.extend(COMBOS[_i])


def range_combos(pct):
    n = max(6, min(1326, int(round(pct * 1326))))
    return ORDERED_COMBOS[:n]


@lru_cache(maxsize=8192)
def _eq_vs_top(cls, pct100):
    if HU is None:
        return max(0.2, min(0.85, T1[cls][0] + (0.5 - T1[cls][0]) * (1 - pct100 / 100.0) * 0.6))
    rep = COMBOS[cls][0]
    budget = pct100 / 100.0 * 1326
    num = den = 0.0
    for v in ORDER:
        if budget <= 0:
            break
        w = min(1.0, budget / WEIGHTS[v])
        budget -= WEIGHTS[v]
        avail = sum(1 for c in COMBOS[v] if rep[0] not in c and rep[1] not in c)
        num += HU[cls][v] * w * avail
        den += w * avail
    return num / den if den else 0.5


def eq_hu(cls, pct):
    """Heads-up equity of class vs the top pct (0..1) of hands."""
    return _eq_vs_top(cls, max(1, min(100, int(round(pct * 100)))))


def eq_vs_random(cls, nopp):
    return T1[cls][max(1, min(5, nopp)) - 1]
