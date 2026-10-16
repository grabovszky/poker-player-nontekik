"""Card encoding: int 0..51 = rank*4 + suit, rank 0..12 = 2..A."""
RANKS = '23456789TJQKA'
SUITS = ('clubs', 'diamonds', 'hearts', 'spades')
_RANK = {r: i for i, r in enumerate(RANKS)}
_RANK.update({'10': 8, 't': 8, 'j': 9, 'q': 10, 'k': 11, 'a': 12})
_SUIT = {s: i for i, s in enumerate(SUITS)}
_SUIT.update({'c': 0, 'd': 1, 'h': 2, 's': 3})


def parse(card):
    r = str(card['rank']).strip()
    r = _RANK[r] if r in _RANK else _RANK[r.upper()]
    s = _SUIT[str(card['suit']).strip().lower()]
    return r * 4 + s


def parse_many(cards):
    return [parse(c) for c in (cards or [])]


def to_str(c):
    return RANKS[c >> 2] + 'cdhs'[c & 3]


def hand_class(c1, c2):
    """Index 0..168 in the 13x13 grid: pairs diagonal, suited above, offsuit below."""
    r1, r2 = c1 >> 2, c2 >> 2
    hi, lo = max(r1, r2), min(r1, r2)
    if hi == lo:
        return (12 - hi) * 14
    if (c1 & 3) == (c2 & 3):
        return (12 - hi) * 13 + (12 - lo)
    return (12 - lo) * 13 + (12 - hi)


def class_name(idx):
    row, col = divmod(idx, 13)
    if row == col:
        return RANKS[12 - row] * 2
    if row < col:
        return RANKS[12 - row] + RANKS[12 - col] + 's'
    return RANKS[12 - col] + RANKS[12 - row] + 'o'


def class_combos(idx):
    row, col = divmod(idx, 13)
    out = []
    if row == col:
        r = 12 - row
        for s1 in range(4):
            for s2 in range(s1 + 1, 4):
                out.append((r * 4 + s1, r * 4 + s2))
    elif row < col:
        hi, lo = 12 - row, 12 - col
        for s in range(4):
            out.append((hi * 4 + s, lo * 4 + s))
    else:
        hi, lo = 12 - col, 12 - row
        for s1 in range(4):
            for s2 in range(4):
                if s1 != s2:
                    out.append((hi * 4 + s1, lo * 4 + s2))
    return out


def chen(c1, c2):
    """Chen formula (Phase 1 heuristic / fallback ordering)."""
    import math
    pts = {12: 10, 11: 8, 10: 7, 9: 6}
    r1, r2 = c1 >> 2, c2 >> 2
    hi, lo = max(r1, r2), min(r1, r2)
    score = pts.get(hi, (hi + 2) / 2.0)
    if hi == lo:
        return max(5, math.ceil(score * 2))
    if (c1 & 3) == (c2 & 3):
        score += 2
    gap = hi - lo - 1
    score -= (0, 1, 2, 4)[gap] if gap < 4 else 5
    if gap <= 1 and hi < 10:
        score += 1
    return math.ceil(score)
