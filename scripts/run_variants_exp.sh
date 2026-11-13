#!/bin/bash
# V1 / V1b 修复策略对照：两种修法各 3 次独立运行，交错执行。
# 与已完成的 Baseline / 随机修复 / V2 三组同配置。

set -u
IMG=lightftp-chatafl:latest
ROOT=$HOME/stc/pairs
RES=$HOME/stc/exp_variants
T=${T:-3600}
SKIP=${SKIP:-10}
mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

launch() {  # name corp out
  docker rm -f "$1" >/dev/null 2>&1
  docker run -d --name "$1" -v "$ROOT/chatafl-$2":/seeds:ro -e INPUTS=/seeds "$IMG" \
    bash -lc "cd /home/ubuntu/experiments && ./run aflnet $3 '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  log "launch $1 (corpus=$2)"
}

run_batch() {
  local specs=("$@")
  for s in "${specs[@]}"; do
    IFS='|' read -r n c o <<< "$s"
    launch "$n" "$c" "$o"
  done
  while true; do
    alive=0
    for s in "${specs[@]}"; do
      IFS='|' read -r n _ _ <<< "$s"
      docker ps --format '{{.Names}}' | grep -qx "$n" && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 60
  done
  for s in "${specs[@]}"; do
    IFS='|' read -r n _ o <<< "$s"
    docker cp "$n":/home/ubuntu/experiments/LightFTP/Source/Release/"$o" "$RES/" >/dev/null 2>&1
    docker rm -f "$n" >/dev/null 2>&1
    log "collect $o"
  done
}

log "===== variants experiment start ====="
run_batch \
  "pv1-r1|v1|out-v1-r1" \
  "pv1b-r1|v1b|out-v1b-r1" \
  "pv1-r2|v1|out-v1-r2"

run_batch \
  "pv1b-r2|v1b|out-v1b-r2" \
  "pv1-r3|v1|out-v1-r3" \
  "pv1b-r3|v1b|out-v1b-r3"

log "===== variants experiment done ====="
