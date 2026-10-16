"""Seed opponent stats from bot/data/opp_priors.json (tools/fit_opps.py) on first sight.

Capped at ~60 hands so live play still moves it.
"""
import json
import os

from . import opponents
from .exploits import k

PATH = os.path.join(os.path.dirname(__file__), 'data', 'opp_priors.json')
_P = {}
_new_stat = opponents._stat


def load(path=PATH):
    try:
        with open(path) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return 0
    _P.clear()
    _P.update(data)
    return len(data)


def _seed(s, p):
    for key in opponents.COUNTS:
        s[key] = float(p.get(key, 0.0))
    s['r3_n'], s['r3_c'] = float(p.get('r3_n', 0.0)), float(p.get('r3_c', 0.0))
    s['shove_pcts'] = list(p.get('shove_pcts') or [])


def _stat(name):
    s = opponents.STATS.get(name)
    if s is None:
        s = _new_stat(name)
        p = _P.get(str(k({'name': name}))) or _P.get(str(name))
        if p:
            _seed(s, p)
    return s


opponents._stat = _stat
load()
