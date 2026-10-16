"""Postflop: equity vs ranges, SPR shove/fold, value bets, pot-odds calls, bluffs."""
import math

from . import config, equity, bluff, opponents, tables, tournament
from .actions import FOLD, CHECK, CALL, ALL_IN, RAISE_TO
from .evaluator import evaluate, category
from .exploits import BPEX, MEGISTEKIK, NONTECHYK

# keep-probability of a villain combo by (aggression level, strength class); 0 = air, 1 = draw,
# 2 = weak pair, 3 = top pair / overpair, 4 = two pair or better (made with hole cards)
KEEP = {1: (None, 0.8, 1.0, 1.0, 1.0), 2: (None, 0.4, 0.5, 1.0, 1.0), 3: (None, 0.25, 0.2, 0.6, 1.0)}

NT_VALUE_FRAC = 0.45   # nontechyk calls ~0.4-pot bets from ~0.41 raw equity, >= half pot only from ~0.6
NT_RAISE_BLUFF = True  # its half-pot/tiny bets are ~44% air (live) and it folds ~0.8-equity-less hands to a raise
PROXY = {0: 0.25, 1: 0.50, 2: 0.68, 3: 0.78, 4: 0.85, 5: 0.88, 6: 0.93, 7: 0.97, 8: 0.99}


def _st(p):
    return int(p.get('stack') or 0)


def _bet(p):
    return int(p.get('bet') or 0)


def _range_pct(ctx, p):
    m = ctx.model(p.get('name'))
    r = m.vpip_range
    if _st(p) == 0:
        r = min(r, m.shove_range)
    return max(0.10, min(1.0, r))


def _board_cat(board):
    cnt = sorted([sum(1 for c in board if c >> 2 == r) for r in set(c >> 2 for c in board)], reverse=True)
    if cnt[0] >= 3:
        return 3
    if cnt[0] == 2:
        return 2 if len(cnt) > 1 and cnt[1] == 2 else 1
    return 0


def strength(hole, board, bcat, top):
    cat = category(evaluate(hole + board))
    if cat >= 3 and cat > bcat:
        return 4
    if cat == 2 and bcat == 0:
        return 4
    if cat in (1, 2) and cat > bcat:
        hr = [c >> 2 for c in hole]
        pair = hr[0] if hr[0] == hr[1] else max(r for r in hr if any(b >> 2 == r for b in board)) \
            if any(b >> 2 in hr for b in board) else -1
        return 3 if pair >= top else 2
    return 1 if len(board) < 5 and bluff.has_draw(hole, board) else 0


def aggression(v, p, lvl):
    """0..3 from the villain's postflop chips relative to the pot at the flop."""
    if lvl is None:
        extra, base = _bet(p) - v.my_bet, max(v.pot, 1)
    else:
        extra = _bet(p) - lvl
        base = max(1, sum(min(_bet(q), lvl) for q in v.players))
    r = extra / float(base)
    return 0 if r < 0.4 else 1 if r < 1.2 else 2 if r < 2.5 else 3


def villain_combos(ctx, v, p, lvl):
    combos = tables.range_combos(_range_pct(ctx, p))
    a = aggression(v, p, lvl)
    if p.get('name') == NONTECHYK and v.call:
        # live: its < 0.8-pot bets are ~44% air, its >= 0.8-pot bets always top pair or better
        a = 0 if v.call < 0.8 * max(v.pot - v.call, 1) else 3
    if a == 0:
        return combos, a
    dead = set(v.hole + v.board)
    bcat, top = _board_cat(v.board), max(c >> 2 for c in v.board)
    bl = ctx.model(p.get('name')).bluff_p
    keep = KEEP[a]
    out = []
    for cb in combos:
        if cb[0] in dead or cb[1] in dead:
            continue
        st = strength(list(cb), v.board, bcat, top)
        w = keep[st] if st else bl * (1.0, 0.5, 0.3)[a - 1]
        out.extend([cb] * int(round(w * 4)))
    return (out or combos), a


def wet(board):
    suits = [c & 3 for c in board]
    if max(suits.count(s) for s in range(4)) >= 3:
        return True
    r = sorted(set(c >> 2 for c in board))
    return any(r[i + 2] - r[i] <= 4 for i in range(len(r) - 2))


def _ireq(v, vil, our_add, vil_add, winner):
    """Equity needed in tournament points (5/3 ICM) to risk our_add against vil; None when not applicable."""
    if vil is None:
        return None
    try:
        f, _, w, l = tournament.icm_allin(v, v.idx_of(vil), our_add, vil_add, v.idx_of(winner or vil))
    except Exception:
        return None
    return (f - l) / (w - l) if w > l else None


