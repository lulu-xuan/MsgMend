#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评测器回归测试：覆盖任务书列出的 8 个已知风险。

这些是**评测器本身的验收**，不是论文实验。
每项给出：构造的输入 → 期望的判定 → 实际判定。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_lib as E  # noqa


def pkg(events, error=None):
    return {"events": events, "error": error, "responses": ["x"]}


def msg(i, cmd):
    return {"t": "msg", "s": 1, "m": i, "cmd": cmd, "params": ""}


def gate(line, lhs, op, rhs, taken):
    return {"t": "gate", "s": 1, "m": 1, "var": "Access", "lhs": lhs,
            "op": op, "rhs": rhs, "taken": taken, "line": line}


def run(name, got, want_q, want_r, detail=""):
    ok = (got[0] == want_q and got[1] == want_r)
    print("%-38s %s  quality=%-14s result=%-28s %s" %
          (name, "PASS" if ok else "FAIL", got[0], got[1],
           got[2] if not ok else ""))
    return ok


def main():
    items = E.make_items(["USER anonymous", "PASS x", "STOR f"])
    tgt = 2
    ok = True

    # 1 空事件：不能算成功
    ok &= run("1 空事件 → 不得判成功",
              E.judge(pkg([]), items, tgt, 1434, False),
              "trace_missing", "target_not_reached")

    # 2 提前 530：目标命令根本没到
    ev = [msg(1, "USER"), msg(2, "PASS")]
    ok &= run("2 提前退出（少一条 msg）→ ambiguous",
              E.judge(pkg(ev), items, tgt, 1434, False),
              "ambiguous", "target_not_reached")

    # 3 仍失败
    ev = [msg(1, "USER"), msg(2, "PASS"), msg(3, "STOR"), gate(1434, 1, "<", 2, 1)]
    ok &= run("3 目标分支仍被拒",
              E.judge(pkg(ev), items, tgt, 1434, False),
              "valid", "target_reached_still_blocked")

    # 4 真实翻转
    ev = [msg(1, "USER"), msg(2, "PASS"), msg(3, "STOR"), gate(1434, 2, "<", 2, 0)]
    ok &= run("4 目标分支真翻转",
              E.judge(pkg(ev), items, tgt, 1434, False),
              "valid", "target_branch_flipped")

    # 5 翻转后另一条件拒绝：仍记翻转，但不代表业务完成
    ev = [msg(1, "USER"), msg(2, "PASS"), msg(3, "STOR"),
          gate(1434, 2, "<", 2, 0), gate(1500, 0, "==", 1, 1)]
    r = E.judge(pkg(ev), items, tgt, 1434, False)
    ok &= run("5 翻转后其它条件拒绝（只判目标分支）",
              r, "valid", "target_branch_flipped")

    # 6 没有 gate 事件：不能凭"没有失败事件"判成功
    ev = [msg(1, "USER"), msg(2, "PASS"), msg(3, "STOR")]
    ok &= run("6 未观察到 gate → 不得判成功",
              E.judge(pkg(ev), items, tgt, 1434, False),
              "valid", "target_not_reached")

    # 7 重复同名命令：按 ID 定位，不按字符串
    dup = E.make_items(["STOR f", "PWD", "STOR f"])
    out, _ = E.apply_actions(dup, [{"op": "replace_message", "index": 2,
                                    "message": "STOR g"}])
    ok7 = (out[0]['text'] == "STOR f" and out[2]['text'] == "STOR g"
           and out[0]['id'] == 0 and out[2]['id'] == 2)
    print("%-38s %s" % ("7 重复同名命令按 ID 替换", "PASS" if ok7 else "FAIL"))
    ok &= ok7

    # 8 插入后动态绑定：绑定按 ID 引用，插入不影响
    items8 = E.make_items(["A", "B"])
    out8, binds8 = E.apply_actions(items8, [
        {"op": "insert_before", "index": 1, "message": "X"},
        {"op": "bind_field", "index": 1, "field": "Session", "from_index": 0},
    ])
    # 插入后：A(id0) X(id2) B(id1)；绑定应指 id1 -> from id0，且 id1 现在位于下标 2
    pos_b = [k for k, x in enumerate(out8) if x['id'] == 1][0]
    ok8 = (len(out8) == 3 and pos_b == 2 and binds8 == [(1, 'Session', 0)])
    print("%-38s %s" % ("8 插入后绑定仍指向原消息", "PASS" if ok8 else "FAIL"))
    ok &= ok8

    # 附：RTSP 查找成功/失败
    ev = [msg(1, "DESCRIBE"), msg(2, "SETUP"), msg(3, "PLAY"),
          {"t": "create", "cmd": "SETUP", "sid": "AAAA", "found": 1},
          {"t": "lookup", "cmd": "PLAY", "cseq": "4", "sid": "AAAA", "found": 1}]
    ok &= run("9 RTSP 查找成功", E.judge(pkg(ev), E.make_items(["a", "b", "c"]),
                                         2, None, True),
              "valid", "target_branch_flipped")

    print()
    print("评测器回归测试：%s" % ("全部通过" if ok else "存在失败项"))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'oracle_tests.json'), 'w', encoding='utf-8') as f:
        json.dump({"passed": bool(ok)}, f)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
