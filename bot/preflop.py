"""Preflop: EV-based push/fold (Z1), raise-or-shove (Z2), standard opens (Z3)."""
from . import config, tables, equity, tournament, opponents, priors  # noqa: F401  (priors seeds the model)
from .actions import FOLD, CHECK, CALL, ALL_IN, RAISE_TO
from .cards import hand_class

OPEN_BY_BEHIND = {0: 0.50, 1: 0.45, 2: 0.32, 3: 0.25, 4: 0.20, 5: 0.16}
RESTEAL_MAX_PCT = 0.30  # live logs: trash re-shoves (73s, T3o, J2o) over opens got called by better


def _raiser_cont(p):
    """P(raiser calls our 3-bet shove): measured r3 counts (priors) else 0.35."""
    s = opponents.STATS.get(p.get('name')) or {}
    n, c = s.get('r3_n', 0.0), s.get('r3_c', 0.0)
    return max(0.08, min(0.9, (c + 0.35 * 5) / (n + 5)))


def _st(p):
    return int(p.get('stack') or 0)


def _bet(p):
    return int(p.get('bet') or 0)


def _var_margin(ctx):
    return {-1: 0.04, 0: 0.0, 1: -0.03}[ctx.var]


def shove_ev(v, ctx, cls, callers):
    """callers: [(player, call_range)]. Returns (ev_chips, ev_points_or_None, info)."""
    S, B, pot = v.my_stack, v.my_bet, v.pot
    callers = [(p, cr) for p, cr in callers if _st(p) > 0]
    if not callers:
        return pot, None, {'p_fold': 1.0}
    p_fold = 1.0
    for _, cr in callers:
        p_fold *= 1 - cr
    c, cr = max(callers, key=lambda x: (x[1], _st(x[0]) + _bet(x[0])))
    eq = tables.eq_hu(cls, cr)
    risk = max(0, min(S, _st(c) + _bet(c) - B))
    vil_add = max(0, min(_st(c), B + risk - _bet(c)))
    ev = p_fold * pot + (1 - p_fold) * (eq * (pot + risk + vil_add) - risk)
    info = {'p_fold': round(p_fold, 3), 'eq': round(eq, 3)}
    pts = None
    if ctx.icm:
        agg = max(v.opps, key=_bet) if v.opps else c
        f, af, w, l = tournament.icm_allin(v, v.idx_of(c), risk, vil_add, v.idx_of(agg))
        pts = (p_fold * af + (1 - p_fold) * (eq * w + (1 - eq) * l)) - f
        info['icm_d'] = round(pts, 4)
    return ev, pts, info


def _shove_ok(ev, pts, bb, ctx, alt=0.0):
    if pts is not None:
        return pts > {-1: 0.01, 0: 0.0, 1: -0.01}[ctx.var]
    return ev > alt + {-1: 0.5 * bb, 0: 0.0, 1: -0.5 * bb}[ctx.var]


def _range_of(ctx, p, bb):
    m = ctx.model(p.get('name'))
    if _st(p) == 0:
        return m.shove_range
    if _bet(p) > 2 * bb:
        return m.aggr_range
    return min(1.0, m.aggr_range * 2)


def _eq_vs(v, ctx, cls, ranges):
    if len(ranges) == 1:
        return tables.eq_hu(cls, ranges[0])
    if ctx.table_only:
        e = 1.0
        for r in ranges:
            e *= tables.eq_hu(cls, r)
        return e
    e, _ = equity.equity(v.hole, [], ranges, ctx.deadline, 4000, ctx.seed)
    return e


def decide(v, ctx):
    cls = hand_class(v.hole[0], v.hole[1])
    info = {'pct': round(tables.PCT[cls], 3)}
    if v.current_buy_in > v.bb:
        return _facing_raise(v, ctx, cls, info)
    return _unopened(v, ctx, cls, info)


