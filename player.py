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
    team_name = "nontekik "

    def is_irational(self, cfg):
        return random.random() > cfg.get('randomness', 0.5)

    def is_berserk(self):
        return random.random() > config.get('berserkness', 0.5)

    def is_bluff_spot(self, game_state, hand, community_cards):
        """
        Returns True if we are in a good bluff spot.
        Example bluff signal: everyone checked and board is scary, or flush/straight possible.
        Very aggressive: bluff randomly with a small chance, especially on dry boards and poor hands.
        """
        n_players = len(game_state.get('players', []))
        # Example: bluff with 10% chance if win perc is very low and board is a good bluff (e.g., scary board)
        hand_win_perc = self.hand_win_percentage(hand)
        if hand_win_perc < 6.0:
            # More likely to bluff if no one has raised much (passive opponents)
            average_bet = sum(p.get("bet", 0) for p in game_state['players']) / max(n_players, 1)
            if average_bet < get_nested(game_state, ['current_buy_in'], 0) * 1.2:
                if random.random() < 0.1:  # 10% bluff freq when hand is weak and action is passive
                    return True
        # More complex bluffing heuristics can be added here.
        return False

    def betRequest(self, game_state):
        us = self.get_our_player(game_state)
        hand = us['hole_cards']
        hand_win_perc = self.hand_win_percentage(hand)

        raise_amt = self.action_raise(game_state, 1)
        all_in_amt = self.action_all_in(game_state)
        check_amt = self.action_check(game_state)

        if self.is_berserk():
            return max(all_in_amt, 100000)

        # Pre-flop decision
        if self.is_pref_flop(game_state):
            # AGGRESSIVE: Loosen thresholds, raise much more frequently
            if hand_win_perc >= config.get('all_in_perc', 14.8):
                return all_in_amt  # More aggressive: go all-in, not just raise
            if hand_win_perc >= config.get('min_raise_perc', 10):  # Lowered threshold
                return max(raise_amt, int(all_in_amt * 0.60))  # Increase raise proportion
            if hand_win_perc > config.get('min_raise_perc_attemptive', 7):  # Lowered again
                # Aggressive moderate bet
                if self.is_irational(config):
                    return int(all_in_amt * 0.4)
                else:
                    return int(all_in_amt * 0.25)
            # Pre-flop bluff opportunity
            if self.is_bluff_spot(game_state, hand, []):
                return max(raise_amt, int(all_in_amt * 0.4))
            return 0

        # Post-flop decision
        community = self.get_community_cards(game_state)
        community_cards = transform_cards(community)
        our_cards = transform_cards(hand)
        c = CardValue()
        community_card_count = len(community_cards)
        score = (c.find_card_score(our_cards + community_cards) - c.find_card_score(community_cards)) * (1 - 0.1 * (community_card_count - 1))

        # More aggressive betting thresholds
        min_score_1 = config.get('min_score_1', 20) - 10
        min_score_2 = config.get('min_score_2', 80) - 20
        min_score_3 = config.get('min_score_3', 200) - 30

        if score <= min_score_1:
            # BLUFF on some low hands
            if self.is_bluff_spot(game_state, hand, community_cards):
                return max(raise_amt, int(all_in_amt * 0.35))
            return 0
        if score <= min_score_2:
            # Be more aggressive: use bigger chunk if random
            if self.is_irational(config):
                return int(all_in_amt * 0.4)
            else:
                return min(check_amt, int(all_in_amt * 0.25))
        if score > min_score_3:
            # Always raise high on excellent post-flop hands
            return max(raise_amt, int(all_in_amt * 0.75))
        # Bigger default raise than before
        return max(raise_amt, int(all_in_amt * 0.33))

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