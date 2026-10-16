"""Postflop decisions: equity vs realistic ranges, then pot odds, stack-to-pot ratio and ICM.

1. Estimate each opponent's range: its preflop range (opponent model), narrowed by how many chips it
   has put in since the flop (a big bet removes most air and weak pairs from its range).
2. Monte Carlo our equity against those ranges (exact on a heads-up river), within the time budget.
3. Facing a bet: call when equity beats the price plus a margin; raise for value with >= 0.70
   (heads-up); at low stack-to-pot ratio it is shove-or-fold. With 3+ players left, any decision that
   risks our stack must also clear the ICM threshold, because busting 3rd scores nothing.
4. Not facing a bet: value-bet good hands, bluff where an opponent is known (opponent_map) or measured
   (bluff.py) to fold, otherwise check.
"""
import math

from . import config, equity, bluff, opponents, tables, tournament, opponent_map
from .actions import FOLD, CHECK, CALL, ALL_IN, RAISE_TO
from .evaluator import evaluate, category

# Keep-probability of a villain combo by bet-strength level (1..3) and the combo's strength class:
# 0 = air, 1 = draw, 2 = weak pair, 3 = top pair / overpair, 4 = two pair+ (made with hole cards).
# Air uses the opponent's measured bluff share instead of the None slot.
KEEP = {1: (None, 0.8, 1.0, 1.0, 1.0), 2: (None, 0.4, 0.5, 1.0, 1.0), 3: (None, 0.25, 0.2, 0.6, 1.0)}

# Equity guess by made-hand category, used when the game is out of thinking time (no Monte Carlo).
PROXY = {0: 0.25, 1: 0.50, 2: 0.68, 3: 0.78, 4: 0.85, 5: 0.88, 6: 0.93, 7: 0.97, 8: 0.99}


def _st(p):
    return int(p.get('stack') or 0)


def _bet(p):
    return int(p.get('bet') or 0)


# ------------------------------------------------------------------------------- villain ranges

def _range_pct(ctx, p):
    """Preflop range width of a player who reached the flop (shove range if it is all-in)."""
    m = ctx.model(p.get('name'))
    r = m.vpip_range
    if _st(p) == 0:
        r = min(r, m.shove_range)
    return max(0.10, min(1.0, r))


def _board_cat(board):
    """0 unpaired board, 1 paired, 2 two pair, 3 trips on board."""
    cnt = sorted([sum(1 for c in board if c >> 2 == r) for r in set(c >> 2 for c in board)], reverse=True)
    if cnt[0] >= 3:
        return 3
    if cnt[0] == 2:
        return 2 if len(cnt) > 1 and cnt[1] == 2 else 1
    return 0


def strength(hole, board, bcat, top):
    """Strength class of a holding on this board (see KEEP); only counts what the hole cards add."""
    cat = category(evaluate(hole + board))
    if cat >= 3 and cat > bcat:
        return 4
    if cat == 2 and bcat == 0:
        return 4
    if cat in (1, 2) and cat > bcat:
        hr = [c >> 2 for c in hole]
        if hr[0] == hr[1]:
            pair = hr[0]
        elif any(b >> 2 in hr for b in board):
            pair = max(r for r in hr if any(b >> 2 == r for b in board))
        else:
            pair = -1
        return 3 if pair >= top else 2
    return 1 if len(board) < 5 and bluff.has_draw(hole, board) else 0


def aggression(v, p, pf_level):
    """Bet-strength level 0..3 from the villain's postflop chips relative to the pot at the flop."""
    if pf_level is None:   # no memory of this hand (e.g. after a redeploy): use this street only
        extra, base = _bet(p) - v.my_bet, max(v.pot, 1)
    else:
        extra = _bet(p) - pf_level
        base = max(1, sum(min(_bet(q), pf_level) for q in v.players))
    r = extra / float(base)
    return 0 if r < 0.4 else 1 if r < 1.2 else 2 if r < 2.5 else 3


