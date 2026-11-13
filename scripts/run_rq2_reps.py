#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ2 重复采样：每组每案例 5 次，用于把组间差异和采样噪声分开。

与单次版（run_rq2.py）的区别
  - 每个 (案例, 组) 采 5 次，按「轮次 → 案例 → 组」的顺序穿插执行，
    避免同一提示连续命中缓存
  - 每次执行回放两遍，两次判定一致才记为成功；不一致记为 unstable 并单列
  - 报出每组翻转率与 Wilson 95% 区间

预算：调用上限 120 次、费用上限 0.20 美元、时间上限 1 小时。

输出
  audit_v1/rq2_reps.jsonl
  audit_v1/rq2_reps_summary.json
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa
import run_rq2 as Q  # noqa
import run_verify as R  # noqa

OUT = os.path.expanduser('~/stc/audit_v1')
REPS = 5
MAX_CALLS = 120
COST_CAP = 0.20


def ask_retry(prompt, tries=6):
    """网络抖动时指数退避重试；失败不消耗调用预算。"""
    last = None
    for k in range(tries):
        try:
            return Q.ask(prompt)
        except Exception as e:
            last = e
            time.sleep(min(30, 2 ** (k + 1)))
    raise last


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    cases, nh, ns = Q.pick_cases()
    print('案例 %d（等级门池 %d / 未登录池 %d），每组重复 %d 次' % (len(cases), nh, ns, REPS))

    ctx = {}
    for cid in cases:
        ev = json.load(open(os.path.join(Q.CASES, cid, 'evidence.json'), encoding='utf-8'))
        ctx[cid] = {"msgs": ev['messages'], "tgt": ev['target_msg_index'],
                    "gate": ev['failure']['gate_line'],
                    "op": ev['failure'].get('operator'),
                    "items": E.make_items(ev['messages'])}
        for g in Q.GROUPS:
            p = os.path.join(Q.PACKS, cid, g + '.md')
            ctx[cid][g] = open(p, encoding='utf-8').read()

    runs, calls, cost, fails = [], 0, 0.0, 0
    t0 = time.time()
    stop = False
    for rep in range(REPS):
        if stop:
            break
        for cid in cases:
            if stop:
                break
            for g in Q.GROUPS:
                if calls >= MAX_CALLS or cost >= COST_CAP or time.time() - t0 > 3600:
                    print('预算触顶，停止')
                    stop = True
                    break
                c = ctx[cid]
                try:
                    txt, dt, tin, tout = ask_retry(c[g])
                except Exception as e:
                    # 网络失败不算调用、不记入结果，只记错误日志
                    fails += 1
                    runs.append({"case": cid, "group": g, "rep": rep,
                                 "error": str(e)[:200]})
                    if fails > 20:
                        print('连续失败过多，停止')
                        stop = True
                        break
                    continue
                calls += 1
                cost += tin * Q.IN_PRICE + tout * Q.OUT_PRICE
                try:
                    obj = json.loads(txt[txt.find('{'):txt.rfind('}') + 1])
                    raw = obj.get('actions') if isinstance(obj, dict) else obj
                    acts = R.normalize_actions(raw or [])
                except Exception:
                    runs.append({"case": cid, "group": g, "rep": rep,
                                 "parse_error": True, "raw": txt[:300],
                                 "tokens_in": tin, "tokens_out": tout})
                    continue

                flips = []
                for k in range(2):
                    ni, b = E.apply_actions(c['items'], acts)
                    res = E.replay(ni, b, False, 'rq2r_%s_%s_%d_%d' % (
                        cid.replace(':', '_'), g, rep, k))
                    q_, r_, _ = E.judge(res, ni, c['tgt'], c['gate'], False)
                    flips.append(r_ == 'target_branch_flipped')
                runs.append({"case": cid, "group": g, "rep": rep,
                             "gate_op": c['op'], "actions": acts,
                             "n_edits": len(acts),
                             "flip1": flips[0], "flip2": flips[1],
                             "flipped": flips[0] and flips[1],
                             "unstable": flips[0] != flips[1],
                             "tokens_in": tin, "tokens_out": tout,
                             "latency": round(dt, 2)})
                print('  rep%d %-18s %-3s %-5s %s' % (
                    rep, cid, g, '翻转' if runs[-1]['flipped'] else '未翻转',
                    json.dumps(acts, ensure_ascii=False)[:90]))

    with open(os.path.join(OUT, 'rq2_reps.jsonl'), 'w', encoding='utf-8') as f:
        for x in runs:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')

    print()
    summary = {}
    for g in Q.GROUPS:
        rs = [x for x in runs if x.get('group') == g and 'flipped' in x]
        n = len(rs)
        k = sum(1 for x in rs if x['flipped'])
        lo, hi = wilson(k, n)
        summary[g] = {"n": n, "flips": k, "rate": round(k / n, 3) if n else 0,
                      "ci95": [round(lo, 3), round(hi, 3)],
                      "mean_edits": round(sum(x['n_edits'] for x in rs) / n, 2) if n else 0,
                      "parse_errors": sum(1 for x in runs
                                          if x.get('group') == g and x.get('parse_error'))}
        print('%-3s 翻转 %2d/%2d = %.0f%%  95%%CI [%.0f%%, %.0f%%]  平均动作 %.1f  解析失败 %d' % (
            g, k, n, 100 * k / n if n else 0, 100 * lo, 100 * hi,
            summary[g]['mean_edits'], summary[g]['parse_errors']))
    summary['calls'] = calls
    summary['est_cost_usd'] = round(cost, 4)
    summary['elapsed_s'] = round(time.time() - t0)
    json.dump(summary, open(os.path.join(OUT, 'rq2_reps_summary.json'), 'w',
                            encoding='utf-8'), ensure_ascii=False, indent=1)
    print('调用 %d 次，估算 $%.4f，用时 %.0f 秒' % (calls, cost, time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