def decide(v, ctx):
    opps = v.opps
    n = max(1, len(opps))
    info = {}
    if ctx.table_only:
        eq = PROXY[category(evaluate(v.hole + v.board))] - 0.05 * (n - 1)
        info['eq_se'] = None
    else:
        lvl = opponents.pf_level(v.game_id, v.raw.get('round', 0))
        rng, aggr = [], []
        for p in opps:
            cb, a = villain_combos(ctx, v, p, lvl)
            rng.append(cb)
            aggr.append(a)
        info['aggr'] = aggr
        eq, it = equity.equity(v.hole, v.board, rng, ctx.deadline, config.mc_max_iters, ctx.seed)
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
        vadj = {-1: 0.03, 0: 0.0, 1: -0.03}[ctx.var]
        if spr <= config.low_spr_shove or call >= 0.5 * S:
            need = required + margin
            if ctx.icm:
                ir = _ireq(v, agg, call_eff, 0, agg)
                if ir is not None:
                    info['icm_req'] = round(ir, 3)
                    need = max(need, ir + vadj)
            if eq < need:
                return FOLD, 'post_lowspr_fold', info
            shove_eq = 0.62 if v.street == 5 else 0.52
            if eq >= shove_eq and not agg_allin and call < S and v.opps_live:
                ir = _ireq(v, agg, S, max(0, min(_st(agg), S - call)), agg) if ctx.icm else None
                if ir is None or eq >= ir + vadj:
                    return ALL_IN, 'post_lowspr_shove', info
            return CALL, 'post_lowspr_call', info
        if eq >= (config.raise_eq_hu if n == 1 else config.raise_eq_multi) and v.opps_live:
            size = call + max(v.min_raise, 2 * call)
            if size >= 0.5 * S:
                ir = _ireq(v, agg, S, max(0, min(_st(agg), S - call)), agg) if ctx.icm else None
                if ir is not None and eq < ir + vadj:
                    return (CALL if eq >= required + margin else FOLD), 'post_icm_noshove', info
                return ALL_IN, 'post_raise_allin', info
            return RAISE_TO(v.my_bet + size), 'post_raise', info
        if eq >= required + margin:
            return CALL, 'post_call', info
        if NT_RAISE_BLUFF and n == 1 and v.opps_live and agg.get('name') == NONTECHYK \
                and call < 0.8 * max(pot - call, 1):
            size = call + pot + call
            if size >= 0.5 * S and ctx.icm:
                return FOLD, 'post_fold', info
            if size >= 0.5 * S:
                return ALL_IN, 'post_nt_raise_bluff', info
            return RAISE_TO(v.my_bet + size), 'post_nt_raise_bluff', info
        return FOLD, 'post_fold', info

    thr = config.value_bet_eq_hu if n == 1 else config.value_bet_eq_multi
    hu_name = opps[0].get('name') if n == 1 else None
    if hu_name == BPEX:
        thr = 0.55  # bpex calls our <= pot bets wide: value-bet thinner, at <= 0.8 pot
    if eq >= thr and v.opps_live:
        frac = 0.66
        if wet(v.board):
            frac = 0.75
        if arch == 'station':
            frac = 0.85
        if hu_name == MEGISTEKIK:
            # stay under its "big bet" line (>= half pot and >= 1/4 of its stack) so it calls light
            frac = max(0.33, min(0.66, (_st(opps[0]) // 4 - 1) / float(max(pot, 1))))
        if hu_name == NONTECHYK:
            frac = NT_VALUE_FRAC
        if hu_name == BPEX:
            frac = 0.7
        size = max(v.bb, int(frac * pot))
        if spr <= config.low_spr_shove or size >= 0.5 * S:
            big = max(opps, key=_st)
            ir = _ireq(v, big, S, max(0, min(_st(big), S)), big) if ctx.icm else None
            if ir is not None and eq < ir:
                return CHECK, 'post_icm_check', info
            return ALL_IN, 'post_value_allin', info
        return RAISE_TO(v.my_bet + size), 'post_value', info
    if n == 1 and v.opps_live:
        b = bluff.nontechyk_stab(v, opps[0])
        if b and ctx.icm and b >= S:
            b = None
        if b:
            return RAISE_TO(v.my_bet + b), 'post_nt_stab', info
        b = bluff.exploit(v, ctx, eq, opps[0])
        if b and ctx.icm and b >= S:
            b = None
        if b:
            return RAISE_TO(v.my_bet + b), 'post_exploit_bluff', info
        b = bluff.decide(v, ctx, eq, opps[0])
        if b:
            return RAISE_TO(v.my_bet + b), 'post_bluff', info
    return CHECK, 'post_check', info