def villain_combos(ctx, v, p, pf_level):
    """Weighted combo list for one villain (duplicates = weight) and its bet-strength level."""
    combos = tables.range_combos(_range_pct(ctx, p))
    a = opponent_map.bet_strength_level(v, p, aggression(v, p, pf_level))
    if a == 0:
        return combos, a
    dead = set(v.hole + v.board)
    bcat, top = _board_cat(v.board), max(c >> 2 for c in v.board)
    bluff_share = ctx.model(p.get('name')).bluff_p
    keep = KEEP[a]
    out = []
    for cb in combos:
        if cb[0] in dead or cb[1] in dead:
            continue
        st = strength(list(cb), v.board, bcat, top)
        w = keep[st] if st else bluff_share * (1.0, 0.5, 0.3)[a - 1]
        out.extend([cb] * int(round(w * 4)))
    return (out or combos), a


def wet(board):
    """Three to a flush, or three ranks within a straight's span."""
    suits = [c & 3 for c in board]
    if max(suits.count(s) for s in range(4)) >= 3:
        return True
    r = sorted(set(c >> 2 for c in board))
    return any(r[i + 2] - r[i] <= 4 for i in range(len(r) - 2))


def _icm_equity_needed(v, vil, our_add, vil_add, winner):
    """Equity needed, in tournament points (5/3 ICM), to put our_add at risk against vil; None if n/a."""
    if vil is None:
        return None
    try:
        f, _, w, l = tournament.icm_allin(v, v.idx_of(vil), our_add, vil_add, v.idx_of(winner or vil))
    except Exception:
        return None
    return (f - l) / (w - l) if w > l else None


# ------------------------------------------------------------------------------------- decision

def _equity(v, ctx, opps, info):
    if ctx.table_only:   # out of thinking time for this game: no Monte Carlo
        info['eq_se'] = None
        return PROXY[category(evaluate(v.hole + v.board))] - 0.05 * (len(opps) - 1)
    pf_level = opponents.pf_level(v.game_id, v.raw.get('round', 0))
    ranges, levels = [], []
    for p in opps:
        cb, a = villain_combos(ctx, v, p, pf_level)
        ranges.append(cb)
        levels.append(a)
    info['aggr'] = levels
    eq, it = equity.equity(v.hole, v.board, ranges, ctx.deadline, config.mc_max_iters, ctx.seed)
    info['eq_se'] = round(math.sqrt(max(eq * (1 - eq), 1e-9) / max(it, 1)), 4)
    info['iters'] = it
    return eq


def decide(v, ctx):
    opps = v.opps
    n = max(1, len(opps))
    info = {}
    eq = _equity(v, ctx, opps, info)
    info['eq'] = round(eq, 3)

    S, pot, call = v.my_stack, v.pot, v.call
    eff = min(S, max([_st(p) for p in opps] or [S]))
    spr = eff / float(max(pot, 1))
    margin = config.call_margin_base + config.call_margin_per_extra_opp * (n - 1)
    margin += {-1: 0.04, 0: 0.0, 1: -0.03}[ctx.var]       # 3-minute cutoff: protect lead / gamble
    agg = max(opps, key=_bet) if opps else None
    arch = ctx.model(agg.get('name')).archetype if agg else 'unknown'
    if arch == 'maniac':
        margin -= 0.05                                     # its big bets are often bluffs
    elif arch == 'nit' and call > 0.5 * pot:
        margin += 0.05                                     # its big bets are not
    info.update({'spr': round(spr, 2), 'arch': arch})

    if call > 0:
        return _facing_bet(v, ctx, eq, n, agg, margin, spr, info)
    return _no_bet(v, ctx, eq, n, opps, arch, spr, info)


