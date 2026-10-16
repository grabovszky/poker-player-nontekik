"""Seed the opponent model from live-log priors (bot/data/opp_priors.json, built by tools/fit_opps.py).

Each redeploy wipes in-memory stats; the seed is capped at ~60 hands so live play still moves it,
and opponents.observe() decays it as usual when an opponent's version string changes.
"""
import json
import os

from . import opponents

PATH = os.path.join(os.path.dirname(__file__), 'data', 'opp_priors.json')


def load(path=PATH):
    try:
        with open(path) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return 0
    with opponents._lock:
        for name, p in data.items():
            if not p or name in opponents.STATS:
                continue
            s = opponents._new()
            for k in opponents.COUNTS:
                s[k] = float(p.get(k, 0.0))
            s['shove_pcts'] = list(p.get('shove_pcts') or [])
            s['version'] = p.get('version')
            opponents.STATS[name] = s
    return len(data)


load()
