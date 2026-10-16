"""Lean Poker entry point. Never lets an error reach the dealer: any exception falls back to a tiny
safe strategy (bot/fallback.py), and every return value is forced to a legal integer."""
import time

from bot import strategy, fallback, log
from bot.actions import sanitize


def _stack(gs):
    try:
        return int(gs['players'][gs['in_action']].get('stack') or 0)
    except Exception:
        return 0


class Player:
    VERSION = "1.3.2 readable refactor, same play as 1.3.0"
    team_name = "nontekik"

    def betRequest(self, game_state):
        t0 = time.perf_counter()
        try:
            amt = strategy.bet_request(game_state, t0)
        except Exception:
            log.warn('bet_request failed, using fallback', game_state.get('game_id') if isinstance(game_state, dict) else None)
            try:
                amt = fallback.bet(game_state)
            except Exception:
                amt = 0
        return sanitize(amt, _stack(game_state))

    def showdown(self, game_state):
        try:
            strategy.showdown(game_state)
        except Exception:
            log.warn('showdown failed', game_state.get('game_id') if isinstance(game_state, dict) else None)
