#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「随机修复」对照语料。

目的
    回答一个问题：提升是不是随便改几条消息也能拿到？
    做法是让随机修复与 V2 使用**完全相同的编辑预算**——
    每条序列改几条，就随机改几条，只是改哪里、改成什么由随机决定。

    指导里的提醒：随机修改协议消息很可能直接破坏合法性，
    因此这一组要额外报告「有效请求比例」，不能只报覆盖率。

输入
    ~/stc/audit_v1/rq3_pairs.csv        配对清单（含每条原始序列、V2 的编辑数）
    原始队列文件

输出
    ~/stc/pairs/chatafl-random/seed_XXX  与 baseline 同编号，便于逐对对照
    ~/stc/audit_v1/random_repair.json    每条的有效率与动作
"""

import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa
import find_identity_case as F  # noqa

AUDIT = os.path.expanduser('~/stc/audit_v1')
OUTDIR = os.path.expanduser('~/stc/pairs/chatafl-random')
SEED = 20261108

# 与 V2 同源的动作词表：V2 会改登录、换账号、插登录，
# 随机组就从同样的候选里随便挑，只是位置与组合是随机的
VOCAB = [
    'USER anonymous', 'PASS x', 'USER ubuntu', 'PASS ubuntu',
    'USER webadmin', 'PASS ubuntu', 'PWD', 'SYST', 'LIST', 'MKD test',
    'CWD /', 'TYPE I', 'PASV', 'PORT 127,0,0,1,132,209',
]


def valid_ratio(msgs):
    """回放一条序列，统计响应码分布。返回 (2xx/3xx 比例, 5xx 比例, 条数)"""
    if not msgs:
        return 0.0, 0.0, 0
    rid = abs(hash(tuple(msgs))) % (10 ** 8)
    res = E.replay(E.make_items(msgs), [], False, 'rr_%d' % rid)
    resp = [r for r in res.get('responses') or [] if r]
    if not resp:
        return 0.0, 0.0, 0
    ok = sum(1 for r in resp if r[:1] in ('1', '2', '3'))
    err = sum(1 for r in resp if r[:1] == '5')
    return ok / len(resp), err / len(resp), len(resp)


def main():
    rng = random.Random(SEED)
    os.makedirs(OUTDIR, exist_ok=True)

    with open(os.path.join(AUDIT, 'rq3_pairs.csv'), encoding='utf-8') as f:
        pairs = [r for r in csv.DictReader(f) if r['source_fuzzer'] == 'ChatAFL']
    print('ChatAFL 配对：%d 条' % len(pairs))

    rows = []
    ok_all = []
    err_all = []
    for i, p in enumerate(pairs):
        msgs = F.parse(open(p['orig_path'], 'rb').read())[:40]
        if not msgs:
            continue
        k = int(p['n_edits']) or 1
        out = [dict(id=j, text=m) for j, m in enumerate(msgs)]
        acts = []
        for _ in range(k):
            op = rng.choice(['replace_message', 'insert_before'])
            idx = rng.randrange(len(out))
            txt = rng.choice(VOCAB)
            acts.append({"op": op, "index": out[idx]['id'], "message": txt})
            if op == 'replace_message':
                out[idx]['text'] = txt
            else:
                out.insert(idx, {"id": 100000 + len(acts), "text": txt})
        body = (chr(13) + chr(10)).join(x['text'] for x in out)
        name = 'seed_%03d' % i
        with open(os.path.join(OUTDIR, name), 'wb') as f:
            f.write(body.encode('latin-1', 'replace'))

        vr, er, n = valid_ratio([x['text'] for x in out])
        ok_all.append(vr)
        err_all.append(er)
        rows.append({"pair_id": p['pair_id'], "seed": name,
                     "n_edits": k, "actions": acts,
                     "valid_ratio": round(vr, 3), "err_ratio": round(er, 3),
                     "responses": n})
        if (i + 1) % 10 == 0:
            print('  %d/%d' % (i + 1, len(pairs)))

    json.dump(rows, open(os.path.join(AUDIT, 'random_repair.json'), 'w',
                         encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('产出 %d 条 -> %s' % (len(rows), OUTDIR))
    print('有效响应比例（2xx/3xx）均值 %.1f%%' % (100 * sum(ok_all) / len(ok_all)))
    print('错误响应比例（5xx）均值   %.1f%%' % (100 * sum(err_all) / len(err_all)))
    print('编辑次数合计 %d（与 V2 相同预算）' % sum(r['n_edits'] for r in rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())
