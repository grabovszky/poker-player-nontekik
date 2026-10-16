"""Live opponent reads from the running game's own log.

Lean Poker publishes each finished hand as /log?fragment=<round> while the game is still running,
with every player's hole cards (folded ones too). One daemon thread per game pulls them in order and
feeds the card-dependent stats into opponents.STATS: shove ranges, bluff share of big bets, fold to
others' shoves, raiser vs 3-bet shove. betRequest never waits on it; if the API is down we keep priors.
"""
import gzip
import json
import re
import threading
import time
import urllib.request

from . import opponents, tables
from .cards import parse_many, hand_class

URL = 'https://live.leanpoker.org/api/tournament/%s/game/%s/log?fragment=%d'
GAME_ID = re.compile(r'^[0-9a-f]{24}$')   # real ids only, so the simulator stays offline
KIND = re.compile(r'\(([\w ]+)\)')
POLL_S = 1.5
IDLE_S = 120                               # stop once the game hasn't asked us for this long

_lock = threading.Lock()
_games = {}                                # game_id -> last bet_request time


def watch(gs, me):
    tid, gid = str(gs.get('tournament_id') or ''), str(gs.get('game_id') or '')
    if not (GAME_ID.match(tid) and GAME_ID.match(gid)):
        return
    with _lock:
        new = gid not in _games
        _games[gid] = time.time()
    if new:
        threading.Thread(target=_run, args=(tid, gid, me, int(gs.get('round') or 0)), daemon=True).start()


def _get(url):
    req = urllib.request.Request(url, headers={'Accept-Encoding': 'gzip', 'User-Agent': 'nontekik-livelog'})
    with urllib.request.urlopen(req, timeout=5) as r:
        d = r.read()
    return json.loads(gzip.decompress(d) if d[:2] == b'\x1f\x8b' else d)


def _run(tid, gid, me, i):
    # hands before `i` were already counted by opponents.observe(); start at the hand in progress
    try:
        while time.time() - _games.get(gid, 0) < IDLE_S:
            try:
                frag = _get(URL % (tid, gid, i))
            except Exception:
                frag = None                # 404 = hand not finished yet
            if frag:
                feed(frag, me, gid)
                i += 1
            else:
                time.sleep(POLL_S)
    finally:
        with _lock:
            _games.pop(gid, None)


def _pct(hole):
    c = parse_many(hole)
    return tables.PCT[hand_class(c[0], c[1])]


def feed(frag, me, gid=None):
    """Count one hand's log entries (same rules as tools/fit_opps.py) into opponents.STATS."""
    d = {}                                 # name -> Counter-like dict of deltas
    shoves = {}                            # name -> pcts of preflop shoves
    prev, nbets, opener, shoved, shovers = None, 0, None, False, set()
    mx, allin, bb = {}, set(), 2
    for e in frag:
        gs = e.get('game_state') or {}
        if e.get('type') == 'bet' and prev is not None and 'on_turn' in e:
            k = e['on_turn']
            p, pp = gs['players'][k], prev['players'][k]
            name, street = p['name'], len(prev.get('community_cards') or [])
            bb = 2 * int(prev.get('small_blind') or 1)
            nbets += 1
            mx[name] = max(mx.get(name, 0), int(p.get('bet') or 0))
            if p.get('stack') == 0:
                allin.add(name)
            if street == 0 and nbets > 2 and len(p.get('hole_cards') or []) == 2:
                m = KIND.search(e.get('message', ''))
                kind = m.group(1) if m else '?'
                amt = p['bet'] - pp['bet']
                call = max(0, prev['current_buy_in'] - pp['bet'])
                is_allin = p['stack'] == 0
                vol = kind in ('raise', 'allin') and amt > call
                s = d.setdefault(name, {})
                if opener and shoved and name == opener:
                    s['r3_n'] = s.get('r3_n', 0) + 1
                    s['r3_c'] = s.get('r3_c', 0) + (kind != 'fold')
                    opener = ''
                if opener is None and vol and not is_allin:
                    opener = name
                elif opener and name != opener and is_allin and amt > call:
                    shoved = True
                if call > 0 and shovers and me not in shovers:  # our own shoves are counted by observe()
                    s['fts_n'] = s.get('fts_n', 0) + 1
                    s['fts_f'] = s.get('fts_f', 0) + (kind == 'fold')
                if is_allin and amt > call:
                    shovers.add(name)
                    shoves.setdefault(name, []).append(_pct(p['hole_cards']))
        prev = gs
    for p in (prev or {}).get('players', []):
        name, hole = p.get('name'), p.get('hole_cards') or []
        if len(hole) == 2 and (name in allin or mx.get(name, 0) > 4 * bb):
            s = d.setdefault(name, {})
            s['big_n'] = s.get('big_n', 0) + 1
            s['big_weak'] = s.get('big_weak', 0) + (_pct(hole) > 0.5)
    with opponents._lock:
        if gid:
            opponents.LOG_FED.add(gid)
        for name, delta in d.items():
            if name == me:
                continue
            st = opponents._stat(name)
            for key, v in delta.items():
                st[key] = st.get(key, 0.0) + v
        for name, pcts in shoves.items():
            if name != me:
                st = opponents._stat(name)
                st['shove_pcts'] = (st['shove_pcts'] + pcts)[-30:]
