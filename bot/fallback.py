"""Dependency-free last resort: preflop shove TT+/AK, else check/fold."""


def bet(gs):
    try:
        me = gs['players'][gs['in_action']]
        stack = int(me.get('stack') or 0)
        if gs.get('community_cards'):
            return 0
        order = {'10': 10, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        rk = sorted([order.get(str(c['rank']), 0) or int(c['rank']) for c in me.get('hole_cards') or []])
        if len(rk) == 2 and ((rk[0] == rk[1] and rk[0] >= 10) or rk == [13, 14]):
            return stack
    except Exception:
        pass
    return 0
