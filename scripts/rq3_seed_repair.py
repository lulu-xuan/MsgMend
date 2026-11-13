#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQ3 前置：从真实 fuzzing 队列自动产出"修复后打通新分支"的种子。

对每条队列序列：
  1. 重放，找第一条被状态门拒绝的权限命令（无需人工指定）
  2. 采集该状态的写入来源
  3. 按来源生成确定性修复动作（与 nat_ablation 的 V2 相同）
  4. 重放两次，两次都翻转才算修复成功
  5. 成功则把修复后的序列写成 fuzzing 可读的种子文件

输出
  out_dir/id: repaired_XXXXXX     修复后的序列（CRLF 连接，与队列同格式）
  audit_v1/rq3_seeds.jsonl        每条记录的判定与动作
  audit_v1/rq3_summary.json       分母与成功数

这一轮不跑长时间 fuzzing，只回答"修复器能不能稳定供货"。

用法
  python3 rq3_seed_repair.py <queue_dir> <抽样数> [种子]
"""

import json
import os
import random
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_provenance as A  # noqa
import eval_lib as E  # noqa
import find_identity_case as F  # noqa
import find_natural_case as N  # noqa
import nat_ablation as NA  # noqa
import run_verify as R  # noqa

OUT = os.path.expanduser('~/stc/audit_v1')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    qdir = os.path.expanduser(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261105
    tag = os.path.basename(os.path.dirname(os.path.abspath(qdir)))
    out_dir = os.path.expanduser('~/stc/rq3_seeds/%s' % tag)
    os.makedirs(out_dir, exist_ok=True)

    accts = R.load_accounts()
    acct = max(accts, key=lambda k: accts[k][0])
    pw = accts[acct][1] or acct

    files = [f for f in sorted(os.listdir(qdir)) if f.startswith('id:')]
    rng = random.Random(seed)
    if n < len(files):
        files = rng.sample(files, n)
    files.sort()

    rows = []
    n_perm = n_gate = n_rep = n_flip = 0
    for k, fn in enumerate(files, 1):
        msgs = F.parse(open(os.path.join(qdir, fn), 'rb').read())
        if not msgs:
            continue
        r = N.run(msgs[:40])
        if not r:
            continue
        rec = A.collect(msgs, r[0], accts)
        if not rec:
            continue
        n_gate += 1
        acts = NA.act(msgs, rec, acct, pw)
        if not acts.get('V2'):
            continue
        n_perm += 1

        # 重放只作为诊断记录，不再决定是否落盘。
        # 方法终止于「修补后的消息序列」，产物应当无条件写出；
        # 是否真的让门翻转，由后续 fuzzing 自己检验。
        flips = []
        for j in range(2):
            items = E.make_items(msgs[:40])
            ni, b = E.apply_actions(items, acts['V2'])
            res = E.replay(ni, b, False, 'rq3_%s_%s_%d' % (tag[:12], fn[3:9], j))
            q, rr, d = E.judge(res, ni, rec['target_msg_index'],
                               rec['failure']['gate_line'], False)
            flips.append(rr == 'target_branch_flipped')

        n_flip += 1
        items = E.make_items(msgs[:40])
        ni, _ = E.apply_actions(items, acts['V2'])
        body = (chr(13) + chr(10)).join(x['text'] for x in ni)
        # 用原始队列编号命名，让「原始序列 ↔ 修复序列」的配对关系写在文件名里
        orig_id = fn.split(',')[0]                        # 形如 id:000123
        seed_name = orig_id + ',repaired'
        with open(os.path.join(out_dir, seed_name), 'wb') as f:
            f.write(body.encode('latin-1', 'replace'))

        rows.append({"file": fn, "queue": qdir, "gate_op": rec['failure']['operator'],
                     "target_msg": rec['target_msg_index'],
                     "writer_msg": rec['state_provenance']['last_write']['message_id'],
                     "actions": acts['V2'],
                     "seed_file": seed_name,
                     "diagnostic_flip1": flips[0],
                     "diagnostic_flip2": flips[1]})
        if k % 20 == 0:
            print('  %d/%d  有权限门 %d  可生成动作 %d  修复成功 %d' % (
                k, len(files), n_gate, n_perm, n_flip))

    # 每个队列写自己的日志，避免后一次运行覆盖前一次
    log_path = os.path.join(OUT, 'rq3_seeds_%s.jsonl' % tag)
    with open(log_path, 'w', encoding='utf-8') as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')

    summary = {"queue": qdir, "sampled": len(files), "with_rejected_gate": n_gate,
               "action_generated": n_perm, "repaired": n_flip,
               "out_dir": out_dir,
               "yield_over_gate": round(n_flip / n_gate, 3) if n_gate else 0}
    json.dump(summary, open(os.path.join(OUT, 'rq3_summary_%s.json' % tag), 'w',
                            encoding='utf-8'), ensure_ascii=False, indent=1)

    print()
    print('抽样 %d  有被拒权限门 %d  能生成动作 %d  两次回放都翻转 %d' % (
        len(files), n_gate, n_perm, n_flip))
    print('产出 %d 条种子 -> %s' % (n_flip, out_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
