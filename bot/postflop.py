"""Postflop: equity vs ranges, SPR shove/fold, value bets, pot-odds calls, bluffs."""
import math

from . import config, equity, bluff
from .actions import FOLD, CHECK, CALL, ALL_IN, RAISE_TO
from .evaluator import evaluate, category

PROXY = {0: 0.25, 1: 0.50, 2: 0.68, 3: 0.78, 4: 0.85, 5: 0.88, 6: 0.93, 7: 0.97, 8: 0.99}


def _st(p):
    return int(p.get('stack') or 0)


def _bet(p):
    return int(p.get('bet') or 0)


def _range(ctx, p, v):
    m = ctx.model(p.get('name'))
    r = m.vpip_range
    if _st(p) == 0:
        r = min(r, m.shove_range)
    if _bet(p) >= v.pot * 0.5 and _bet(p) > v.my_bet:
        r *= 0.7
    return max(0.10, min(1.0, r))


def wet(board):
    suits = [c & 3 for c in board]
    if max(suits.count(s) for s in range(4)) >= 3:
        return True
    r = sorted(set(c >> 2 for c in board))
    return any(r[i + 2] - r[i] <= 4 for i in range(len(r) - 2))


def decide(v, ctx):
    opps = v.opps
    n = max(1, len(opps))
    info = {}
    if ctx.table_only:
        eq = PROXY[category(evaluate(v.hole + v.board))] - 0.05 * (n - 1)
        info['eq_se'] = None
    else:
        eq, it = equity.equity(v.hole, v.board, [_range(ctx, p, v) for p in opps], ctx.deadline,
                               config.mc_max_iters, ctx.seed)
        info['eq_se'] = round(math.sqrt(max(eq * (1 - eq), 1e-9) / max(it, 1)), 4)
        info['iters'] = it
    info['eq'] = round(eq, 3)
    S, pot, call = v.my_stack, v.pot, v.call
    eff = min(S, max([_st(p) for p in opps] or [S]))
    spr = eff / float(max(pot, 1))
    margin = config.call_margin_base + config.call_margin_per_extra_opp * (n - 1)
    margin += {-1: 0.04, 0: 0.0, 1: -0.03}[ctx.var]
    agg = max(opps, key=_bet) if opps else None
    arch = ctx.model(agg.get('name')).archetype if agg else 'unknown'
    if arch == 'maniac':
        margin -= 0.05
    elif arch == 'nit' and call > 0.5 * pot:
        margin += 0.05
    info.update({'spr': round(spr, 2), 'arch': arch})

    if call > 0:
        call_eff = min(call, S)
        pot_eff = sum(min(_bet(p), v.my_bet + S) for p in v.players)
        required = call_eff / float(pot_eff + call_eff)
        info['required'] = round(required, 3)
        agg_allin = agg is not None and _st(agg) == 0
        if spr <= config.low_spr_shove or call >= 0.5 * S:
            if eq >= required + margin:
                return (CALL if agg_allin or call >= S or not v.opps_live else ALL_IN), 'post_lowspr_in', info
            return FOLD, 'post_lowspr_fold', info
        if eq >= (config.raise_eq_hu if n == 1 else config.raise_eq_multi) and v.opps_live:
            size = call + max(v.min_raise, 2 * call)
            if size >= 0.5 * S:
                return ALL_IN, 'post_raise_allin', info
            return RAISE_TO(v.my_bet + size), 'post_raise', info
        if eq >= required + margin:
            return CALL, 'post_call', info
        return FOLD, 'post_fold', info

    thr = config.value_bet_eq_hu if n == 1 else config.value_bet_eq_multi
    if eq >= thr and v.opps_live:
        frac = 0.66
        if wet(v.board):
            frac = 0.75
        if arch == 'station':
            frac = 0.85
        size = max(v.bb, int(frac * pot))
        if spr <= config.low_spr_shove or size >= 0.5 * S:
            return ALL_IN, 'post_value_allin', info
        return RAISE_TO(v.my_bet + size), 'post_value', info
    if n == 1 and v.opps_live:
        b = bluff.decide(v, ctx, eq, opps[0])
        if b:
            return RAISE_TO(v.my_bet + b), 'post_bluff', info
    return CHECK, 'post_check', info
