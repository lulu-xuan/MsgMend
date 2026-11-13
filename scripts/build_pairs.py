#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为「原始语料 vs 修复语料」配对覆盖率实验生成清单与语料目录。

为什么必须配对
    直接拿大队列和几十条修复种子比，覆盖率差异可能来自语料数量而不是修复质量。
    配对设计让两组的种子数、来源完全相同，只差「有没有经过 V2 修复」。

为什么按来源分开
    AFLNet 与 ChatAFL 的队列质量本身不同。混在一起会把 Fuzzer 的差异算到修复头上。

来源目录
    ~/stc/audit_v1/rq3_seeds_<campaign>.jsonl     每次修复运行的记录
    ~/ccfa/lftp2h/<campaign>/queue/               原始队列
    ~/stc/rq3_seeds/<campaign>/                   修复后的序列

用法
    python3 build_pairs.py manifest              # 只生成清单
    python3 build_pairs.py stage <输出根目录>     # 生成两组语料目录
"""

import csv
import json
import os
import shutil
import sys

AUDIT = os.path.expanduser('~/stc/audit_v1')
SEEDS = os.path.expanduser('~/stc/rq3_seeds')
QUEUES = os.path.expanduser('~/ccfa/lftp2h')

CAMPAIGNS = ['out-aflnet-r1', 'out-chatafl-r1', 'out-chatafl-r3']


def load(camp):
    p = os.path.join(AUDIT, 'rq3_seeds_%s.jsonl' % camp)
    if not os.path.exists(p):
        return []
    rows = [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]
    out = []
    for i, r in enumerate(rows, 1):
        # 现在所有生成了修补动作的序列都会落盘，不再用重放结果过滤
        tip = r.get('seed_file')
        if not tip:
            # 旧日志没有 seed_file 字段，按命名规则推
            tip = r['file'].split(',')[0] + ',repaired'
        out.append({
            "pair_id": "%s-%02d" % (camp.replace('out-', ''), i),
            "source_campaign": camp,
            "source_fuzzer": 'AFLNet' if 'aflnet' in camp else 'ChatAFL',
            "orig_file": r['file'],
            "orig_path": os.path.join(r['queue'], r['file']),
            "seed_file": tip,
            "seed_path": os.path.join(SEEDS, camp, tip),
            "gate_op": r['gate_op'],
            "target_msg": r['target_msg'],
            "writer_msg": r['writer_msg'],
            "n_edits": len(r.get('actions') or []),
            "actions": json.dumps(r.get('actions') or [], ensure_ascii=False),
        })
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mode = sys.argv[1]

    pairs = []
    for c in CAMPAIGNS:
        got = load(c)
        pairs.extend(got)
        print('%-18s 配成 %d 对' % (c, len(got)))

    # 检查两侧文件是否都在
    missing = [p for p in pairs
               if not os.path.exists(p['orig_path']) or not os.path.exists(p['seed_path'])]
    if missing:
        print('缺文件 %d 对，例如：' % len(missing))
        for m in missing[:3]:
            print('  orig', os.path.exists(m['orig_path']), m['orig_path'])
            print('  seed', os.path.exists(m['seed_path']), m['seed_path'])

    out_csv = os.path.join(AUDIT, 'rq3_pairs.csv')
    cols = ['pair_id', 'source_campaign', 'source_fuzzer', 'gate_op',
            'n_edits', 'target_msg', 'writer_msg', 'orig_file', 'seed_file',
            'orig_path', 'seed_path', 'actions']
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in pairs:
            w.writerow({k: p[k] for k in cols})
    print('\n清单 ->', out_csv)

    by = {}
    for p in pairs:
        d = by.setdefault(p['source_fuzzer'], {'pairs': 0, 'campaigns': set()})
        d['pairs'] += 1
        d['campaigns'].add(p['source_campaign'])
    for k, v in by.items():
        print('  %-8s %d 对，来自 %s' % (k, v['pairs'], ', '.join(sorted(v['campaigns']))))
    json.dump({k: {"pairs": v['pairs'], "campaigns": sorted(v['campaigns'])}
               for k, v in by.items()},
              open(os.path.join(AUDIT, 'rq3_pairs_summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    if mode != 'stage':
        return 0

    # 生成两组语料目录：基线用原始序列，实验组用修复序列
    root = os.path.expanduser(sys.argv[2])
    for fuzzer in sorted(by):
        base_dir = os.path.join(root, '%s-baseline' % fuzzer.lower())
        ours_dir = os.path.join(root, '%s-repaired' % fuzzer.lower())
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(ours_dir, exist_ok=True)
        n = 0
        for p in pairs:
            if p['source_fuzzer'] != fuzzer:
                continue
            if not (os.path.exists(p['orig_path']) and os.path.exists(p['seed_path'])):
                continue
            # 两组用相同的文件名编号，便于逐对核对
            dst = 'seed_%03d' % n
            shutil.copyfile(p['orig_path'], os.path.join(base_dir, dst))
            shutil.copyfile(p['seed_path'], os.path.join(ours_dir, dst))
            n += 1
        print('%-8s baseline %d 条 -> %s' % (fuzzer, n, base_dir))
        print('%-8s repaired %d 条 -> %s' % (fuzzer, n, ours_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
