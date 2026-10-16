"""Check bot/livelog.py against tools/fit_opps.py on a real finished game (needs network).

  python tools/test_livelog.py
Splits the full game log into per-hand fragments (what a running game serves) and asserts
livelog.feed() measures the same shoves and raiser-vs-3bet-shove counts as the offline fitter.
"""
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from fetch_logs import get, API  # noqa: E402
import fit_opps  # noqa: E402
from bot import opponents, livelog  # noqa: E402

TID = '6ad1f731e9d3abe3c2580703'
US = 'nontekik'

games = [g for g in get('%s/tournament/%s/game' % (API, TID)) if g['status'] in ('done', 'finished')]
log = get('%s/tournament/%s/game/%s/log' % (API, TID, games[-1]['_id']))

frags, cur = [], None
for e in log:
    if e.get('type') is None:
        cur = []
        frags.append(cur)
    if cur is not None:
        cur.append(e)

opponents.STATS.clear()
for f in frags:
    livelog.feed(f, US)

path = os.path.join(tempfile.mkdtemp(), 'game.json')
json.dump(log, open(path, 'w'))
A = fit_opps.fit([path])

for name, acc in A.items():
    if name == US:
        continue
    s = opponents.STATS.get(name, {})
    want = sorted(acc.shove_pcts)[-30:] if len(acc.shove_pcts) <= 30 else None
    if want is not None:
        assert sorted(s.get('shove_pcts', [])) == want, (name, s.get('shove_pcts'), want)
    assert s.get('r3_n', 0) == acc.c['r3_n'] and s.get('r3_c', 0) == acc.c['r3_c'], (name, s, acc.c)
    assert s.get('fts_n', 0) <= acc.c['fts_n']  # we skip hands where we were the shover
    print('%-12s shoves=%-3d r3=%d/%d fts=%d/%d big_weak=%d/%d' % (
        name, len(s.get('shove_pcts', [])), s.get('r3_c', 0), s.get('r3_n', 0),
        s.get('fts_f', 0), s.get('fts_n', 0), s.get('big_weak', 0), s.get('big_n', 0)))
print('ok: %d hands from game %s' % (len(frags), games[-1]['_id']))
