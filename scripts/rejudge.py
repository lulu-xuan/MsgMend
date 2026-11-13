#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用统一评测器重判已有结果：不重新请求模型，只重放保存下来的动作。

输入
    verify_matrix_165.jsonl（165 条，含 actions）
    ~/stc/cases/*/evidence.json（消息、目标消息、gate_line）

输出
    audit_v1/rejudged.jsonl  每条的原判定、新判定、执行质量、事件日志路径
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa

SRC = os.path.expanduser('~/stc/verify_matrix_165.jsonl')
CASES = os.path.expanduser('~/stc/cases')
OUT = os.path.expanduser('~/stc/audit_v1')


def load_evidence():
    idx = {}
    for d in os.listdir(CASES):
        p = os.path.join(CASES, d, 'evidence.json')
        if os.path.exists(p):
            ev = json.load(open(p, encoding='utf-8'))
            idx[ev['case_id']] = ev
    return idx


def main():
    os.makedirs(OUT, exist_ok=True)
    evs = load_evidence()

    recs = [json.loads(l) for l in open(SRC, encoding='utf-8') if l.strip()]
    print('待重判: %d 条' % len(recs))

    out = []
    old_ok = new_flip = 0
    q_count = {}
    for k, r in enumerate(recs, 1):
        cid = r['case']
        ev = evs.get(cid)
        if ev is None:
            out.append({**r, 'quality': 'ambiguous', 'result': 'target_not_reached',
                        'detail': 'evidence_missing'})
            continue
        msgs = ev.get('messages') or ev.get('failed_sequence') or []
        gate_line = (ev.get('failure') or {}).get('gate_line')
        is_rtsp = not cid[0] in ('A', 'C')
        tgt = ev.get('target_msg_index', len(msgs) - 1)

        items = E.make_items(msgs)
        new_items, binds = E.apply_actions(items, r.get('actions') or [])
        res = E.replay(new_items, binds, is_rtsp,
                       '%s_%s_r%s' % (cid[:20], r['group'], r['rep']))
        q, res_r, detail = E.judge(res, new_items, tgt, gate_line, is_rtsp)

        flipped = (res_r == 'target_branch_flipped')
        old_ok += 1 if r.get('ok') else 0
        new_flip += 1 if flipped else 0
        q_count[q] = q_count.get(q, 0) + 1

        out.append({
            "case": cid, "group": r['group'], "rep": r['rep'],
            "old_ok": bool(r.get('ok')), "old_note": r.get('note'), "old_after": r.get('after'),
            "actions": r.get('actions'),
            "quality": q, "result": res_r, "detail": detail, "flipped": flipped,
            "responses": res.get('responses'), "trace": res.get('trace'),
        })
        if k % 25 == 0:
            print('  %d/%d' % (k, len(recs)))

    with open(os.path.join(OUT, 'rejudged.jsonl'), 'w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print()
    print('原判定成功: %d / %d' % (old_ok, len(out)))
    print('重判翻转:   %d / %d' % (new_flip, len(out)))
    print('执行质量分布:', q_count)

    # 分组对比
    import collections
    agg = collections.defaultdict(lambda: {'old': 0, 'new': 0, 'n': 0})
    for r in out:
        a = agg[r['group']]
        a['n'] += 1
        a['old'] += 1 if r.get('old_ok') else 0
        a['new'] += 1 if r.get('flipped') else 0
    print()
    print('%-6s %-14s %-14s' % ('组', '原判定', '重判翻转'))
    for g in sorted(agg):
        a = agg[g]
        print('%-6s %-14s %-14s' % (g, '%d/%d' % (a['old'], a['n']),
                                    '%d/%d' % (a['new'], a['n'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