def _facing_bet(v, ctx, eq, n, agg, margin, spr, info):
    S, pot, call = v.my_stack, v.pot, v.call
    call_eff = min(call, S)
    pot_eff = sum(min(_bet(p), v.my_bet + S) for p in v.players)   # chips we can actually win
    required = call_eff / float(pot_eff + call_eff)                 # pot odds
    info['required'] = round(required, 3)
    agg_allin = agg is not None and _st(agg) == 0
    var_adj = {-1: 0.03, 0: 0.0, 1: -0.03}[ctx.var]

    # Low stack-to-pot ratio, or the call is half our stack: it is shove-or-fold.
    if spr <= config.low_spr_shove or call >= 0.5 * S:
        need = required + margin
        if ctx.icm:
            ir = _icm_equity_needed(v, agg, call_eff, 0, agg)
            if ir is not None:
                info['icm_req'] = round(ir, 3)
                need = max(need, ir + var_adj)
        if eq < need:
            return FOLD, 'post_lowspr_fold', info
        shove_eq = 0.62 if v.street == 5 else 0.52
        if eq >= shove_eq and not agg_allin and call < S and v.opps_live:
            ir = _icm_equity_needed(v, agg, S, max(0, min(_st(agg), S - call)), agg) if ctx.icm else None
            if ir is None or eq >= ir + var_adj:
                return ALL_IN, 'post_lowspr_shove', info
        return CALL, 'post_lowspr_call', info

    # Strong hand: raise for value (all-in if the raise is most of our stack and ICM allows).
    if eq >= (config.raise_eq_hu if n == 1 else config.raise_eq_multi) and v.opps_live:
        size = call + max(v.min_raise, 2 * call)
        if size >= 0.5 * S:
            ir = _icm_equity_needed(v, agg, S, max(0, min(_st(agg), S - call)), agg) if ctx.icm else None
            if ir is not None and eq < ir + var_adj:
                return (CALL if eq >= required + margin else FOLD), 'post_icm_noshove', info
            return ALL_IN, 'post_raise_allin', info
        return RAISE_TO(v.my_bet + size), 'post_raise', info

    if eq >= required + margin:
        return CALL, 'post_call', info

    # Would fold: some opponents' small bets are weak enough to raise as a bluff (opponent_map).
    if n == 1 and v.opps_live:
        size = opponent_map.raise_bluff(v, agg, pot, call)
        if size:
            if size >= 0.5 * S:
                if ctx.icm:
                    return FOLD, 'post_fold', info   # never risk our stack on a bluff with 3+ left
                return ALL_IN, 'post_nt_raise_bluff', info
            return RAISE_TO(v.my_bet + size), 'post_nt_raise_bluff', info
    return FOLD, 'post_fold', info


def _no_bet(v, ctx, eq, n, opps, arch, spr, info):
    S, pot = v.my_stack, v.pot
    hu_name = opps[0].get('name') if n == 1 else None
    default_thr = config.value_bet_eq_hu if n == 1 else config.value_bet_eq_multi
    thr = opponent_map.value_bet_threshold(hu_name, default_thr)

    # Value bet: 2/3 pot, bigger on wet boards and vs calling stations, tuned per opponent.
    if eq >= thr and v.opps_live:
        frac = 0.66
        if wet(v.board):
            frac = 0.75
        if arch == 'station':
            frac = 0.85
        if hu_name:
            frac = opponent_map.value_bet_frac(hu_name, frac, pot, opps[0])
        size = max(v.bb, int(frac * pot))
        if spr <= config.low_spr_shove or size >= 0.5 * S:
            big = max(opps, key=_st)
            ir = _icm_equity_needed(v, big, S, max(0, min(_st(big), S)), big) if ctx.icm else None
            if ir is not None and eq < ir:
                return CHECK, 'post_icm_check', info
            return ALL_IN, 'post_value_allin', info
        return RAISE_TO(v.my_bet + size), 'post_value', info

    # Bluffs, heads-up only; with 3+ players left never as an all-in.
    if n == 1 and v.opps_live:
        b = opponent_map.stab(v, opps[0])
        if b and not (ctx.icm and b >= S):
            return RAISE_TO(v.my_bet + b), 'post_nt_stab', info
        b = opponent_map.big_bet_bluff(v, ctx, eq, opps[0], config.min_samples)
        if b and not (ctx.icm and b >= S):
            return RAISE_TO(v.my_bet + b), 'post_exploit_bluff', info
        b = bluff.decide(v, ctx, eq, opps[0])
        if b:
            return RAISE_TO(v.my_bet + b), 'post_bluff', info
    return CHECK, 'post_check', info
