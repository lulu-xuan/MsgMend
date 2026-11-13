#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 AFLNet 的真实队列里，找"被状态门卡住"的自然失败案例。

判据
    某条队列序列执行时，出现 gate 事件 taken=1（判定成立 → 被拒绝），
    且该 gate 读到的 Access 最后写入者是 INIT（说明整个会话没有任何消息写过它）。

输出
    每个候选打印：序列、触发的 gate、相关写入事件。

用法
    python3 find_natural_case.py <queue_dir> [抽样数]
"""

import json
import os
import random
import socket
import subprocess
import sys
import time

RUN = os.path.expanduser("~/stc/proto/Source/Release")
BIN = os.path.join(RUN, "fftp")
CONF = "fftp.conf"
PORT = 9701
TRACE = "/tmp/_stc_nat.jsonl"
CRLF = chr(13) + chr(10)
SEP = CRLF.encode()


def start():
    p = subprocess.Popen([BIN, CONF, str(PORT)], cwd=RUN,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=dict(os.environ, STC_TRACE=TRACE))
    time.sleep(0.06)
    return p


def conn():
    t0 = time.time()
    while time.time() - t0 < 2:
        try:
            return socket.create_connection(("127.0.0.1", PORT), 0.15)
        except OSError:
            time.sleep(0.01)
    return None


def run(msgs, cap=40):
    try:
        os.remove(TRACE)
    except OSError:
        pass
    p = start()
    try:
        s = conn()
        if s is None:
            return None
        s.settimeout(0.25)
        try:
            s.recv(4096)
        except Exception:
            pass
        resp = []
        for m in msgs[:cap]:
            try:
                s.sendall((m + CRLF).encode())
            except OSError:
                break
            try:
                resp.append(s.recv(4096).decode(errors="replace").strip())
            except socket.timeout:
                resp.append("")
        s.close()
    finally:
        p.kill()
        try:
            p.wait(timeout=1)
        except Exception:
            pass

    evs = []
    try:
        with open(TRACE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        evs.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return evs, resp


def last_writer(evs, upto_msg):
    """最后一次写 Access 的事件"""
    w = None
    for e in evs:
        if e.get("t") == "write" and e.get("var") == "Access" and e.get("m", 0) <= upto_msg:
            w = e
    return w


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    qdir = os.path.expanduser(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    files = [f for f in sorted(os.listdir(qdir)) if f.startswith("id:")]
    rng = random.Random(20261104)
    if n < len(files):
        files = rng.sample(files, n)

    found = 0
    for fn in files:
        data = open(os.path.join(qdir, fn), "rb").read()
        msgs = [m.decode("latin-1").strip(CRLF) for m in data.split(SEP)]
        msgs = [m for m in msgs if m]
        # 遇到 QUIT 截断
        for i, m in enumerate(msgs):
            if m.strip().upper().startswith("QUIT"):
                msgs = msgs[:i]
                break
        if not msgs:
            continue

        out = run(msgs)
        if out is None:
            continue
        evs, resp = out

        gates = [e for e in evs if e.get("t") == "gate" and e.get("taken") == 1]
        if not gates:
            continue
        g = gates[0]
        w = last_writer(evs, g.get("m", 0))
        if w is None or w.get("writer") != "INIT":
            continue

        found += 1
        print("=" * 70)
        print("队列文件:", fn)
        print("消息序列:", " | ".join(msgs[:12]), "(共%d条)" % len(msgs))
        print("响应:", " | ".join(r.split(chr(10))[0][:40] for r in resp[:12]))
        print("卡住的 gate:", "line=%s msg=%s lhs=%s %s rhs=%s taken=%s"
              % (g.get("line"), g.get("m"), g.get("lhs"), g.get("op"),
                 g.get("rhs"), g.get("taken")))
        print("该状态最后写入者:", "m=%s fn=%s line=%s writer=%s"
              % (w.get("m"), w.get("fn"), w.get("line"), w.get("writer")))
        if found >= 3:
            break

    print()
    print("共找到 %d 个自然失败候选（抽样 %d 条）" % (found, len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
