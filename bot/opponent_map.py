"""The opponents we play against: what each one does, and how we counter it.

Every opponent-specific rule in the bot lives in this file. Each profile below was read from the
opponent's public source and checked against live game logs (tools/fetch_logs.py); the rest of the bot
is generic poker logic that works the same against anyone. When an opponent redeploys, update its
profile here and nowhere else.

    bpex        "maniac": pushes any two short, bets narrow size windows, calls our ~pot bluffs.
    megistekik  chart/rule bot: calls our small bets light, folds to its "big bet" line.
    nontechyk   equity-vs-random-hand bot: bets >= 0.6 equity, checks the rest, folds to big bets.
"""
from collections import deque

from . import tables
from .actions import ALL_IN
from .cards import hand_class

BPEX, MEGISTEKIK, NONTECHYK = 'bpex', 'megistekik', 'nontechyk'

PROFILES = {
    BPEX: """
        Preflop: pushes/folds at <= 15bb by Chen score (+3 heads-up, +1 three-handed); deeper it opens
        ~4.5bb with Chen >= 8. Postflop: bets 3/4 pot with >= 0.75 equity vs random, 1/2 pot with >= 0.55,
        mixes 30% semi-bluffs. Facing our bets it assumes a range that tightens with bet size, except
        that our 1.05-1.45x pot bets are read as bluffs and called with any 0.4-equity hand (v4.3+).
        Counter: bluff it just under pot (0.96x); value-bet thinner (>= 0.55 eq) at 0.7 pot.
        (Tried and reverted, v1.3.1: exact preflop ranges + deep non-all-in 3-bets vs its opens.)""",
    MEGISTEKIK: """
        Postflop it treats our heads-up bets as air (calls light) unless they are "big": >= half pot and
        >= 1/4 of its stack, which it reads as value and folds to without a strong hand.
        Counter: bluff only at its big-bet line (when that costs <= 1.2 pot); value-bet under the line.""",
    NONTECHYK: """
        Bets whenever its equity vs a random hand is >= 0.6, checks otherwise, and needs ~0.6 raw equity
        to call a >= half-pot bet. Its < 0.8-pot bets are ~44% air (live); its >= 0.8-pot bets are always
        top pair or better. It calls a lone all-in only vs our measured shove frequency (default top 15%).
        Counters: stab 3/4 pot whenever it checks to us heads-up (live: 42 of 43 folds); raise its small
        bets pot-size instead of folding; value-bet it small (0.45 pot); when it is the only player left,
        shove wide preflop up to 40bb effective (live: +127 BB over 234 hands, losing above 40bb).""",
}

# Heads-up big-bet bluff: pot fraction per opponent, scaled by BLUFF_SCALE (sim: 0.6 beat 1.0).
BLUFF_FRAC = {BPEX: 1.6, MEGISTEKIK: 1.0, NONTECHYK: 1.0}
BLUFF_SCALE = 0.6
BLUFF_MAX_EQ = 0.35          # only hands with no showdown value become bluffs
BLUFF_STREETS = (3, 4, 5)

NT_VALUE_FRAC = 0.45         # nontechyk calls ~0.4-pot bets from ~0.41 raw equity
NT_STAB_FRAC = 0.75
NT_MAX_SHOVE_RATE = 0.25     # keep our shove rate low so nontechyk keeps calling only premiums

_bluffed_hands = {}          # (game_id, round) -> True once we bluffed: never barrel
_recent_shoves = deque(maxlen=20)   # did we shove preflop, one entry per hand (nontechyk counts these)
_last_hand = [None]


def _st(p):
    return int(p.get('stack') or 0)


def _bet(p):
    return int(p.get('bet') or 0)


def _cap_at_stack(v, b):
    """A bet of 60%+ of our stack becomes an all-in."""
    return v.my_stack if b >= 0.6 * v.my_stack else b


# ---------------------------------------------------------------------------------------- preflop

