#!/bin/bash
# 主流 fuzzer 头对头基线：AFLNet 与 StateAFL，各 3 次独立运行 × 1 小时。
# 使用 ProFuzzBench 默认种子（in-ftp / in-ftp-replay），与「修复语料」实验区分开。

set -u
RES=$HOME/stc/exp_baselines
T=${T:-3600}
SKIP=${SKIP:-10}
mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

launch() {  # name image fuzzer outdir
  docker rm -f "$1" >/dev/null 2>&1
  docker run -d --name "$1" "$2" bash -lc \
    "cd /home/ubuntu/experiments && ./run $3 $4 '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  log "launch $1 ($3)"
}

run_batch() {
  local specs=("$@")
  for s in "${specs[@]}"; do
    IFS='|' read -r n img fz out <<< "$s"
    launch "$n" "$img" "$fz" "$out"
  done
  while true; do
    alive=0
    for s in "${specs[@]}"; do
      IFS='|' read -r n _ _ _ <<< "$s"
      docker ps --format '{{.Names}}' | grep -qx "$n" && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 60
  done
  for s in "${specs[@]}"; do
    IFS='|' read -r n img fz out <<< "$s"
    base="/home/ubuntu/experiments/LightFTP/Source/Release"
    [ "$fz" = "stateafl" ] && base="/home/ubuntu/experiments/LightFTP-stateafl/Source/Release"
    docker cp "$n":"$base/$out" "$RES/" >/dev/null 2>&1
    docker rm -f "$n" >/dev/null 2>&1
    log "collect $out"
  done
}

log "===== baselines start ====="
run_batch \
  "b-afl-r1|lightftp-chatafl|aflnet|out-afl-r1" \
  "b-afl-r2|lightftp-chatafl|aflnet|out-afl-r2" \
  "b-afl-r3|lightftp-chatafl|aflnet|out-afl-r3"

log "----- aflnet done, stateafl start -----"
run_batch \
  "b-sa-r1|lightftp-stateafl|stateafl|out-sa-r1" \
  "b-sa-r2|lightftp-stateafl|stateafl|out-sa-r2" \
  "b-sa-r3|lightftp-stateafl|stateafl|out-sa-r3"

log "===== baselines done ====="
