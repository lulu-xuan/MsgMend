# -*- coding: utf-8 -*-
"""配对覆盖率实验：第 1–5 次合并分析（ChatAFL 来源，36 对）。

数据分布
    exp_pairs_2026-11-07/out-{base,ours}-r{1,2,3}    第一批
    exp_pairs2/out-{base,ours}-r{4,5}                第二批（本脚本会把它们并入）
"""

import csv
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
P2 = os.path.join(HERE, '..', 'exp_pairs2_2026-11-12')
REPS = [1, 2, 3, 4, 5]
ARMS = ['base', 'ours']
LAB = {'base': 'Baseline（未修改的原始序列）', 'ours': 'Ours（把初始序列修好之后再跑）'}
SURF, INK2, GRID = '#fcfcfb', '#52514e', '#e3e2dd'
COL = {'base': '#2a78d6', 'ours': '#eb6834'}


def dir_of(arm, rep):
    if rep <= 3:
        return os.path.join(HERE, 'out-%s-r%d' % (arm, rep))
    return os.path.join(P2, 'out-%s-r%d' % (arm, rep))


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
for arm in ARMS:
    for rep in REPS:
        c = read_cov(dir_of(arm, rep))
        if not c:
            continue
        runs.append({'arm': arm, 'rep': rep, 'curve': c,
                     'final_b': c[-1][1], 'final_l': c[-1][2]})

by = {}
for r in runs:
    by.setdefault(r['arm'], []).append(r)

print('%-6s %-4s %8s %8s' % ('arm', 'run', 'b_abs', 'l_abs'))
for r in runs:
    print('%-6s r%-3d %8.0f %8.0f' % (r['arm'], r['rep'], r['final_b'], r['final_l']))


def mean(xs):
    return sum(xs) / len(xs) if xs else 0


def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


print()
for arm in ARMS:
    b = [r['final_b'] for r in by.get(arm, [])]
    l = [r['final_l'] for r in by.get(arm, [])]
    if not b:
        continue
    print('%-6s n=%d  b_abs %.1f ± %.1f（%s）  l_abs %.1f' % (
        arm, len(b), mean(b), sd(b), ', '.join('%.0f' % x for x in b), mean(l)))

wins = ties = n = 0
for o in by.get('ours', []):
    for b in by.get('base', []):
        n += 1
        if o['final_b'] > b['final_b']:
            wins += 1
        elif o['final_b'] == b['final_b']:
            ties += 1
a12 = (wins + 0.5 * ties) / n if n else 0
mb = mean([r['final_b'] for r in by['base']])
mo = mean([r['final_b'] for r in by['ours']])
print('\n提升 %.1f%%   Â12 = %.3f（%d 对运行）' % (100 * (mo - mb) / mb, a12, n))

times = [10, 20, 30, 40, 50, 60]
print()
print('%-6s' % 'min' + ''.join('%7d' % t for t in times))
tab = {}
for arm in ARMS:
    vals = []
    for t in times:
        xs = [at(r['curve'], t) for r in by[arm]]
        xs = [x for x in xs if x is not None]
        vals.append(round(mean(xs), 1) if xs else None)
    tab[arm] = vals
    print('%-6s' % arm + ''.join('%7.0f' % (v or 0) for v in vals))

json.dump({'runs': [{k: v for k, v in r.items() if k != 'curve'} for r in runs],
           'A12': round(a12, 3), 'pairs': n,
           'mean': {a: round(mean([r['final_b'] for r in by[a]]), 1) for a in ARMS if a in by},
           'sd': {a: round(sd([r['final_b'] for r in by[a]]), 1) for a in ARMS if a in by},
           'at_time': tab},
          open(os.path.join(HERE, 'pair5.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(figsize=(8.8, 4.5))
ax.set_facecolor(SURF)
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)
for s in ('left', 'bottom'):
    ax.spines[s].set_color(GRID)
ax.yaxis.grid(True, color=GRID, linewidth=0.8)
ax.set_axisbelow(True)
ax.tick_params(colors=INK2)
for arm in ARMS:
    for r in by[arm]:
        ax.plot([p[0] / 60 for p in r['curve']], [p[1] for p in r['curve']],
                color=COL[arm], alpha=0.22, linewidth=1.0)
for arm in ARMS:
    xs, ys = [], []
    for t in range(0, 61):
        vs = [at(r['curve'], t) for r in by[arm]]
        vs = [v for v in vs if v is not None]
        if vs:
            xs.append(t)
            ys.append(mean(vs))
    ax.plot(xs, ys, color=COL[arm], linewidth=2.4, label=LAB[arm])
    ax.annotate('%.0f' % ys[-1], (xs[-1], ys[-1]), textcoords='offset points',
                xytext=(6, -3), fontsize=9.5, color=COL[arm], weight='bold')
ax.set_xlabel('运行时间（分钟）', fontsize=9.5, color=INK2)
ax.set_ylabel('累计覆盖分支数 b_abs', fontsize=9.5, color=INK2)
ax.set_xlim(0, 65)
ax.legend(frameon=False, fontsize=9.5, loc='lower right')
p = os.path.join(HERE, 'fig_pair5.png')
fig.savefig(p, dpi=200, bbox_inches='tight', facecolor=SURF)
print('\n图 ->', p)
