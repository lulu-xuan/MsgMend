#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为一个失败案例生成 B0–B3 四份 prompt（证据逐层递增），并要求**可执行的**修复动作。

设计原则（来自指导2）
    - 四组的源码范围、请求响应、参考轨迹、预算完全相同，只有证据层不同；
    - 参考轨迹对四组都提供，不能让 B3 独享成功答案；
    - B2 只给"状态写入的位置（源码处）"，隐藏写入消息的身份；
    - B3 额外给"是哪一条消息写的"和值来源。

输出格式改为**可执行**：插入 / 替换 / 绑定，带消息下标，
这样评测可以做**真实重放验证**，而不是靠关键词猜对错。

输出
    packs/<case_id>/{context.md,B0.md,B1.md,B2.md,B3.md}
"""

import json
import os
import re
import sys

OUT_DEFAULT = os.path.expanduser('~/stc/packs')

TASK = """## 任务

上面是一次失败的会话，消息从 0 开始编号。

请给出修复方案。**只允许以下三种动作**：

- `insert_before`：在第 N 条消息**之前**插入一条消息
  `{"op":"insert_before","index":N,"message":"<完整消息一行>"}`
- `replace_message`：把第 N 条消息**整体替换**
  `{"op":"replace_message","index":N,"message":"<完整消息一行>"}`
- `bind_field`：把第 N 条消息的某字段，绑定为第 M 条消息**响应**里的对应值
  `{"op":"bind_field","index":N,"field":"<字段名>","from_index":M}`

输出严格 JSON：
```json
{"actions":[...],"reason":"<一句话>"}
```

最多 2 个动作。信息不足时输出 `{"actions":[],"reason":"insufficient evidence"}`。
不要修改服务器状态，不要写死一次性动态值（需要的话用 bind_field）。

