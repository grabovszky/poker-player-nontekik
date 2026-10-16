class Player:
    VERSION = "nontekik_v0.1.0"

    def betRequest(self, game_state):
        in_action = game_state['in_action']
        player = game_state['players'][in_action]
        our_bet = player['bet']
        cards = player['hole_cards']
        card0 = dict(cards[0])
        card1 = dict(cards[1])

        def call():
            return game_state['current_buy_in'] - our_bet - game_state['small_blind']

        def fold():
            return 0

        def minimum_raise():
            return call() + game_state['minimum_raise']

        # calculate the rank of the hand with Chen
        def rank():
            # convert '10' to 'T'
            if card0['rank'] == '10':
                card0['rank'] = 'T'
            if card1['rank'] == '10':
                card1['rank'] = 'T'

            hand = card0['rank'] + card1['rank']
            hand_reverse = card1['rank'] + card0['rank']

            ranks = [
                {
                    "rank": 1,
                    "cards": ['AA', 'KK', 'QQ', 'AK']
                },
                {
                    "rank": 2,
                    "cards": ['JJ', 'TT', '99']
                },
                {
                    "rank": 3,
                    "cards": ['88', '77', 'AQ']
                },
                {
                    "rank": 4,
                    "cards": ['66', '65', '44', '33', '22', 'AJ', 'AT', 'A9', 'A8']
                },
                {
                    "rank": 5,
                    "cards": ['A7', 'A6', 'A5', 'A4', 'A3', 'A2', 'KQ']
                },
                {
                    "rank": 6,
                    "cards": ['QJ', 'JT', 'T9', '98', '87', '76', '75', '65']
                }
            ]
            hand_rank = 7
            for r in ranks:
                if hand in r['cards'] or hand_reverse in r['cards']:
                    hand_rank = r['rank']
                    break
            return hand_rank

        def call_or_fold():
            current_call = call()
            if current_call <= 50:
                return call()
            if current_call <= our_bet * 1.25:
                return call()
            return fold()

        def is_straight():
            all_cards = list(game_state['community_cards'])
            all_cards.append(card0)
            all_cards.append(card1)

            # map each card's rank to int for comparison
            def to_num(card):
                r = card['rank']
                if r == 'A':
                    return 14
                elif r == 'K':
                    return 13
                elif r == 'Q':
                    return 12
                elif r == 'J':
                    return 11
                elif r == 'T':
                    return 10
                else:
                    try:
                        return int(r)
                    except Exception:
                        return 0

            nums = [to_num(card) for card in all_cards]
            nums = sorted(set(nums))
            # count consecutive numbers
            max_consecutive = 1
            current_consecutive = 1
            for i in range(1, len(nums)):
                if nums[i] == nums[i-1] + 1:
                    current_consecutive += 1
                    if current_consecutive > max_consecutive:
                        max_consecutive = current_consecutive
                else:
                    current_consecutive = 1
            return max_consecutive >= 5

        def preflop_strategie():
            r = rank()
            if r == 1:
                return int(minimum_raise() * 5)
            elif r == 2:
                return int(minimum_raise() * 2)
            elif r == 3 or r == 4:
                return int(minimum_raise() * 1.5)
            elif r == 5:
                return int(minimum_raise())
            elif r == 6:
                return call_or_fold()
            else:
                return call_or_fold()

        def flop_strategie():
            if is_straight():
                return int(minimum_raise() * 10)
            r = rank()
            if r == 1:
                return int(minimum_raise() * 5)
            elif r == 2:
                return int(minimum_raise() * 2)
            elif r == 3 or r == 4:
                return int(minimum_raise() * 1.5)
            elif r == 5:
                return int(minimum_raise())
            elif r == 6:
                return call_or_fold()
            else:
                return call_or_fold()

        cc_len = len(game_state.get('community_cards', []))
        if cc_len == 0:
            # Preflop
            print("preflop")
            return preflop_strategie()
        elif cc_len == 3:
            print("flop")
            return flop_strategie()
        elif cc_len == 4:
            print("turn")
            return flop_strategie()
        elif cc_len == 5:
            print("river")
            return flop_strategie()
        else:
            return flop_strategie()

    def showdown(self, game_state):
        pass
