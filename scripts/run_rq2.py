#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2：来源信息对照。E0–E3 四组，每组同一案例、同一提示骨架。

预算硬约束（本轮已确认）
    调用上限 24 次；费用上限 0.30 美元；时间上限 1 小时。
    任一触顶即停，已完成的记录照常写出。

每组可见信息
    E0  基线信息 + 失败分支的比较操作数
    E1  E0 + 写入位置/旧新值，无消息身份
    E2  E1 + 自动采集的消息身份、事件先后、值来源
    E3  E2 + 人工补充说明（自然案例没有，等同 E2，单列）

输出
    audit_v1/rq2_runs.jsonl   每次一行
    audit_v1/rq2_summary.json 分组汇总
"""

import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa
import run_verify as R  # noqa

CASES = os.path.expanduser('~/stc/cases_nat')
PACKS = os.path.expanduser('~/stc/packs_nat')
OUT = os.path.expanduser('~/stc/audit_v1')
KEY = open(os.path.expanduser('~/.dskey'), encoding='utf-8').read().strip()
MODEL = 'deepseek-chat'
GROUPS = ['E0', 'E1', 'E2', 'E3']
MAX_CALLS = 24
COST_CAP = 0.30
IN_PRICE, OUT_PRICE = 0.28 / 1e6, 0.42 / 1e6      # 美元/token


def ask(prompt, max_tokens=700):
    body = json.dumps({"model": MODEL, "temperature": 0,
                       "max_tokens": max_tokens,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read().decode())
    u = d.get("usage") or {}
    return (d["choices"][0]["message"]["content"], time.time() - t0,
            u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def pick_cases(seed=20261105):
    """按 protocol.md 第三节固定规则选例：每族 3 条，种子固定。

    只读 evidence.json 里的 operator 字段，不读任何修法结果，
    避免按模型胜负挑案例。
    """
    import random
    hard, soft = [], []
    for d in sorted(os.listdir(CASES)):
        p = os.path.join(CASES, d, 'evidence.json')
        if not os.path.exists(p):
            continue
        ev = json.load(open(p, encoding='utf-8'))
        (hard if (ev['failure'].get('operator') == '<') else soft).append(d)
    rng = random.Random(seed)
    picked = (rng.sample(hard, min(3, len(hard)))
              + rng.sample(soft, min(3, len(soft))))
    return sorted(picked), len(hard), len(soft)


def main():
    cases, nh, ns = pick_cases()
    print('候选：等级门 %d 条，其它 %d 条；本轮取 %d 条' % (nh, ns, len(cases)))
    if len(cases) < len(GROUPS):
        print('案例不足，停止')
        return 1

    runs, calls, cost = [], 0, 0.0
    t_start = time.time()
    for cid in cases:
        ev = json.load(open(os.path.join(CASES, cid, 'evidence.json'), encoding='utf-8'))
        msgs = ev['messages']
        tgt = ev['target_msg_index']
        gate = ev['failure']['gate_line']
        items = E.make_items(msgs)
        for g in GROUPS:
            p = os.path.join(PACKS, cid, g + '.md')
            if not os.path.exists(p):
                continue
            if calls >= MAX_CALLS or cost >= COST_CAP or time.time() - t_start > 3600:
                print('预算触顶，停止')
                break
            prompt = open(p, encoding='utf-8').read()
            ph = hashlib.sha256(prompt.encode()).hexdigest()[:16]
            try:
                txt, dt, tin, tout = ask(prompt)
            except Exception as e:
                runs.append({"case": cid, "group": g, "error": str(e)[:200]})
                calls += 1
                continue
            calls += 1
            cost += tin * IN_PRICE + tout * OUT_PRICE

            try:
                obj = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
                raw = obj.get('actions') if isinstance(obj, dict) else obj
                acts = R.normalize_actions(raw if raw is not None else [])
            except Exception:
                acts = None
            if acts is None:
                runs.append({"case": cid, "group": g, "prompt_sha": ph,
                             "raw": txt[:400], "parse_error": True,
                             "tokens_in": tin, "tokens_out": tout, "latency": dt})
                continue

            ni, b = E.apply_actions(items, acts)
            res = E.replay(ni, b, False, 'rq2_%s_%s' % (cid[:16], g))
            q, r, d = E.judge(res, ni, tgt, gate, False)
            runs.append({"case": cid, "group": g, "prompt_sha": ph,
                         "gate_op": ev['failure'].get('operator'),
                         "actions": acts, "n_edits": len(acts),
                         "quality": q, "result": r, "detail": d,
                         "flipped": r == 'target_branch_flipped',
                         "tokens_in": tin, "tokens_out": tout,
                         "latency": round(dt, 2)})
            print('  %-18s %-3s 动作 %d  -> %-24s %s' % (
                cid, g, len(acts), r, '翻转' if runs[-1]['flipped'] else ''))
        if calls >= MAX_CALLS or cost >= COST_CAP:
            break

    with open(os.path.join(OUT, 'rq2_runs.jsonl'), 'w', encoding='utf-8') as f:
        for x in runs:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')

    import collections
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for x in runs:
        if 'flipped' not in x:
            continue
        a = agg[x['group']]
        a[0] += 1 if x['flipped'] else 0
        a[1] += 1
        a[2] += x['n_edits']
    print()
    for g in GROUPS:
        if g in agg:
            a = agg[g]
            print('%-3s 翻转 %d/%d  平均动作数 %.1f' % (g, a[0], a[1], a[2] / a[1]))
    print('调用 %d 次，估算费用 $%.4f，用时 %.0f 秒' % (calls, cost, time.time() - t_start))
    json.dump({"calls": calls, "est_cost_usd": round(cost, 4),
               "by_group": {g: agg[g] for g in agg}},
              open(os.path.join(OUT, 'rq2_summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