**密码**：配置里的密码字段已脱敏。需要某个账号的密码时写成
`PASS {{pswd:<账号名>}}`，执行器会在发送前替换为真实密码，你不需要知道密码内容。
"""


def read(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


def deinstrument(t):
    t = t.replace('STC_EQ(context, context->Access, FTP_ACCESS_NOT_LOGGED_IN)',
                  'context->Access == FTP_ACCESS_NOT_LOGGED_IN')
    t = t.replace('STC_LT(context, context->Access, FTP_ACCESS_FULL)',
                  'context->Access < FTP_ACCESS_FULL')
    t = t.replace('STC_LT(context, context->Access, FTP_ACCESS_CREATENEW)',
                  'context->Access < FTP_ACCESS_CREATENEW')
    return re.sub(r'STC_WRITE\((context|&ctx), Access, ([^;]+)\);', r'\1->Access = \2;', t)


def slice_between(text, a, b):
    i = text.find(a)
    if i < 0:
        return ''
    j = text.find(b, i)
    return text[i:j if j > 0 else i + 1500]


def func_at(src, line, span=45):
    """取出 line 所在的函数片段。line 为 1 基行号。"""
    lines = src.splitlines()
    if not line or line > len(lines):
        return ''
    start = 0
    for i in range(line - 1, -1, -1):
        if re.match(r'^(int|void|unsigned)\s+ftp[A-Za-z0-9]*\(', lines[i]):
            start = i
            break
    return '\n'.join(lines[start:min(len(lines), start + span)])


def lightftp_slices(gate_line=None, write_line=None):
    """按实际失败分支与写入位置取源码，不再固定给 ftpPWD 片段。"""
    src = read(os.path.expanduser('~/stc/proto/Source/ftpserv.c'))
    if gate_line:
        gate = func_at(src, gate_line)
    else:
        gate = slice_between(src, 'int ftpPWD(PFTPCONTEXT context', 'int ftpTYPE(')
    if write_line:
        write = func_at(src, write_line)
    else:
        write = slice_between(src,
                              'context->Access = FTP_ACCESS_NOT_LOGGED_IN;\n\t\ndo {',
                              'return sendstring(context, error530_b);')
    return deinstrument(gate), deinstrument(write)


def live555_slices():
    src = read(os.path.expanduser('~/stc/live555/liveMedia/RTSPServer.cpp'))
    gen = read(os.path.expanduser('~/stc/live555/liveMedia/GenericMediaServer.cpp'))
    return (slice_between(src, 'Boolean const requestIncludedSessionId',
                          '// We now have a complete RTSP request.'),
            slice_between(gen, 'GenericMediaServer::createNewClientSessionWithId()',
                          'GenericMediaServer::lookupClientSession(u_int32_t'))


def build_case(case_dir, out_root):
    ev = json.load(open(os.path.join(case_dir, 'evidence.json'), encoding='utf-8'))
    cid = ev['case_id']
    is_ftp = cid[0] in ('A', 'C', 'N')

    if is_ftp:
        fl = ev.get('failure') or {}
        site = ((ev.get('state_provenance') or {}).get('last_write') or {}).get('site') or ''
        mw = re.search(r':(\d+)$', site)
        gate_src, write_src = lightftp_slices(
            fl.get('gate_line'), int(mw.group(1)) if mw else None)
        target = 'LightFTP (FTP)'
    else:
        gate_src, write_src = live555_slices()
        target = 'Live555 (RTSP)'

    msgs = ev.get('messages') or ev.get('failed_sequence') or []
    resps = ev.get('responses') or []

    d = os.path.join(out_root, cid)
    os.makedirs(d, exist_ok=True)

    ctx = ['# 目标：%s' % target, '', '## 失败的会话（消息从 0 编号）', '```']
    for i, m in enumerate(msgs):
        r = resps[i] if i < len(resps) else ''
        shown = m.replace(chr(13)+chr(10), ' | ').replace(chr(10), ' | ')

        ctx.append('[%d] %-46s -> %s' % (i, shown, r))
    ctx += ['```', '']
    # 目标消息属于四组共有的基础信息：不指明哪一条失败，任务本身就是欠定义的
    tgt_i = ev.get('target_msg_index')
    if isinstance(tgt_i, int) and 0 <= tgt_i < len(msgs):
        shown_t = msgs[tgt_i].replace(chr(13) + chr(10), ' | ').replace(chr(10), ' | ')
        ctx += ['## 失败位置', '',
                '第 %d 条消息 `%s` 被状态判断拒绝，修复目标是让它通过。' % (tgt_i, shown_t), '']
    ctx += ['## 参考：同一目标上成功走通的轨迹', '```',
            ev.get('reference_trace_text', '(无)'), '```', '']
    ctx += ['## 相关源码', '### 失败判定所在的函数', '```c', gate_src.strip(), '```',
            '### 与该状态相关的写入代码', '```c', write_src.strip(), '```']

    if is_ftp:
        cfg = read(os.path.expanduser('~/stc/proto/Source/Release/fftp.conf'))
        i = cfg.find('[anonymous]')
        if i > 0:
            # 凭据不得进入发往模型 API 的提示
            redacted = re.sub(r'(?m)^\s*pswd=.*$', 'pswd=<redacted>', cfg[i:].strip())
            ctx += ['', '## 目标服务器的账号配置', '```ini', redacted, '```']

    context = "\n".join(ctx)
    open(os.path.join(d, 'context.md'), 'w', encoding='utf-8').write(context)

    fail = ev.get('failure', {})
    prov = ev.get('state_provenance', {})
    base = {"branch": fail.get('branch_id'), "lhs": fail.get('lhs'),
            "operator": fail.get('operator'), "rhs": fail.get('rhs')}

    base_json = json.dumps(base, ensure_ascii=False, indent=2)
    lw = prov.get('last_write') or {}
    site_only = {k: lw[k] for k in ('variable', 'site', 'old', 'new')
                 if k in lw and lw[k] is not None} or {'site': '(未采集)'}
    with_identity = {
        "variable": prov.get('variable'),
        "last_write": {k: lw[k] for k in ('message_id', 'command', 'site', 'old', 'new')
                       if k in lw and lw[k] is not None},
        "event_order": prov.get('event_order'),
        "value_source": prov.get('value_source'),
    }
    human = {k: prov[k] for k in ('derived_from', 'interpretation') if prov.get(k)}

    layers = {
        # B0 是额外的无证据对照，不属于 E0–E3 序列
        'B0': '（本组不提供任何运行时分支信息。）',
        'E0': '## 额外证据：失败分支实际比较的操作数\n```json\n%s\n```' % base_json,
        'E1': '## 额外证据\n### 失败分支实际比较的操作数\n```json\n%s\n```\n'
              '### 该状态的写入位置（源码处，不含消息身份）\n```json\n%s\n```\n'
              '（只给出代码位置与旧新值，不说明是哪一条消息触发的写入。）'
              % (base_json, json.dumps(site_only, ensure_ascii=False, indent=2)),
        'E2': '## 额外证据\n### 失败分支实际比较的操作数\n```json\n%s\n```\n'
              '### 该状态的写入来源（自动采集，含消息身份）\n```json\n%s\n```'
              % (base_json, json.dumps(with_identity, ensure_ascii=False, indent=2)),
        'E3': '## 额外证据\n### 失败分支实际比较的操作数\n```json\n%s\n```\n'
              '### 该状态的写入来源（自动采集，含消息身份）\n```json\n%s\n```\n'
              '### 人工补充说明（非自动采集）\n```json\n%s\n```'
              % (base_json,
                 json.dumps(with_identity, ensure_ascii=False, indent=2),
                 json.dumps(human, ensure_ascii=False, indent=2) if human
                 else '{"note":"本例无人工补充说明"}'),
    }

    for name, layer in layers.items():
        open(os.path.join(d, name + '.md'), 'w', encoding='utf-8').write(
            context + "\n\n" + layer + "\n\n" + TASK)

    print('生成 %-34s 消息 %d 条' % (cid, len(msgs)))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else OUT_DEFAULT
    os.makedirs(out, exist_ok=True)
    base = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else '~/stc/cases')
    for case in sorted(os.listdir(base)):
        p = os.path.join(base, case)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, 'evidence.json')):
            build_case(p, out)
    print('done ->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
