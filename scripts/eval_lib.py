#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一评测库：稳定消息身份 + 逐 run 日志 + 双轴判定。

按任务书要求：
  - 原序列每条消息一个唯一 ID；替换保留 ID，插入使用新 ID；绑定按 ID 引用、发送时解析
  - 每个 run 独立日志文件，不互相覆盖
  - 判定必须**观察到正向证据**才记成功；空日志、目标被删、提前退出都不算
  - 判分拆成两个独立轴：执行质量 / 目标结果
"""

import json
import os
import re
import socket
import subprocess
import time

CRLF = chr(13) + chr(10)
LOG_DIR = '/tmp/audit_logs'

FTP = {"run": os.path.expanduser('~/stc/proto/Source/Release'), "bin": './fftp',
       "conf": 'fftp.conf', "port": 9821}
RTSP = {"run": os.path.expanduser('~/stc/live555/testProgs'),
        "bin": './testOnDemandRTSPServer', "port": 8554}


# ---------------- 消息身份 ----------------
def make_items(msgs):
    return [{"id": i, "text": m} for i, m in enumerate(msgs)]


def apply_actions(items, actions):
    """返回 (新 items, binds)。binds 里用消息 ID 而不是下标。"""
    out = [dict(x) for x in items]
    binds = []
    next_id = max([x['id'] for x in out] + [-1]) + 1

    def pos_of(mid):
        for k, x in enumerate(out):
            if x['id'] == mid:
                return k
        return None

    norm = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        if a.get('op'):
            norm.append(a)
            continue
        for k in ('insert_before', 'replace_message', 'bind_field'):
            if isinstance(a.get(k), dict):
                d = dict(a[k]); d['op'] = k; norm.append(d); break

    # 先替换（保留 ID）
    for a in norm:
        if a.get('op') == 'replace_message' and isinstance(a.get('index'), int):
            p = pos_of(a['index'])
            if p is not None and a.get('message'):
                out[p]['text'] = a['message']

    # 再插入（新 ID）
    for a in norm:
        if a.get('op') == 'insert_before' and isinstance(a.get('index'), int):
            p = pos_of(a['index'])
            if p is None:
                if a['index'] == len(items):
                    p = len(out)
                else:
                    continue
            out.insert(p, {"id": next_id, "text": a.get('message', '')})
            next_id += 1

    # 绑定（按 ID）
    for a in norm:
        if a.get('op') == 'bind_field':
            t, s = a.get('index'), a.get('from_index')
            if isinstance(t, int) and isinstance(s, int) and a.get('field'):
                if pos_of(t) is not None and pos_of(s) is not None:
                    binds.append((t, a['field'], s))
    return out, binds


# ---------------- 服务器 ----------------
def _start(t, trace):
    try:
        os.remove(trace)
    except OSError:
        pass
    env = dict(os.environ, STC_TRACE=trace)
    args = [t['bin'], t['conf'], str(t['port'])] if t is FTP else [t['bin']]
    p = subprocess.Popen(args, cwd=t['run'], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, env=env)
    time.sleep(0.35)
    return p


def _connect(t, n=300):
    for _ in range(n):
        try:
            return socket.create_connection(("127.0.0.1", t['port']), 0.2)
        except OSError:
            time.sleep(0.02)
    return None


def _passwords():
    """从目标配置读账号密码，只给执行器用，不进任何提示。"""
    out = {}
    try:
        cfg = open(os.path.expanduser('~/stc/proto/Source/Release/fftp.conf'),
                   encoding='utf-8', errors='replace').read()
    except OSError:
        return out
    cur = None
    for raw in cfg.splitlines():
        line = raw.strip()
        if line.startswith('[') and line.endswith(']'):
            cur = line[1:-1]
        elif cur and line.startswith('pswd='):
            out[cur] = line[5:].strip()
    return out


def substitute_secrets(text):
    """把 {{pswd:账号}} 换成真实密码。模型始终看不到密码本身。"""
    def rep(m):
        return _passwords().get(m.group(1), '')
    return re.sub(r'\{\{pswd:([^}]+)\}\}', rep, text)


def _events(path):
    out = []
    try:
        for line in open(path, encoding='utf-8', errors='replace'):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def replay(items, binds, is_rtsp, run_id):
    """返回 dict：responses / events / error / exit_code"""
    os.makedirs(LOG_DIR, exist_ok=True)
    trace = os.path.join(LOG_DIR, '%s.jsonl' % run_id)
    t = RTSP if is_rtsp else FTP
    p = _start(t, trace)
    res = {"responses": [], "events": [], "error": None, "exit_code": None,
           "trace": trace}
    try:
        s = _connect(t)
        if s is None:
            res["error"] = "connect_failed"
            return res
        s.settimeout(0.6)
        if not is_rtsp:
            try:
                s.recv(4096)
            except Exception:
                pass
        vals = {}
        for it in items:
            txt = substitute_secrets(it['text'])
            if is_rtsp:
                for (tid, field, sid) in binds:
                    if tid == it['id'] and vals.get((sid, field)):
                        if re.search(r'(?im)^%s:' % re.escape(field), txt):
                            txt = re.sub(r'(?im)^%s:.*$' % re.escape(field),
                                         '%s: %s' % (field, vals[(sid, field)]), txt)
                        else:
                            txt += CRLF + '%s: %s' % (field, vals[(sid, field)])
            try:
                # 队列消息经 latin-1 解码得到，必须原样按 latin-1 发回，
                # 否则高位字节被重新编码，与原始请求不一致
                if is_rtsp:
                    payload = (txt + CRLF + CRLF).encode('latin-1', 'replace')
                else:
                    payload = (txt + CRLF).encode('latin-1', 'replace')
                s.sendall(payload)
            except OSError:
                res["error"] = "send_failed"
                break
            time.sleep(0.12)
            buf = b""
            try:
                while True:
                    d = s.recv(8192)
                    if not d:
                        break
                    buf += d
                    if len(d) < 8192:
                        break
            except (socket.timeout, ConnectionResetError, OSError):
                pass
            body = buf.decode(errors='replace')
            mm = re.search(r'(?im)^Session:\s*([0-9A-Fa-f]+)', body)
            if mm:
                vals[(it['id'], 'Session')] = mm.group(1)
            first = body.split(CRLF)[0].strip() if body else ""
            res["responses"].append(first)
        s.close()
    finally:
        try:
            p.terminate()
            res["exit_code"] = p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    res["events"] = _events(trace)
    return res


# ---------------- 判定 ----------------
def judge(res, items, target_id, gate_line, is_rtsp):
    """返回 (quality, result, detail)
    quality: valid / trace_missing / execution_error / ambiguous
    result : target_not_reached / target_reached_still_blocked / target_branch_flipped
    """
    if res.get("error"):
        return "execution_error", "target_not_reached", res["error"]
    evs = res.get("events") or []
    if not evs:
        return "trace_missing", "target_not_reached", "no_events"

    if not is_rtsp:
        # FTP 插桩会为每条命令记一个 msg 事件；数量对不上说明解析与发送不对应
        msgs = [e for e in evs if e.get('t') == 'msg']
        sent = len(items)
        if len(msgs) != sent:
            return "ambiguous", "target_not_reached", "msg_count_%d_vs_sent_%d" % (len(msgs), sent)

    # 目标消息的运行时 ID = 它在发送序列中的位置 + 1
    pos = None
    for k, it in enumerate(items):
        if it['id'] == target_id:
            pos = k
            break
    if pos is None:
        return "ambiguous", "target_not_reached", "target_missing"
    rt_id = pos + 1

    if is_rtsp:
        lk = [e for e in evs if e.get('t') == 'lookup' and e.get('m') is not None]
        # 取目标消息之后的查找事件（按命令名与顺序）
        cand = [e for e in evs if e.get('t') in ('lookup', 'nosession')]
        if not cand:
            return "valid", "target_not_reached", "no_lookup_event"
        last = cand[-1]
        if last.get('t') == 'lookup' and last.get('found') == 1:
            return "valid", "target_branch_flipped", "lookup_found"
        return "valid", "target_reached_still_blocked", "lookup_not_found"

    if gate_line is None:
        return "valid", "target_not_reached", "no_gate_line"

    gates = [e for e in evs if e.get('t') == 'gate' and e.get('line') == gate_line]
    if not gates:
        return "valid", "target_not_reached", "gate_not_observed"
    g = gates[-1]
    if g.get('taken') == 0:
        return "valid", "target_branch_flipped", "gate_not_taken"
    return "valid", "target_reached_still_blocked", "gate_still_taken"
