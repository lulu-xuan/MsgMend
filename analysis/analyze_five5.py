# -*- coding: utf-8 -*-
"""五臂对照 × 5 次：Baseline / 随机 / V1 / V1b / V2。"""

import csv
import json
import os

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAIRS = os.path.join(D, 'exp_pairs_2026-11-07')
PAIRS2 = os.path.join(D, 'exp_pairs2_2026-11-12')
RAND = os.path.join(D, 'exp_random_2026-11-08')
VAR = os.path.join(D, 'exp_variants_2026-11-08')
REPS = [1, 2, 3, 4, 5]

ARMS = [
    ('base', 'Baseline（未修改）', '#2a78d6'),
    ('rand', '随机修改（改的条数相同）', '#9a9a94'),
    ('v1b', 'V1b（把全部登录都改一遍）', '#1baf7a'),
    ('v1', 'V1（只改第一次登录）', '#8a6fd8'),
    ('ours', 'Ours = V2（按采集到的信息改）', '#eb6834'),
]


def d_of(arm, rep):
    if arm in ('base', 'ours'):
        return os.path.join(PAIRS if rep <= 3 else PAIRS2, 'out-%s-r%d' % (arm, rep))
    if arm == 'rand':
        return os.path.join(RAND, 'out-rnd-r%d' % rep)
    return os.path.join(VAR, 'out-%s-r%d' % (arm, rep))


def read_cov(d):
    rows = []
    try:
        with open(os.path.join(d, 'cov_over_time.csv'), encoding='utf-8', errors='replace') as f:
            for r in csv.DictReader(f):
                t = (r.get('Time') or '').strip()
                if not t:
                    continue
                try:
                    rows.append((float(t), float(r['b_abs']), float(r['l_abs'])))
                except (TypeError, ValueError):
                    continue
    except OSError:
        return []
    if not rows:
        return []
    t0 = rows[0][0]
    return [(t - t0, b, l) for t, b, l in rows]


def at(c, m):
    v = None
    for t, b, _ in c:
        if t / 60.0 <= m:
            v = b
        else:
            break
    return v


runs = []
for key, lab, _ in ARMS:
    for rep in REPS:
        c = read_cov(d_of(key, rep))
        if c:
            runs.append({'arm': key, 'rep': rep, 'curve': c,
                         'b': c[-1][1], 'l': c[-1][2]})

by = {}
for r in runs:
    by.setdefault(r['arm'], []).append(r)


def mean(x):
    return sum(x) / len(x) if x else 0


def sd(x):
    if len(x) < 2:
        return 0
    m = mean(x)
    return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** 0.5


print('%-6s %s' % ('arm', ''.join('%7s' % ('r%d' % r) for r in REPS)))
for key, lab, _ in ARMS:
    rs = {r['rep']: r['b'] for r in by.get(key, [])}
    print('%-6s' % key + ''.join('%7.0f' % rs[r] if r in rs else '%7s' % '-' for r in REPS))

print()
base_mean = mean([r['b'] for r in by['base']])
print('%-6s %-22s %8s %8s %9s' % ('arm', 'label', 'mean', 'sd', 'vs base'))
summary = {}
for key, lab, _ in ARMS:
    xs = [r['b'] for r in by.get(key, [])]
    if not xs:
        continue
    summary[key] = {'mean': round(mean(xs), 1), 'sd': round(sd(xs), 1),
                    'n': len(xs), 'runs': xs}
    print('%-6s %-22s %8.1f %8.1f %+8.1f%%' % (
        key, lab, mean(xs), sd(xs), 100 * (mean(xs) - base_mean) / base_mean))


def a12(a, b):
    w = t = n = 0
    for x in by.get(a, []):
        for y in by.get(b, []):
            n += 1
            if x['b'] > y['b']:
                w += 1
            elif x['b'] == y['b']:
                t += 1
    return (w + 0.5 * t) / n if n else None


print()
A = {}
for a, b in (('ours', 'v1'), ('ours', 'v1b'), ('ours', 'rand'), ('ours', 'base'),
             ('v1', 'rand'), ('v1b', 'rand'), ('rand', 'base')):
    v = a12(a, b)
    if v is not None:
        A['%s>%s' % (a, b)] = round(v, 3)
        print('Â12(%-4s > %-4s) = %.3f' % (a, b, v))

times = [10, 20, 30, 40, 50, 60]
print()
print('%-6s' % 'min' + ''.join('%7d' % t for t in times))
tab = {}
for key, _, _ in ARMS:
    vals = []
    for t in times:
        xs = [at(r['curve'], t) for r in by.get(key, [])]
        xs = [x for x in xs if x is not None]
        vals.append(round(mean(xs), 1) if xs else None)
    tab[key] = vals
    print('%-6s' % key + ''.join('%7.0f' % (v or 0) for v in vals))

json.dump({'summary': summary, 'A12': A, 'at_time': tab},
          open(os.path.join(VAR, 'five5.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False
SURF, INK2, GRID = '#fcfcfb', '#52514e', '#e3e2dd'

fig, ax = plt.subplots(figsize=(9.0, 4.8))
ax.set_facecolor(SURF)
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
for s in ('left', 'bottom'):
    ax.spines[s].set_color(GRID)
ax.yaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
ax.tick_params(colors=INK2)
for key, lab, col in ARMS:
    for r in by.get(key, []):
        ax.plot([p[0] / 60 for p in r['curve']], [p[1] for p in r['curve']],
                color=col, alpha=0.15, linewidth=0.9)
for key, lab, col in ARMS:
    xs, ys = [], []
    for t in range(0, 61):
        vs = [at(r['curve'], t) for r in by.get(key, [])]
        vs = [v for v in vs if v is not None]
        if vs:
            xs.append(t)
            ys.append(mean(vs))
    ax.plot(xs, ys, color=col, linewidth=2.4, label=lab)
    ax.annotate('%.0f' % ys[-1], (xs[-1], ys[-1]), textcoords='offset points',
                xytext=(6, -3), fontsize=9, color=col, weight='bold')
ax.set_xlabel('运行时间（分钟）', fontsize=9.5, color=INK2)
ax.set_ylabel('累计覆盖分支数 b_abs', fontsize=9.5, color=INK2)
ax.set_xlim(0, 65)
ax.legend(frameon=False, fontsize=9, loc='lower right')
p = os.path.join(VAR, 'fig_five5.png')
fig.savefig(p, dpi=200, bbox_inches='tight', facecolor=SURF)
print('\n图 ->', p)
