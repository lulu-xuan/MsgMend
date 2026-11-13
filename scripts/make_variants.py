#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按指导第三周，生成 V1 / V1b 两种修复语料，用于策略对照。

V1  只看消息位置：改第一次登录；未登录门则在目标前插登录
V1b 暴力基线：把每一对登录消息都改掉
V2  按写入来源定位（已有，不重新生成）

三者作用在同一批原始序列上，语料规模一致，只有修复策略不同。

注意
    V1/V1b 的写入来源在本脚本内重新采集一次，可能与当初生成 V2 语料时
    的那次采集有极细微差异（执行存在不确定性）。语料层面的对照不受影响，
    但文档中要写明这一点。

输出
    ~/stc/pairs/chatafl-v1/seed_XXX
    ~/stc/pairs/chatafl-v1b/seed_XXX
    ~/stc/audit_v1/variants.json
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_provenance as A  # noqa
import eval_lib as E  # noqa
import find_identity_case as F  # noqa
import find_natural_case as N  # noqa
import nat_ablation as NA  # noqa
import run_verify as R  # noqa

AUDIT = os.path.expanduser('~/stc/audit_v1')
PAIRS = os.path.expanduser('~/stc/pairs')


def valid_ratio(msgs):
    if not msgs:
        return 0.0, 0.0, 0
    rid = abs(hash(tuple(msgs))) % (10 ** 8)
    res = E.replay(E.make_items(msgs), [], False, 'var_%d' % rid)
    resp = [r for r in res.get('responses') or [] if r]
    if not resp:
        return 0.0, 0.0, 0
    ok = sum(1 for r in resp if r[:1] in ('1', '2', '3'))
    err = sum(1 for r in resp if r[:1] == '5')
    return ok / len(resp), err / len(resp), len(resp)


def main():
    accts = R.load_accounts()
    acct = max(accts, key=lambda k: accts[k][0])
    pw = accts[acct][1] or acct

    with open(os.path.join(AUDIT, 'rq3_pairs.csv'), encoding='utf-8') as f:
        pairs = [r for r in csv.DictReader(f) if r['source_fuzzer'] == 'ChatAFL']
    print('ChatAFL 配对 %d 条' % len(pairs))

    for v in ('v1', 'v1b'):
        os.makedirs(os.path.join(PAIRS, 'chatafl-%s' % v), exist_ok=True)

    rows = []
    stat = {k: [0.0, 0.0, 0] for k in ('V1', 'V1b')}
    for i, p in enumerate(pairs):
        msgs = F.parse(open(p['orig_path'], 'rb').read())[:40]
        if not msgs:
            continue
        r = N.run(msgs)
        if not r:
            continue
        rec = A.collect(msgs, r[0], accts)
        if not rec:
            continue
        acts = NA.act(msgs, rec, acct, pw)

        for key, corp in (('V1', 'v1'), ('V1b', 'v1b')):
            a = acts.get(key) or []
            items = E.make_items(msgs)
            ni, _ = E.apply_actions(items, a)
            body = (chr(13) + chr(10)).join(x['text'] for x in ni)
            name = 'seed_%03d' % i
            with open(os.path.join(PAIRS, 'chatafl-%s' % corp, name), 'wb') as f:
                f.write(body.encode('latin-1', 'replace'))
            o, e, n = valid_ratio([x['text'] for x in ni])
            stat[key][0] += o
            stat[key][1] += e
            stat[key][2] += 1
            rows.append({"pair_id": p['pair_id'], "variant": key, "seed": name,
                         "gate_op": rec['failure']['operator'],
                         "n_edits": len(a), "actions": a,
                         "valid_ratio": round(o, 3), "err_ratio": round(e, 3)})
        if (i + 1) % 10 == 0:
            print('  %d/%d' % (i + 1, len(pairs)))

    json.dump(rows, open(os.path.join(AUDIT, 'variants.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    print()
    for k, (o, e, n) in stat.items():
        print('%-4s %d 条  有效响应 %.1f%%  5xx %.1f%%  平均编辑 %.2f 条' % (
            k, n, 100 * o / n, 100 * e / n,
            sum(r['n_edits'] for r in rows if r['variant'] == k) / max(n, 1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