def _unopened(v, ctx, cls, info):
    bb, S = v.bb, v.my_stack
    pct = tables.PCT[cls]
    callers = [(p, ctx.model(p.get('name')).call_range) for p in v.opps_live]
    can_check = v.call == 0
    hu = v.n_alive == 2

    if v.eff_bb <= config.pushfold_max_bb or (hu and v.eff_bb <= 15):
        ev, pts, si = shove_ev(v, ctx, cls, callers)
        info.update(si)
        alt = tables.eq_vs_random(cls, len(v.opps)) * v.pot * 0.8 if can_check else 0.0
        if _shove_ok(ev, pts, bb, ctx, alt):
            return ALL_IN, 'pf_shove', info
        return (CHECK if can_check else FOLD), 'pf_pushfold_no', info

    z3 = v.eff_bb > config.z2_max_bb
    if can_check:  # BB with limpers
        if pct <= 0.12:
            return RAISE_TO(3 * bb + bb * len(v.limpers)), 'pf_iso', info
        return CHECK, 'pf_check_bb', info

    open_pct = 0.65 if hu else OPEN_BY_BEHIND.get(len(v.behind), 0.13)
    if z3:
        open_pct *= 0.85
    if v.limpers:
        open_pct *= 0.6
    if any(ctx.model(p.get('name')).archetype == 'maniac' for p in v.opps_live):
        open_pct *= 0.6
    if pct <= open_pct:
        size = (config.open_raise_bb if z3 else config.z2_open_raise_bb) * bb + bb * len(v.limpers)
        if size >= 0.35 * S:
            return ALL_IN, 'pf_open_shove', info
        return RAISE_TO(int(size)), 'pf_open', info
    if not z3 and v.eff_bb <= 18:
        ev, pts, si = shove_ev(v, ctx, cls, callers)
        info.update(si)
        if _shove_ok(ev, pts, bb, ctx):
            return ALL_IN, 'pf_z2_shove', info
    return FOLD, 'pf_fold', info


def _facing_raise(v, ctx, cls, info):
    bb, S, call = v.bb, v.my_stack, v.call
    pct = tables.PCT[cls]
    agg = max(v.opps, key=_bet) if v.opps else None
    villains = [p for p in v.opps if _bet(p) > bb] or ([agg] if agg else [])
    ranges = [_range_of(ctx, p, bb) for p in villains]
    eq = _eq_vs(v, ctx, cls, ranges)
    call_eff = min(call, S)
    pot_eff = sum(min(_bet(p), v.my_bet + S) for p in v.players)
    required = call_eff / float(pot_eff + call_eff) if call_eff else 0.0
    margin = _var_margin(ctx)
    info.update({'eq': round(eq, 3), 'required': round(required, 3), 'ranges': [round(r, 2) for r in ranges]})
    agg_allin = agg is not None and _st(agg) == 0
    big = call >= 0.4 * S or v.eff_bb <= config.pushfold_max_bb or (agg_allin and _bet(agg) >= 0.25 * (S + v.my_bet))

    if big:
        ok = eq >= required + margin
        if ctx.icm and agg is not None:
            f, _, w, l = tournament.icm_allin(v, v.idx_of(agg), call_eff, 0, v.idx_of(agg))
            ok = eq * w + (1 - eq) * l > f + {-1: 0.01, 0: 0.0, 1: -0.01}[ctx.var]
            info['icm'] = [round(f, 3), round(w, 3), round(l, 3)]
        if ok:
            if agg_allin or call >= S:
                return CALL, 'pf_call_allin', info
            return ALL_IN, 'pf_reshove', info
        if not agg_allin and agg is not None and pct <= RESTEAL_MAX_PCT:  # fold equity re-shove
            callers = [(agg, _raiser_cont(agg))] + [(p, ctx.model(p.get('name')).call_range)
                                                     for p in v.opps_live if p is not agg]
            ev, pts, si = shove_ev(v, ctx, cls, callers)
            if _shove_ok(ev, pts, bb, ctx):
                info.update(si)
                return ALL_IN, 'pf_reshove_fe', info
        return FOLD, 'pf_fold_big', info

    z3 = v.eff_bb > config.z2_max_bb
    closing = not v.behind
    if not z3:
        if pct <= 0.06:
            return ALL_IN, 'pf_z2_3bet_shove', info
        if agg is not None and pct <= RESTEAL_MAX_PCT:
            callers = [(agg, _raiser_cont(agg))] + [(p, ctx.model(p.get('name')).call_range)
                                                     for p in v.opps_live if p is not agg]
            ev, pts, si = shove_ev(v, ctx, cls, callers)
            if _shove_ok(ev, pts, bb, ctx):
                info.update(si)
                return ALL_IN, 'pf_z2_resteal', info
        if v.is_bb and closing and call <= 1.5 * bb and eq >= required + config.call_margin_base + margin:
            return CALL, 'pf_bb_defend', info
        return FOLD, 'pf_z2_fold', info

    if pct <= 0.03:
        if v.my_bet > bb or 3 * v.current_buy_in >= 0.35 * (S + v.my_bet):
            return ALL_IN, 'pf_premium_shove', info
        return RAISE_TO(3 * v.current_buy_in), 'pf_3bet', info
    r1, r2 = v.hole[0] >> 2, v.hole[1] >> 2
    playable = r1 == r2 or ((v.hole[0] & 3) == (v.hole[1] & 3) and min(r1, r2) >= 8)
    if playable and call <= 0.08 * S and pct <= 0.35:
        return CALL, 'pf_call_playable', info
    if call <= 0.15 * S and eq >= required + 0.08 + margin:
        return CALL, 'pf_call_odds', info
    return FOLD, 'pf_z3_fold', info
