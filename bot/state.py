"""Typed, validated view of a raw Lean Poker game_state."""
from . import cards


def _i(x, d=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return d


class View(object):
    def __init__(self, gs):
        self.raw = gs
        self.game_id = str(gs.get('game_id', ''))
        self.round = _i(gs.get('round'))
        self.players = gs.get('players') or []
        self.me_idx = _i(gs.get('in_action'))
        self.me = self.players[self.me_idx]
        self.name = self.me.get('name')
        hole = self.me.get('hole_cards') or []
        self.hole = cards.parse_many(hole) if len(hole) == 2 else []
        self.board = cards.parse_many(gs.get('community_cards'))
        self.street = len(self.board)
        self.sb = max(1, _i(gs.get('small_blind'), 1))
        self.bb = 2 * self.sb
        self.current_buy_in = _i(gs.get('current_buy_in'))
        self.my_stack = max(0, _i(self.me.get('stack')))
        self.my_bet = max(0, _i(self.me.get('bet')))
        self.call = max(0, self.current_buy_in - self.my_bet)
        mr = gs.get('minimum_raise')
        self.min_raise = max(1, _i(mr, self.bb)) if mr is not None else self.bb
        self.pot = _i(gs.get('pot')) or sum(_i(p.get('bet')) for p in self.players)
        n = len(self.players)
        self.dealer = _i(gs.get('dealer')) % max(1, n)

        self.alive = [(self.dealer + k) % n for k in range(n)
                      if self.players[(self.dealer + k) % n].get('status') != 'out']
        self.n_alive = len(self.alive)
        self.opps = [p for i, p in enumerate(self.players) if i != self.me_idx and p.get('status') == 'active']
        self.opps_live = [p for p in self.opps if _i(p.get('stack')) > 0]

        biggest = max([_i(p.get('stack')) + _i(p.get('bet')) for p in self.opps] or [0])
        self.eff = min(self.my_stack + self.my_bet, biggest)
        self.eff_bb = self.eff / float(self.bb)
        self.stack_bb = self.my_stack / float(self.bb)

        a = self.alive
        if len(a) == 2:  # heads-up: dealer posts the small blind
            self.sb_seat, self.bb_seat = a[0], a[1]
            pf = [a[0], a[1]]
        elif len(a) > 2:
            self.sb_seat, self.bb_seat = a[1], a[2]
            pf = a[3:] + a[:3]
        else:
            self.sb_seat = self.bb_seat = -1
            pf = list(a)
        order = pf if self.street == 0 else a[1:] + a[:1]
        pos = order.index(self.me_idx) if self.me_idx in order else len(order)
        self.behind = [self.players[i] for i in order[pos + 1:]
                       if self.players[i].get('status') == 'active' and _i(self.players[i].get('stack')) > 0]
        self.is_bb = self.me_idx == self.bb_seat
        self.limpers = [p for i, p in enumerate(self.players)
                        if i != self.me_idx and i != self.bb_seat and p.get('status') == 'active'
                        and _i(p.get('bet')) >= self.bb]

    def idx_of(self, player):
        for i, p in enumerate(self.players):
            if p is player:
                return i
        return -1
