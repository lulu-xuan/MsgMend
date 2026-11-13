#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动采集消息级状态来源，并据此生成自然案例。

对应任务书第三步：
  - 来源事件必须早于目标读取，使用全序事件号（这里用 trace 文件行号）而不是
    只比较 writer_message_id <= target_message_id
  - 写入与读取必须同一会话
  - 同一消息里读取之后发生的写入不能当成该读取的来源
  - 区分「消息身份来源」与「值的语义来源」，后者是配置查找，属工具推导

输出字段全部为工具生成；不含 human_annotation / ground_truth。

用法
  python3 auto_provenance.py collect <queue_dir> <抽样数> [种子]   # 只报告
  python3 auto_provenance.py build   <queue_dir> <抽样数> [种子]   # 写案例目录
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import find_natural_case as N  # noqa
import find_identity_case as F  # noqa
import run_verify as R  # noqa

PERM = ('STOR ', 'APPE ', 'DELE ', 'MKD ', 'RMD ', 'RNFR ')
CASES_OUT = os.path.expanduser('~/stc/cases_nat')
LEVELS = {"readonly": 1, "upload": 2, "admin": 3}


def auto_target(events, msgs):
    """选出第一条被状态门拒绝的权限命令，不需要人工指定。"""
    for i, e in enumerate(events):
        if e.get('t') != 'gate' or e.get('taken') != 1:
            continue
        m = e.get('m')
        if not isinstance(m, int) or not (1 <= m <= len(msgs)):
            continue
        if not msgs[m - 1].upper().startswith(PERM):
            continue
        return i, e
    return None, None


def last_writer(events, gate_i, gate):
    """同一会话、全序在 gate 之前的最后一次写入。"""
    var, sess = gate.get('var'), gate.get('s')
    w_i = None
    for i in range(gate_i):
        e = events[i]
        if e.get('t') == 'write' and e.get('var') == var and e.get('s') == sess:
            w_i = i
    return (w_i, events[w_i]) if w_i is not None else (None, None)


def account_before(msgs, upto_idx):
    """写入消息之前最近的 USER 参数。"""
    for i in range(min(upto_idx, len(msgs)) - 1, -1, -1):
        t = msgs[i].strip()
        if t.upper().startswith('USER '):
            return t[5:].strip()
    return None


def value_source(msgs, w, accts):
    """值的语义来源：配置查找 / 协议规则。"""
    fn = w.get('fn') or ''
    widx = w['m'] - 1
    if fn == 'ftpPASS':
        acct = account_before(msgs, widx)
        lv, pw = accts.get(acct, (None, None))
        return {
            "kind": "config_lookup",
            "detail": "PASS 成功后 Access 取该账号在 fftp.conf 中的权限等级",
            "account": acct,
            "accs_level": lv,
            "matches_observed_new": (lv == w.get('new')),
            "source": "fftp.conf [%s] accs=" % acct,
        }
    if fn == 'ftpUSER':
        return {
            "kind": "protocol_rule",
            "detail": "收到 USER 时服务器把 Access 置 0，直到 PASS 通过",
            "observed_new": w.get('new'),
        }
    return {"kind": "unknown", "detail": "未识别的写入位置 %s" % fn}


def collect(msgs, events, accts):
    gate_i, gate = auto_target(events, msgs)
    if gate is None:
        return None
    w_i, w = last_writer(events, gate_i, gate)
    if w is None:
        return None
    return {
        "target_msg_index": gate['m'] - 1,
        "failure": {
            "gate_line": gate.get('line'),
            "operator": gate.get('op'),
            "lhs": gate.get('lhs'),
            "rhs": gate.get('rhs'),
            "branch_id": "ftpserv.c:gate:%s:%s" % (gate.get('line'), w.get('fn')),
            "session": gate.get('s'),
        },
        "state_provenance": {
            "variable": "context->Access",
            "last_write": {
                "message_id": w['m'] - 1,
                "command": (msgs[w['m'] - 1].split(' ')[0] if w['m'] - 1 < len(msgs) else ''),
                "site": "%s:%s" % (w.get('fn'), w.get('line')),
                "old": w.get('old'),
                "new": w.get('new'),
                "session": w.get('s'),
            },
            "event_order": {
                "write_at": w_i,
                "read_at": gate_i,
                "write_before_read": w_i < gate_i,
                "same_session": w.get('s') == gate.get('s'),
                "total_events": len(events),
            },
            "value_source": value_source(msgs, w, accts),
            "derived_from": "tool:auto_provenance.py",
        },
    }


