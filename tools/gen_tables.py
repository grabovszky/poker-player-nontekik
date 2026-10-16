"""Generate bot/data/preflop.json with our own evaluator (fixed seed).
hu: 169x169 heads-up equity matrix (class vs class)
t1: equity vs N random opponents, N = 1..5
order: class indices sorted by t1[N=1], best first
Usage: python tools/gen_tables.py [hu_trials] [multi_trials]"""
import json
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from bot.cards import class_combos  # noqa: E402
from bot.evaluator import RK, SK, NONFLUSH, flush_value  # noqa: E402

COMBOS = [class_combos(i) for i in range(169)]


def _val(cards):
    rk = 0
    sk = 0
    for c in cards:
        rk += RK[c]
        sk += SK[c]
    if (sk + 0x3333) & 0x8888:
        return flush_value(cards, sk)
    return NONFLUSH[rk]


def _board(rng, used, n):
    out = []
    while len(out) < n:
        c = int(rng() * 52)
        if not used >> c & 1:
            used |= 1 << c
            out.append(c)
    return out


def hu_row(args):
    i, trials = args
    rnd = random.Random(1000 + i)
    rng = rnd.random
    row = []
    for j in range(169):
        if j < i:
            row.append(None)
            continue
        hc, vc = COMBOS[i], COMBOS[j]
        win = 0.0
        n = 0
        for _ in range(trials):
            h = hc[int(rng() * len(hc))]
            v = vc[int(rng() * len(vc))]
            if h[0] in v or h[1] in v:
                continue
            used = (1 << h[0]) | (1 << h[1]) | (1 << v[0]) | (1 << v[1])
            b = _board(rng, used, 5)
            a = _val([h[0], h[1]] + b)
            c = _val([v[0], v[1]] + b)
            win += 1.0 if a > c else (0.5 if a == c else 0.0)
            n += 1
        row.append(win / n if n else 0.5)
    return i, row


def multi_row(args):
    i, trials = args
    rnd = random.Random(5000 + i)
    rng = rnd.random
    hc = COMBOS[i]
    out = []
    for nopp in range(2, 6):
        win = 0.0
        for _ in range(trials):
            h = hc[int(rng() * len(hc))]
            used = (1 << h[0]) | (1 << h[1])
            cards = _board(rng, used, 5 + 2 * nopp)
            b = cards[:5]
            a = _val([h[0], h[1]] + b)
            best = 0
            ties = 0
            for k in range(nopp):
                v = _val(cards[5 + 2 * k:7 + 2 * k] + b)
                if v > best:
                    best, ties = v, 1
                elif v == best:
                    ties += 1
            if a > best:
                win += 1
            elif a == best:
                win += 1.0 / (ties + 1)
        out.append(win / trials)
    return i, out


def main():
    hu_trials = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    multi_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    with Pool() as pool:
        hu = [[0.5] * 169 for _ in range(169)]
        for i, row in pool.imap_unordered(hu_row, [(i, hu_trials) for i in range(169)]):
            for j, e in enumerate(row):
                if e is not None:
                    hu[i][j] = e
                    hu[j][i] = 1.0 - e
        for i in range(169):
            hu[i][i] = 0.5
        multi = dict(pool.imap_unordered(multi_row, [(i, multi_trials) for i in range(169)]))
    weights = [len(c) for c in COMBOS]
    tot = float(sum(weights))
    t1 = []
    for i in range(169):
        e1 = sum(hu[i][j] * weights[j] for j in range(169)) / tot
        t1.append([round(e1, 4)] + [round(x, 4) for x in multi[i]])
    order = sorted(range(169), key=lambda k: -t1[k][0])
    out = {'order': order, 't1': t1, 'hu': [[round(x, 4) for x in r] for r in hu]}
    path = os.path.join(os.path.dirname(__file__), '..', 'bot', 'data', 'preflop.json')
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    from bot.cards import class_name
    for nm in ('AA', 'KK', 'AKs', 'AKo', '72o', '32o'):
        k = next(i for i in range(169) if class_name(i) == nm)
        print(nm, t1[k])
    print('AA vs KK', hu[0][14])


if __name__ == '__main__':
    main()