def note_preflop_action(v, amount):
    """Track our preflop shove rate, which nontechyk uses to size its calling range."""
    if v.street:
        return
    key = (v.game_id, v.round)
    if _last_hand[0] != key:
        _last_hand[0] = key
        _recent_shoves.append(False)
    if amount >= v.my_stack > 0:
        _recent_shoves[-1] = True


def preflop_counter(v):
    """(intent, reason) when an opponent-specific preflop rule applies, else None (generic preflop runs)."""
    if v.street or len(v.hole) != 2 or len(v.opps) != 1:
        return None
    o = v.opps[0]
    if o.get('name') != NONTECHYK or _st(o) == 0:
        return None
    if _recent_shoves and sum(_recent_shoves) / float(len(_recent_shoves)) > NT_MAX_SHOVE_RATE:
        return None
    pct = tables.PCT[hand_class(v.hole[0], v.hole[1])]
    bb = v.bb
    if v.current_buy_in <= bb and v.eff_bb <= 40 and pct <= (1.0 if v.eff_bb <= 25 else 0.6):
        return ALL_IN, 'x_nt_shove_alone'
    if bb < _bet(o) <= 3.5 * bb and v.my_bet <= bb and v.eff_bb <= 25 and pct <= 0.5:
        return ALL_IN, 'x_nt_reshove'
    return None


# --------------------------------------------------------------------------------------- postflop

def bet_strength_level(v, p, level):
    """Override how strong an opponent's postflop bet is (0 = no information .. 3 = very strong)."""
    if p.get('name') == NONTECHYK and v.call:
        return 0 if v.call < 0.8 * max(v.pot - v.call, 1) else 3
    return level


def raise_bluff(v, agg, pot, call):
    """Chips to raise as a bluff instead of folding to agg's bet, or None."""
    if agg.get('name') == NONTECHYK and call < 0.8 * max(pot - call, 1):
        return call + pot + call
    return None


def value_bet_threshold(name, default):
    """Heads-up equity needed to value-bet; bpex calls wide, so bet thinner against it."""
    return 0.55 if name == BPEX else default


def value_bet_frac(name, frac, pot, opp):
    """Heads-up value-bet size as a pot fraction, adjusted to what each opponent calls."""
    if name == MEGISTEKIK:   # stay under its big-bet line so it keeps calling light
        return max(0.33, min(0.66, (_st(opp) // 4 - 1) / float(max(pot, 1))))
    if name == NONTECHYK:
        return NT_VALUE_FRAC
    if name == BPEX:
        return 0.7
    return frac


def stab(v, opp):
    """nontechyk checked to us heads-up: its hand is weak, a 3/4-pot bet folds almost all of it."""
    if opp.get('name') != NONTECHYK or v.call or _st(opp) == 0:
        return None
    if any(p is opp for p in v.behind):
        return None   # it has not acted on this street yet
    return _cap_at_stack(v, int(NT_STAB_FRAC * max(v.pot, 1)))


def big_bet_bluff(v, ctx, eq, opp, min_samples):
    """Heads-up bluff sized to the opponent's fold window; off once its measured fold rate says no."""
    name = opp.get('name')
    frac = BLUFF_FRAC.get(name)
    key = (v.game_id, v.round)
    if frac is None or _st(opp) == 0 or eq > BLUFF_MAX_EQ or v.street not in BLUFF_STREETS \
            or key in _bluffed_hands:
        return None
    f, n = ctx.model(name).fold_to_bet(2)
    if n >= min_samples and f < 0.45:
        return None
    if len(_bluffed_hands) > 5000:
        _bluffed_hands.clear()
    _bluffed_hands[key] = True
    b = int(frac * BLUFF_SCALE * max(v.pot, 1))
    if name == MEGISTEKIK:
        b = max(int(0.75 * v.pot), _st(opp) // 4 + 1)   # its big-bet line
        if b > 1.2 * v.pot:
            _bluffed_hands.pop(key, None)
            return None
    return _cap_at_stack(v, b)

