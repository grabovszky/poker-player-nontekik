"""ICM (Malmuth-Harville, payouts 5/3), per-game timers, 3-minute cutoff mode."""
import threading
import time

from . import config

now = time.time  # the simulator may swap this
_lock = threading.Lock()
FIRST_SEEN = {}
THINK = {}


def touch(gid):
    t = now()
    with _lock:
        FIRST_SEEN.setdefault(gid, t)
        if len(FIRST_SEEN) > 200:
            for k in [k for k, v in FIRST_SEEN.items() if t - v > config.state_ttl_s]:
                FIRST_SEEN.pop(k, None)
                THINK.pop(k, None)


def elapsed(gid):
    return now() - FIRST_SEEN.get(gid, now())


def add_think(gid, sec):
    with _lock:
        THINK[gid] = THINK.get(gid, 0.0) + sec


def table_only(gid):
    return THINK.get(gid, 0.0) > config.game_time_soft_cap_s


def icm(stacks, payouts=(5.0, 3.0)):
    T = float(sum(stacks))
    ev = [0.0] * len(stacks)
    if T <= 0:
        return ev
    for i, si in enumerate(stacks):
        if si <= 0:
            continue
        p2 = 0.0
        for j, sj in enumerate(stacks):
            if j != i and sj > 0 and T - sj > 0:
                p2 += (sj / T) * (si / (T - sj))
        ev[i] = payouts[0] * si / T + payouts[1] * p2
    return ev


def _points(st, me):
    alive = [i for i in st if st[i] > 0]
    if st.get(me, 0) <= 0:
        return 3.0 if len(alive) == 1 else 0.0
    ids = list(alive)
    ev = icm([st[i] for i in ids])
    return ev[ids.index(me)]


def icm_allin(v, vil_idx, our_add, vil_add, fold_winner_idx):
    """Points for outcomes: fold, everyone folds, we win, we lose."""
    base = dict((i, int(v.players[i].get('stack') or 0)) for i in v.alive)
    me = v.me_idx
    pot = v.pot
    fold = dict(base)
    fold[fold_winner_idx] = fold.get(fold_winner_idx, 0) + pot
    allfold = dict(base)
    allfold[me] += pot
    win = dict(base)
    win[me] += pot + vil_add
    win[vil_idx] = win.get(vil_idx, 0) - vil_add
    lose = dict(base)
    lose[me] -= our_add
    lose[vil_idx] = lose.get(vil_idx, 0) + pot + our_add
    return (_points(fold, me), _points(allfold, me), _points(win, me), _points(lose, me))


def variance_mode(v):
    """-1 protect lead, 0 normal, +1 gamble (only once the 3-minute cutoff nears)."""
    if elapsed(v.game_id) < config.cutoff_mode_s:
        return 0
    tot = sorted(((int(p.get('stack') or 0) + int(p.get('bet') or 0), i) for i, p in enumerate(v.players)
                  if p.get('status') != 'out'), reverse=True)
    if len(tot) < 2:
        return 0
    rank = [i for _, i in tot].index(v.me_idx)
    ours = tot[rank][0]
    if rank == 0:
        return -1 if ours >= 1.3 * tot[1][0] else 0
    if rank == 1:
        return 1 if tot[0][0] <= 2 * ours else -1
    return 1
