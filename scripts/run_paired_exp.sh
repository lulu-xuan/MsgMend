#!/bin/bash
# 配对覆盖率实验：原始语料（Baseline） vs 修复语料（Ours）
# 同一 Fuzzer（AFLNet）、同一镜像、同一预算，只差初始种子目录。
# 分两批各 3 个并行容器，批次内交错 Baseline 与 Ours 以抵消时间效应。

set -u
IMG=lightftp-chatafl:latest
ROOT=$HOME/stc/pairs
RES=$HOME/stc/exp_pairs
T=${T:-3600}
SKIP=${SKIP:-10}
BASE=$ROOT/chatafl-baseline
OURS=$ROOT/chatafl-repaired

mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

launch() {   # name seeddir outdir
  docker rm -f "$1" >/dev/null 2>&1
  docker run -d --name "$1" -v "$2":/seeds:ro -e INPUTS=/seeds "$IMG" \
    bash -lc "cd /home/ubuntu/experiments && ./run aflnet $3 '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  log "launch $1  seeds=$2  out=$3"
}

collect() {  # name outdir
  docker cp "$1":/home/ubuntu/experiments/LightFTP/Source/Release/"$2" "$RES/" >/dev/null 2>&1
  docker rm -f "$1" >/dev/null 2>&1
  log "collect $2"
}

run_batch() {  # 参数形如 name|seeddir|outdir
  local specs=("$@")
  for spec in "${specs[@]}"; do
    IFS='|' read -r n s o <<< "$spec"
    launch "$n" "$s" "$o"
  done
  # 等这批容器全部退出（含覆盖率采集阶段）
  while true; do
    alive=0
    for spec in "${specs[@]}"; do
      IFS='|' read -r n _ _ <<< "$spec"
      if docker ps --format '{{.Names}}' | grep -qx "$n"; then alive=1; fi
    done
    [ "$alive" -eq 0 ] && break
    sleep 60
  done
  for spec in "${specs[@]}"; do
    IFS='|' read -r n _ o <<< "$spec"
    collect "$n" "$o"
  done
}

log "===== paired experiment start (T=${T}s, skip=${SKIP}) ====="
cp "$(dirname "$0")/../audit_v1/rq3_pairs.csv" "$RES/rq3_pairs.csv" 2>/dev/null

run_batch \
  "p-base-r1|$BASE|out-base-r1" \
  "p-ours-r1|$OURS|out-ours-r1" \
  "p-base-r2|$BASE|out-base-r2"

run_batch \
  "p-ours-r2|$OURS|out-ours-r2" \
  "p-base-r3|$BASE|out-base-r3" \
  "p-ours-r3|$OURS|out-ours-r3"

log "===== paired experiment done ====="
ls -d "$RES"/out-* 2>/dev/null | tee -a "$RES/timeline.log"
