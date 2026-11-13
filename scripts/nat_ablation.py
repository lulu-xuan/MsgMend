#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自然案例上的三种修法对比，写入者来自自动采集的来源记录。

V1  无身份，冻结规则的原始形态
      `<`  权限等级门 → 改**第一次**登录
      `==0` 未登录门 → 在目标前**插入**一条参考登录
V1b 无身份的暴力基线
      `<`  权限等级门 → 改**全部**登录
      `==0` 未登录门 → 同 V1（插登录已是最直接做法）
V2  有身份，只改来源记录指出的那条消息
      `<`  改包含写入者的那一对 USER/PASS
      `==0` 若写入者是 USER，把它改成合法登录；否则改对应 PASS

每项跑两次，两次判定必须一致才算可重现。
"""

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa
import run_verify as R  # noqa

CASES = os.path.expanduser('~/stc/cases_nat')
OUT = os.path.expanduser('~/stc/audit_v1')


def pairs(msgs):
    out, pending = [], None
    for i, m in enumerate(msgs):
        u = m.upper()
        if u.startswith('USER '):
            pending = i
        elif u.startswith('PASS ') and pending is not None:
            out.append((pending, i))
            pending = None
    return out


def rep(i, t):
    return {"op": "replace_message", "index": i, "message": t}


def act(msgs, ev, acct, pw):
    f = ev['failure']
    prov = ev['state_provenance']
    tgt = ev['target_msg_index']
    wid = prov['last_write']['message_id']
    ps = pairs(msgs)
    v1, v1b, v2 = [], [], []
    if f['operator'] == '<':
        if ps:
            v1 = [rep(ps[0][0], 'USER ' + acct), rep(ps[0][1], 'PASS ' + pw)]
        for u, p in ps:
            v1b += [rep(u, 'USER ' + acct), rep(p, 'PASS ' + pw)]
        for u, p in ps:
            if u <= wid <= p:
                v2 = [rep(u, 'USER ' + acct), rep(p, 'PASS ' + pw)]
    else:
        v1 = [{"op": "insert_before", "index": tgt, "message": "USER anonymous"},
              {"op": "insert_before", "index": tgt, "message": "PASS x"}]
        v1b = list(v1)
        # 用来源记录里的写入位置判断读写的是 USER 还是 PASS，
        # 不看消息文本（fuzz 变异的文本可能带前导垃圾）
        site = (prov.get('last_write') or {}).get('site') or ''
        w = ''
        if 'ftpUSER' in site:
            w = 'USER '
        elif 'ftpPASS' in site:
            w = 'PASS '
        if w.startswith('USER '):
            # 来源指出写 Access 的是这条 USER；但只改 USER 不够，
            # 还必须补上被它丢掉的 PASS，才算完成登录
            v2 = [rep(wid, 'USER anonymous')]
            if wid + 1 < len(msgs):
                v2.append({"op": "insert_before", "index": wid + 1, "message": "PASS x"})
        elif w.startswith('PASS '):
            v2 = [rep(wid, 'PASS x')]
    return {"V1": v1, "V1b": v1b, "V2": v2}


def main():
    accts = R.load_accounts()
    acct = max(accts, key=lambda k: accts[k][0])
    pw = accts[acct][1] or acct

    rows = []
    for d in sorted(os.listdir(CASES)):
        p = os.path.join(CASES, d, 'evidence.json')
        if not os.path.exists(p):
            continue
        ev = json.load(open(p, encoding='utf-8'))
        msgs = ev['messages']
        tgt = ev['target_msg_index']
        gate = ev['failure']['gate_line']
        items = E.make_items(msgs)
        acts = act(msgs, ev, acct, pw)

        rec = {"case": d, "gate_op": ev['failure']['operator'],
               "gate_line": gate, "writer_msg": ev['state_provenance']['last_write']['message_id'],
               "target_msg": tgt}
        for name, a in acts.items():
            flips, quals, last = [], [], ''
            for k in range(2):
                ni, b = E.apply_actions(items, a)
                res = E.replay(ni, b, False, 'nat_%s_%s_%d' % (
                    name, d.replace(':', '_')[:24], k))
                # 判据用的是稳定消息 ID，插入不会改变目标身份
                q, r, _ = E.judge(res, ni, tgt, gate, False)
                flips.append(r == 'target_branch_flipped')
                quals.append(q)
                last = res['responses'][tgt] if tgt < len(res['responses']) else ''
            rec[name] = {"actions": a, "n_edits": len(a),
                         "flip": all(flips), "reproducible": flips[0] == flips[1],
                         "quality": quals[0], "target_response": last}
        rows.append(rec)
        print('%-22s %-3s 目标[%2d] 写入[%2d]  V1=%-5s V1b=%-5s V2=%-5s' % (
            d, rec['gate_op'], tgt, rec['writer_msg'],
            '成功' if rec['V1']['flip'] else '失败',
            '成功' if rec['V1b']['flip'] else '失败',
            '成功' if rec['V2']['flip'] else '失败'))

    json.dump(rows, open(os.path.join(OUT, 'nat_ablation.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    print()
    n = len(rows)
    print('案例 %d' % n)
    for k in ('V1', 'V1b', 'V2'):
        print('  %-4s 成功 %d/%d  平均编辑数 %.1f' % (
            k, sum(1 for r in rows if r[k]['flip']), n,
            sum(r[k]['n_edits'] for r in rows) / max(n, 1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
