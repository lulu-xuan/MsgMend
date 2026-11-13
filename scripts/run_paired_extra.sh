#!/bin/bash
# 配对覆盖率实验：在第 1–3 次的基础上补第 4、5 次。
# 目的：把核心证据从每组 3 次扩到 5 次（论文惯例是 10 次）。
# 语料与配置与前三次完全一致。

set -u
IMG=lightftp-chatafl:latest
ROOT=$HOME/stc/pairs
RES=$HOME/stc/exp_pairs2
T=${T:-3600}
SKIP=${SKIP:-10}
mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

launch() {
  local name=$1 seeds=$2 out=$3
  docker rm -f "$name" >/dev/null 2>&1
  docker run -d --name "$name" -v "$seeds":/seeds:ro -e INPUTS=/seeds "$IMG" \
    bash -lc "cd /home/ubuntu/experiments && ./run aflnet $out '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  log "launch $name"
}

wait_all() {
  local names=("$@")
  while true; do
    local alive=0
    for n in "${names[@]}"; do
      docker ps --format '{{.Names}}' | grep -qx "$n" && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 60
  done
}

collect() {
  local name=$1 out=$2
  docker cp "$name":/home/ubuntu/experiments/LightFTP/Source/Release/"$out" "$RES/" >/dev/null 2>&1
  docker rm -f "$name" >/dev/null 2>&1
  log "collect $out"
}

log "===== paired extra start ====="

# 第一批：base-r4, ours-r4, base-r5（三个并行）
launch p2-base-r4 "$ROOT/chatafl-baseline" out-base-r4
launch p2-ours-r4 "$ROOT/chatafl-repaired" out-ours-r4
launch p2-base-r5 "$ROOT/chatafl-baseline"  out-base-r5
wait_all p2-base-r4 p2-ours-r4 p2-base-r5
collect p2-base-r4 out-base-r4
collect p2-ours-r4 out-ours-r4
collect p2-base-r5 out-base-r5

# 第二批：ours-r5
launch p2-ours-r5 "$ROOT/chatafl-repaired" out-ours-r5
wait_all p2-ours-r5
collect p2-ours-r5 out-ours-r5

log "===== paired extra done ====="
