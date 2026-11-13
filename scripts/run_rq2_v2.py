#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型实验 v2：冻结提示，15 个案例，4 组证据，每组 3 次。

判据在序列层面：模型给出的修补动作有没有落在真正写入状态的那条消息上
（含其前后各一条配对消息），不需要重放。

规则见 汇报&指导相关/6/protocol_v2.md，在任何调用之前写定。

输出
    ~/stc/audit_v1/rq2_v2.jsonl
    ~/stc/audit_v1/rq2_v2_summary.json
"""

import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_rq2 as Q  # noqa
import run_verify as R  # noqa

CASES = os.path.expanduser('~/stc/cases_nat')
PACKS = os.path.expanduser('~/stc/packs_nat')
OUT = os.path.expanduser('~/stc/audit_v1')
SEED = 20261108
N_HARD, N_SOFT = 7, 8
REPS = 3
MAX_CALLS = 180
COST_CAP = 0.20


def select():
    hard, soft = [], []
    for d in sorted(os.listdir(CASES)):
        p = os.path.join(CASES, d, 'evidence.json')
        if not os.path.exists(p):
            continue
        ev = json.load(open(p, encoding='utf-8'))
        (hard if ev['failure'].get('operator') == '<' else soft).append(d)
    rng = random.Random(SEED)
    h = rng.sample(hard, min(N_HARD, len(hard)))
    s = rng.sample(soft, min(N_SOFT, len(soft)))
    # 族内按抽取顺序切分：前段开发集，后段留出集
    split = {}
    for x in h[:4] + s[:5]:
        split[x] = 'dev'
    for x in h[4:] + s[5:]:
        split[x] = 'holdout'
    return sorted(h + s), split


def hit(actions, wid):
    idx = {a.get('index') for a in actions if isinstance(a.get('index'), int)}
    return bool(idx & {wid - 1, wid, wid + 1})


def main():
    cases, split = select()
    print('案例 %d（开发 %d / 留出 %d）' % (
        len(cases), sum(1 for v in split.values() if v == 'dev'),
        sum(1 for v in split.values() if v == 'holdout')))
    for c in cases:
        print('  %-20s %s' % (c, split[c]))

    runs, calls, cost, t0 = [], 0, 0.0, time.time()
    for rep in range(REPS):
        for cid in cases:
            ev = json.load(open(os.path.join(CASES, cid, 'evidence.json'), encoding='utf-8'))
            wid = ev['state_provenance']['last_write']['message_id']
            for g in Q.GROUPS:
                if calls >= MAX_CALLS or cost >= COST_CAP or time.time() - t0 > 7200:
                    print('预算触顶')
                    break
                p = os.path.join(PACKS, cid, g + '.md')
                if not os.path.exists(p):
                    continue
                prompt = open(p, encoding='utf-8').read()
                try:
                    txt, dt, tin, tout = Q.ask(prompt)
                except Exception as e:
                    runs.append({"case": cid, "group": g, "rep": rep,
                                 "error": str(e)[:160]})
                    continue
                calls += 1
                cost += tin * Q.IN_PRICE + tout * Q.OUT_PRICE
                try:
                    obj = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
                    raw = obj.get('actions') if isinstance(obj, dict) else obj
                    acts = R.normalize_actions(raw or [])
                except Exception:
                    runs.append({"case": cid, "group": g, "rep": rep,
                                 "parse_error": True, "raw": txt[:200],
                                 "tokens_in": tin, "tokens_out": tout})
                    continue
                runs.append({
                    "case": cid, "group": g, "rep": rep, "split": split[cid],
                    "gate_op": ev['failure'].get('operator'),
                    "writer_msg": wid, "actions": acts, "n_edits": len(acts),
                    "hit": hit(acts, wid),
                    "tokens_in": tin, "tokens_out": tout, "latency": round(dt, 2),
                })

    with open(os.path.join(OUT, 'rq2_v2.jsonl'), 'w', encoding='utf-8') as f:
        for x in runs:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')

    def agg(rows):
        n = len(rows)
        return {"n": n, "hit": sum(1 for r in rows if r.get('hit')),
                "rate": round(sum(1 for r in rows if r.get('hit')) / n, 3) if n else 0}

    print()
    summary = {}
    for scope in ('all', 'dev', 'holdout'):
        base = [r for r in runs if 'hit' in r and (scope == 'all' or r['split'] == scope)]
        print('== %s (%d 次)' % (scope, len(base)))
        summary[scope] = {}
        for g in Q.GROUPS:
            rs = [r for r in base if r['group'] == g]
            a = agg(rs)
            summary[scope][g] = a
            print('   %s 命中 %2d/%2d = %3.0f%%' % (g, a['hit'], a['n'], 100 * a['rate']))

    summary['calls'] = calls
    summary['est_cost_usd'] = round(cost, 4)
    summary['elapsed_s'] = round(time.time() - t0)
    summary['parse_errors'] = sum(1 for r in runs if r.get('parse_error'))
    summary['errors'] = sum(1 for r in runs if r.get('error'))
    json.dump(summary, open(os.path.join(OUT, 'rq2_v2_summary.json'), 'w',
                            encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n调用 %d 次，估算 $%.4f，用时 %.0f 秒；解析失败 %d，接口错误 %d' % (
        calls, cost, time.time() - t0, summary['parse_errors'], summary['errors']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