def first_login_pass(msgs):
    """第一次登录对的 PASS 下标；写入者在此之后才说明身份有区分作用。"""
    pending = None
    for i, m in enumerate(msgs):
        u = m.upper()
        if u.startswith('USER '):
            pending = i
        elif u.startswith('PASS ') and pending is not None:
            return i
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    mode, qdir = sys.argv[1], os.path.expanduser(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 20261105
    accts = R.load_accounts()

    files = [f for f in sorted(os.listdir(qdir)) if f.startswith('id:')]
    import random
    rng = random.Random(seed)
    if n < len(files):
        files = rng.sample(files, n)

    got = []
    for fn in files:
        msgs = F.parse(open(os.path.join(qdir, fn), 'rb').read())
        if not msgs:
            continue
        r = N.run(msgs[:40])
        if not r:
            continue
        rec = collect(msgs, r[0], accts)
        if not rec:
            continue
        w_id = rec['state_provenance']['last_write']['message_id']
        fp = first_login_pass(msgs)
        rec.update({"file": fn, "queue": qdir,
                    "writer_is_first_login": (fp is not None and w_id <= fp),
                    "responses": r[1]})
        got.append(rec)

    print('扫描 %d 条，命中被权限门拒绝的 %d 条' % (len(files), len(got)))
    diff = [x for x in got if not x['writer_is_first_login']]
    print('其中写入者不是首次登录的：%d 条' % len(diff))
    for x in diff:
        w = x['state_provenance']['last_write']
        vs = x['state_provenance']['value_source']
        print('  %-30s 目标[%d] gate %s  写入 msg %d (%s) new=%s  值来源=%s(%s 级)' % (
            x['file'][:30], x['target_msg_index'], x['failure']['gate_line'],
            w['message_id'], w['command'], w['new'],
            vs.get('account'), vs.get('accs_level')))

    if mode == 'build':
        os.makedirs(CASES_OUT, exist_ok=True)
        tag = os.path.basename(os.path.dirname(os.path.abspath(qdir)))
        keep = []
        for x in diff:
            msgs = F.parse(open(os.path.join(x['queue'], x['file']), 'rb').read())[:40]
            r2 = N.run(msgs)
            rec2 = collect(msgs, r2[0], accts) if r2 else None
            same = (rec2 is not None
                    and rec2['target_msg_index'] == x['target_msg_index']
                    and rec2['failure']['gate_line'] == x['failure']['gate_line']
                    and rec2['state_provenance']['last_write']['message_id']
                    == x['state_provenance']['last_write']['message_id'])
            if not same:
                print('  丢弃（两次重放不一致）:', x['file'][:40])
                continue
            keep.append(x)
        print('可重现 %d 条' % len(keep))
        for k, x in enumerate(keep, 1):
            cid = 'N_%s_%02d' % (tag.split('out-')[-1][:12], k)
            d = os.path.join(CASES_OUT, cid)
            os.makedirs(d, exist_ok=True)
            ev = {
                "case_id": cid, "kind": "natural", "source": "%s/%s" % (x['queue'], x['file']),
                "messages": F.parse(open(os.path.join(x['queue'], x['file']), 'rb').read())[:40],
                "responses": x['responses'],
                "failure": x['failure'],
                "state_provenance": x['state_provenance'],
                "target_msg_index": x['target_msg_index'],
            }
            json.dump(ev, open(os.path.join(d, 'evidence.json'), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            print('  写出案例', cid)
    return 0


if __name__ == '__main__':
    sys.exit(main())
