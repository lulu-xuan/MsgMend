#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 Live555 队列，找出会话相关的自然失败。

RTSP 的状态门不是 Access 等级，而是**会话表查找**：
PLAY 必须带上 SETUP 时服务器下发的 Session 值，否则 lookup 失败。
现有插桩会记录 create（新建会话）与 lookup（查找会话，found=0/1）。

对每条队列序列：重放，统计 lookup 的结果，判定属于哪一类：
  ok           所有 lookup 都成功
  stale/wrong  PLAY 带 Session，但 lookup 失败（值不对或已失效）
  missing      PLAY 没有带 Session
  nosetup      序列里没有 SETUP，无从建立会话

用法
    python3 scan_rtsp.py <队列目录> [抽样数] [种子]
"""

import json
import os
import random
import socket
import subprocess
import sys
import time

BIN_DIR = os.path.expanduser('~/stc/live555/testProgs')
BIN = './testOnDemandRTSPServer'
PORT = 8554   # 该构建固定监听 8554，不接受端口参数
TRACE = '/tmp/_rtsp_scan.jsonl'
SEP = b'\r\n\r\n'


def start():
    try:
        os.remove(TRACE)
    except OSError:
        pass
    p = subprocess.Popen([BIN], cwd=BIN_DIR, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         env=dict(os.environ, STC_TRACE=TRACE))
    time.sleep(0.5)
    return p


def conn():
    t0 = time.time()
    while time.time() - t0 < 3:
        try:
            return socket.create_connection(('127.0.0.1', PORT), 0.3)
        except OSError:
            time.sleep(0.05)
    return None


def events():
    out = []
    try:
        for line in open(TRACE, encoding='utf-8', errors='replace'):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def replay(msgs):
    p = start()
    resp = []
    try:
        s = conn()
        if s is None:
            return None, []
        s.settimeout(0.8)
        for m in msgs:
            try:
                s.sendall(m + SEP)
            except OSError:
                break
            buf = b''
            try:
                while True:
                    d = s.recv(8192)
                    if not d:
                        break
                    buf += d
                    if len(d) < 8192:
                        break
            except (socket.timeout, OSError):
                pass
            resp.append(buf.decode(errors='replace').split('\r\n')[0])
        s.close()
    finally:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    return resp, events()


def classify(msgs, evs):
    has_setup = any(m.upper().startswith(b'SETUP') for m in msgs)
    plays = [m for m in msgs if m.upper().startswith(b'PLAY')]
    has_session = any(b'Session:' in m for m in plays)
    lookups = [e for e in evs if e.get('t') == 'lookup']
    creates = [e for e in evs if e.get('t') == 'create']
    failed = [e for e in lookups if e.get('found') == 0]
    if not has_setup:
        return 'nosetup', len(creates), len(lookups), len(failed)
    if plays and not has_session:
        return 'missing', len(creates), len(lookups), len(failed)
    if failed:
        return 'stale_or_wrong', len(creates), len(lookups), len(failed)
    return 'ok', len(creates), len(lookups), len(failed)


def main():
    qdir = os.path.expanduser(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20261108

    files = [f for f in sorted(os.listdir(qdir)) if f.startswith('id:')]
    rng = random.Random(seed)
    if n < len(files):
        files = rng.sample(files, n)
    files.sort()

    import collections
    tally = collections.Counter()
    rows = []
    for k, fn in enumerate(files, 1):
        data = open(os.path.join(qdir, fn), 'rb').read()
        msgs = [m.rstrip(b'\r\n') for m in data.split(SEP) if m.strip()]
        msgs = [m for m in msgs if m]
        if not msgs:
            continue
        resp, evs = replay(msgs)
        if resp is None:
            tally['connect_fail'] += 1
            continue
        cls, nc, nl, nf = classify(msgs, evs)
        tally[cls] += 1
        rows.append({'file': fn, 'class': cls, 'msgs': len(msgs),
                     'creates': nc, 'lookups': nl, 'failed_lookups': nf,
                     'resp': resp[:6]})
        if k % 25 == 0:
            print('  %d/%d  %s' % (k, len(files), dict(tally)))

    print()
    print('分类统计（抽样 %d 条）:' % len(files))
    for k, v in tally.most_common():
        print('  %-16s %d' % (k, v))
    out = os.path.expanduser('~/stc/audit_v1/rtsp_scan.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({'queue': qdir, 'sampled': len(files),
               'tally': dict(tally), 'rows': rows},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
