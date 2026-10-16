"""Orchestration: parse -> observe -> decide intent -> legal amount -> log."""
import random
import time

from . import config, opponents, tournament, preflop, postflop, log, livelog, exploits
from .actions import CHECK, legal_amount
from .state import View
from .cards import to_str

_rng = random.SystemRandom()


class Ctx(object):
    def __init__(self, v, t0):
        self.model = opponents.get
        self.deadline = t0 + config.decision_budget_ms / 1000.0
        self.table_only = tournament.table_only(v.game_id)
        self.icm = v.n_alive >= 3
        self.var = tournament.variance_mode(v)
        self.seed = _rng.getrandbits(32)


def bet_request(gs, t0):
    v = View(gs)
    tournament.touch(v.game_id)
    try:
        opponents.observe(gs)
    except Exception:
        log.warn('observe failed', v.game_id)
    try:
        livelog.watch(gs, v.name)
    except Exception:
        log.warn('livelog watch failed', v.game_id)
    ctx = Ctx(v, t0)
    if len(v.hole) != 2:
        intent, reason, info = CHECK, 'no_hole_cards', {}
    elif not v.opps:
        intent, reason, info = CHECK, 'walk', {}
    elif v.street == 0:
        x = exploits.preflop(v)
        if x:
            intent, reason, info = x[0], x[1], {}
        else:
            intent, reason, info = preflop.decide(v, ctx)
    else:
        intent, reason, info = postflop.decide(v, ctx)
    amt = legal_amount(intent, v)
    exploits.note(v, amt)
    try:
        opponents.record_ours(v, amt)
    except Exception:
        log.warn('record_ours failed', v.game_id)
    ms = (time.perf_counter() - t0) * 1000.0
    tournament.add_think(v.game_id, ms / 1000.0)
    rec = {'game_id': v.game_id, 'round': v.round, 'street': v.street,
           'hand': ''.join(to_str(c) for c in v.hole), 'board': ''.join(to_str(c) for c in v.board),
           'n_opps': len(v.opps), 'stack_bb': round(v.stack_bb, 1), 'call': v.call, 'pot': v.pot,
           'icm_mode': ctx.icm, 'var': ctx.var, 'table_only': ctx.table_only,
           'archetypes_vs': [ctx.model(p.get('name')).archetype for p in v.opps],
           'intent': intent[0], 'amount': amt, 'reason_code': reason, 'ms': round(ms, 1)}
    rec.update(info)
    log.decision(rec)
    return amt


def showdown(gs):
    opponents.observe(gs, final=True)
