#!/bin/bash
# StateAFL 基线：串行跑 3 次。
# 原因：StateAFL 的状态快照对时序敏感，并发运行时 IPSM 初始化会崩
# （"states hashtable should always contain an entry of the initial state"）。

set -u
RES=$HOME/stc/exp_baselines
T=${T:-3600}
SKIP=${SKIP:-10}
OPTS="-P FTP -D 10000 -q 3 -s 3 -E -K -m none -u /home/ubuntu/experiments/LightFTP/Source/Release/fftp -t 5000"
mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

wait_gone() {
  local name=$1
  while docker ps --format '{{.Names}}' | grep -qx "$name"; do sleep 60; done
}

run_one() {
  local r=$1
  local name="b-sa2-r$r"
  local out="out-sa2-r$r"
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
    docker run -d --name "$name" lightftp-stateafl bash -lc \
      "cd /home/ubuntu/experiments && ./run stateafl $out '$OPTS' $T $SKIP" >/dev/null 2>&1
    log "launch $name"
  else
    log "reuse running $name"
  fi
  wait_gone "$name"
  docker cp "$name":/home/ubuntu/experiments/LightFTP-stateafl/Source/Release/"$out" "$RES/" >/dev/null 2>&1
  docker rm -f "$name" >/dev/null 2>&1
  log "collect $out"
}

START=${1:-1}
log "===== stateafl serial start (from r$START) ====="
for r in $(seq $START 3); do run_one $r; done
log "===== stateafl serial done ====="
