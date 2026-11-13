#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在真实队列里找「消息身份决定修复位置」的案例。

要满足的自然条件
    1. 序列里有多于一次登录（USER/PASS 对）
    2. 某条权限命令被 gate 拒绝（taken=1）
    3. 该 gate 读到的 Access，最后一次写入来自**不是第一条**登录消息

这种序列下：
    V1 无身份 —— 把第一次登录改成高权限账号，后续匿名登录会把 Access 写回去，仍然失败
    V2 有身份 —— 按来源记录改真正写入的那次登录，分支翻转

用法
    python3 find_identity_case.py <queue_dir> [抽样数] [随机种子]
"""

import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_natural_case as N  # noqa

PERM = ('STOR ', 'APPE ', 'DELE ', 'MKD ', 'RMD ', 'RNFR ')


def parse(data):
    msgs = [m.decode('latin-1').strip(N.CRLF) for m in data.split(N.SEP)]
    msgs = [m for m in msgs if m]
    for i, m in enumerate(msgs):
        if m.strip().upper().startswith('QUIT'):
            return msgs[:i]
    return msgs


def main():
    qdir = os.path.expanduser(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261105

    files = [f for f in sorted(os.listdir(qdir)) if f.startswith('id:')]
    rng = random.Random(seed)
    if n < len(files):
        files = rng.sample(files, n)

    hits = []
    funnel = collections.OrderedDict([
        ("queue_total", len([f for f in os.listdir(qdir) if f.startswith('id:')])),
        ("sampled", len(files)), ("nonempty", 0), ("multi_login", 0),
        ("has_perm_cmd", 0), ("perm_gate_rejected", 0),
        ("reproducible", 0), ("writer_not_first_login", 0),
    ])
    for k, fn in enumerate(files, 1):
        msgs = parse(open(os.path.join(qdir, fn), 'rb').read())
        if not msgs:
            continue
        funnel["nonempty"] += 1
        logins = [i for i, m in enumerate(msgs) if m.upper().startswith('USER ')]
        perms = [i for i, m in enumerate(msgs) if m.upper().startswith(PERM)]
        if not perms:
            continue
        funnel["has_perm_cmd"] += 1
        if len(logins) < 2:
            continue
        funnel["multi_login"] += 1

        def reject_gate(e, evs_):
            """目标消息被权限门拒绝 → 返回 (目标消息号, 该门之前最后写 Access 的消息)"""
            if e.get('t') != 'gate' or e.get('taken') != 1:
                return None
            m = e.get('m')
            if not isinstance(m, int) or not (1 <= m <= len(msgs)):
                return None
            if not msgs[m - 1].upper().startswith(PERM):
                return None
            w = None
            for x in evs_:
                if (x.get('t') == 'write' and x.get('var') == 'Access'
                        and isinstance(x.get('m'), int) and x['m'] <= m):
                    w = x
            return (m, w)

        # 第一遍：单次重放筛候选
        r = N.run(msgs[:40])
        if not r:
            continue
        evs, resp = r
        g1 = [(e, reject_gate(e, evs)) for e in evs]
        g1 = [(e, x) for e, x in g1 if x and x[1]]
        if g1:
            funnel["perm_gate_rejected"] += 1
        # 写入者必须不来自第一次登录对（USER 在下标 0、PASS 在下标 1）
        g1 = [(e, x) for e, x in g1 if x[1]['m'] - 1 > logins[0] + 1]
        if not g1:
            continue
        funnel["writer_not_first_login"] += 1

        # 第二遍：只对候选验证可重现（同一条消息、同一个写入者）
        r2 = N.run(msgs[:40])
        if not r2:
            continue
        g2 = [reject_gate(e, r2[0]) for e in r2[0]]
        g2 = [x for x in g2 if x and x[1]]
        if [(x[0], x[1]['m']) for _, x in g1] != [(x[0], x[1]['m']) for x in g2]:
            continue
        funnel["reproducible"] += 1

        for e, (m, w) in g1:
            hits.append({
                "file": fn, "queue": qdir,
                "n_msgs": len(msgs), "logins": logins,
                "gate": e, "writer": w,
                "target_msg": m - 1,
                "target_text": msgs[m - 1],
                "writer_text": msgs[w['m'] - 1],
                "responses": resp,
            })
            break
        if k % 10 == 0:
            print('  已检查 %d/%d，命中 %d' % (k, len(files), len(hits)))

    print()
    print('命中 %d 条' % len(hits))
    for h in hits:
        print('-' * 70)
        print('文件   :', h['file'])
        print('消息数 :', h['n_msgs'], ' 登录下标:', h['logins'])
        print('目标   : [%d] %s' % (h['target_msg'], h['target_text']))
        print('写入者 : [%d] %s' % (h['writer']['m'] - 1, h['writer_text']))
        print('gate   :', json.dumps(h['gate'], ensure_ascii=False))

    print()
    print('漏斗：')
    for k, v in funnel.items():
        print('  %-24s %d' % (k, v))
    tag = os.path.basename(os.path.dirname(os.path.abspath(qdir))) or 'queue'
    fp = os.path.expanduser('~/stc/audit_v1/funnel_%s.json' % tag)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    json.dump(dict(funnel, queue=qdir, seed=seed, hits=len(hits)),
              open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    out = os.path.expanduser('~/stc/audit_v1/identity_candidates.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        try:
            prev = json.load(open(out, encoding='utf-8'))
        except ValueError:
            prev = []
        seen = {(x['queue'], x['file']) for x in prev}
        hits = prev + [x for x in hits if (x['queue'], x['file']) not in seen]
    json.dump(hits, open(os.path.expanduser('~/stc/audit_v1/identity_candidates_%s.json' % tag), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(hits, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
