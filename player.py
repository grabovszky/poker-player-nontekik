import random
from CardValue import CardValue
from config import config
from hands import hands

def get_nested(d, keys, default):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) and k in d else None
        if d is None:
            return default
    return d

def transform_cards(cards):
    return [(c['rank'], c['suit']) for c in cards]

class Player:
    VERSION = "nontekik_v0.2.0"
    order = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    team_name = "So Deal With It "

    def is_irational(self, cfg):
        return random.random() > cfg.get('randomness', 0.5)

    def is_berserk(self):
        return random.random() > config.get('berserkness', 0.5)

    def betRequest(self, game_state):
        us = self.get_our_player(game_state)
        hand = us['hole_cards']
        hand_win_perc = self.hand_win_percentage(hand)

        raise_amt = self.action_raise(game_state, 1)
        all_in_amt = self.action_all_in(game_state)
        check_amt = self.action_check(game_state)

        if self.is_berserk():
            return 100000

        if self.is_pref_flop(game_state):
            if hand_win_perc >= config.get('all_in_perc', 14.8):
                return raise_amt
            if hand_win_perc >= config.get('min_raise_perc', 12):
                return raise_amt if self.is_irational(config) else min(raise_amt, all_in_amt / 2)
            if hand_win_perc > config.get('min_raise_perc_attemptive', 10):
                return raise_amt if self.is_irational(config) else min(raise_amt, all_in_amt / 4)
            return 0

        # post-flop
        community = self.get_community_cards(game_state)
        community_cards = transform_cards(community)
        our_cards = transform_cards(hand)
        c = CardValue()
        community_card_count = len(community_cards)
        score = (c.find_card_score(our_cards + community_cards) - c.find_card_score(community_cards)) * (1 - 0.1 * (community_card_count - 1))

        if score <= config.get('min_score_1', 20):
            return 0
        if score <= config.get('min_score_2', 80):
            return all_in_amt if self.is_irational(config) else min(check_amt, all_in_amt / 3)
        if score > config.get('min_score_3', 200):
            return raise_amt if self.is_irational(config) else raise_amt
        return min(raise_amt, all_in_amt / 2)

    def is_pref_flop(self, game_state):
        return not self.get_community_cards(game_state)

    def get_community_cards(self, game_state):
        return get_nested(game_state, ['community_cards'], [])

    def showdown(self, game_state):
        pass

    def hand_win_percentage(self, hand):
        ranks = self.order_cards([hand[0]['rank'], hand[1]['rank']])
        suited = hand[0].get('suit') == hand[1].get('suit')
        h = tuple(ranks + ['' if suited is None else ('s' if suited else 'o')])
        return hands.get(h, 0)

    def order_cards(self, ranks):
        return sorted(ranks, key=lambda x: -self.order.index(x))

    def action_all_in(self, game_state):
        return self.get_our_player(game_state).get("stack", 0)

    def action_check(self, game_state):
        return get_nested(game_state, ['current_buy_in'], 0)

    def action_raise(self, game_state, amount=0):
        current_buy_in = get_nested(game_state, ['current_buy_in'], 0)
        us = self.get_our_player(game_state)
        already_bet = us.get("bet", 0)
        minimum_raise = get_nested(game_state, ['minimum_raise'], 0)
        our_stack = us.get("stack", 0)
        return max(minimum_raise, min(our_stack, current_buy_in + already_bet + amount))

    def get_our_player(self, game_state):
        return next(p for p in game_state['players'] if p['name'] == self.team_name)

if __name__ == '__main__':
    p = Player()
    print(p.hand_win_percentage([{'rank': 'A'}, {'rank': 'A'}]))
    print(p.hand_win_percentage([{'rank': '2'}, {'rank': '8'}]))
    print(p.hand_win_percentage([{'rank': 'A'}, {'rank': '4'}]))