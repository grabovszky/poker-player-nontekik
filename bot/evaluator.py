"""7-card evaluator: rank-count key -> precomputed value, flush via suit-count nibbles.
Value = category << 20 | 5 kicker nibbles; plain int comparison ranks hands."""
RK = [1 << (3 * (c >> 2)) for c in range(52)]
SK = [1 << (4 * (c & 3)) for c in range(52)]

STRAIGHT = [-1] * 8192
for _m in range(8192):
    for _h in range(12, 3, -1):
        if (_m >> (_h - 4)) & 31 == 31:
            STRAIGHT[_m] = _h
            break
    else:
        if _m & 0b1000000001111 == 0b1000000001111:
            STRAIGHT[_m] = 3


def _val(cat, ranks):
    v = cat
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def _eval_counts(counts):
    present = [r for r in range(12, -1, -1) if counts[r]]
    mask = 0
    for r in present:
        mask |= 1 << r
    quads = [r for r in present if counts[r] == 4]
    trips = [r for r in present if counts[r] == 3]
    pairs = [r for r in present if counts[r] == 2]
    if quads:
        q = quads[0]
        return _val(7, [q, max(r for r in present if r != q)])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        return _val(6, [t, max(trips[1:] + pairs)])
    if STRAIGHT[mask] >= 0:
        return _val(4, [STRAIGHT[mask]])
    if trips:
        t = trips[0]
        return _val(3, [t] + [r for r in present if r != t][:2])
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return _val(2, [p1, p2, max(r for r in present if r != p1 and r != p2)])
    if pairs:
        p = pairs[0]
        return _val(1, [p] + [r for r in present if r != p][:3])
    return _val(0, present[:5])


NONFLUSH = {}


def _build(counts, r, left):
    if r == 13:
        if 5 <= sum(counts) <= 7:
            key = 0
            for i in range(13):
                key += counts[i] << (3 * i)
            NONFLUSH[key] = _eval_counts(counts)
        return
    for k in range(min(4, left) + 1):
        counts[r] = k
        _build(counts, r + 1, left - k)
    counts[r] = 0


_build([0] * 13, 0, 7)

FLUSH = [0] * 8192
for _m in range(8192):
    if bin(_m).count('1') >= 5:
        if STRAIGHT[_m] >= 0:
            FLUSH[_m] = _val(8, [STRAIGHT[_m]])
        else:
            FLUSH[_m] = _val(5, [r for r in range(12, -1, -1) if _m >> r & 1][:5])


def flush_value(cards, sk):
    for s in range(4):
        if (sk >> (4 * s)) & 15 >= 5:
            m = 0
            for c in cards:
                if c & 3 == s:
                    m |= 1 << (c >> 2)
            return FLUSH[m]
    return 0


def evaluate(cards):
    rk = 0
    sk = 0
    for c in cards:
        rk += RK[c]
        sk += SK[c]
    if (sk + 0x3333) & 0x8888:
        return flush_value(cards, sk)
    return NONFLUSH[rk]


def category(value):
    return value >> 20
