#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Live555 自然队列上验证会话绑定修补。

失败模式：PLAY 携带的 Session 与本次 SETUP 下发的值不一致（或来自别的会话），
服务器查找会话表失败。

修补动作：bind_field —— 把 PLAY 的 Session 字段绑定为 SETUP 那条消息的响应值，
发送时才解析，因此拿到的是本次执行真正下发的会话号。

判定同样在序列层面之外，这里额外做一次执行确认（lookup found=1），
用于验证修补机制在第二个协议上成立。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa

SEP = b'\r\n\r\n'


def parse(path):
    data = open(path, 'rb').read()
    msgs = [m.rstrip(b'\r\n').decode('latin-1') for m in data.split(SEP) if m.strip()]
    return [m for m in msgs if m]


def main():
    qdir = os.path.expanduser(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    files = [f for f in sorted(os.listdir(qdir)) if f.startswith('id:')][:n]

    ok = 0
    tried = 0
    rows = []
    for fn in files:
        msgs = parse(os.path.join(qdir, fn))
        setup = next((i for i, m in enumerate(msgs) if m.upper().startswith('SETUP')), None)
        play = next((i for i, m in enumerate(msgs) if m.upper().startswith('PLAY')), None)
        if setup is None or play is None:
            continue
        tried += 1

        # 修复：把 SETUP 之后**所有带 Session 头的消息**都绑定到 SETUP 的响应值。
        # 只绑 PLAY 不够——TEARDOWN / GET_PARAMETER 等同样引用会话，带旧值会被 454 拒绝。
        items = E.make_items(msgs)
        refs = [i for i, m in enumerate(msgs)
                if i > setup and 'session:' in m.lower()]
        binds = [(items[i]['id'], 'Session', items[setup]['id']) for i in refs]
        res = E.replay(items, binds, True, 'rtspfix_%s' % fn[3:9])
        evs = res.get('events') or []
        lk = [e for e in evs if e.get('t') == 'lookup']
        good = bool(lk) and lk[-1].get('found') == 1
        ok += 1 if good else 0
        rows.append({'file': fn, 'msgs': len(msgs), 'setup': setup, 'play': play,
                     'lookups': len(lk),
                     'found': [e.get('found') for e in lk],
                     'repaired_ok': good})
        print('%-36s lookup %s  修复后 %s' % (
            fn[:36], [e.get('found') for e in lk], '成功' if good else '失败'))

    print()
    print('可尝试 %d 条，绑定修补后 lookup 成功 %d 条（%.0f%%）' % (
        tried, ok, 100 * ok / tried if tried else 0))
    out = os.path.expanduser('~/stc/audit_v1/rtsp_repair.json')
    json.dump({'queue': qdir, 'tried': tried, 'ok': ok, 'rows': rows},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
