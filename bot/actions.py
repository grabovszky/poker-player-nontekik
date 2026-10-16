"""Intents -> legal integer amounts. Strategy code returns intents, never raw numbers."""
import math

from . import config

FOLD = ('FOLD',)
CHECK = ('CHECK',)
CALL = ('CALL',)
ALL_IN = ('ALL_IN',)


def RAISE_TO(total):
    return ('RAISE_TO', total)


def sanitize(amount, stack):
    try:
        a = float(amount)
        if a != a or a in (float('inf'), float('-inf')):
            return 0
        a = int(math.floor(a))
    except (TypeError, ValueError):
        return 0
    stack = max(0, int(stack or 0))
    return max(0, min(a, stack))


def legal_amount(intent, v):
    kind = intent[0]
    if kind == 'CALL':
        amt = v.call
    elif kind == 'ALL_IN':
        amt = v.my_stack
    elif kind == 'RAISE_TO':
        amt = int(intent[1]) - v.my_bet
        lo = v.call + v.min_raise + (1 if config.raise_plus_one else 0)
        amt = max(amt, lo)
    else:
        amt = 0
    return sanitize(amt, v.my_stack)
