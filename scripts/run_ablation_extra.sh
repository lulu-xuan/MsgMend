#!/bin/bash
# 把消融对照（随机修复 / V1 / V1b）从 3 次补到 5 次，与 V2 的 5 次对齐。
# 语料与配置与前几次完全一致。

set -u
IMG=lightftp-chatafl:latest
ROOT=$HOME/stc/pairs
T=${T:-3600}
SKIP=${SKIP:-10}
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$HOME/stc/exp_ablation2/timeline.log"; }
mkdir -p "$HOME/stc/exp_ablation2"

launch() {  # name corpus outdir resultroot
  local name=$1 corp=$2 out=$3 res=$4
  docker rm -f "$name" >/dev/null 2>&1
  docker run -d --name "$name" -v "$ROOT/chatafl-$corp":/seeds:ro -e INPUTS=/seeds "$IMG" \
    bash -lc "cd /home/ubuntu/experiments && ./run aflnet $out '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  echo "$name|$out|$res" >> "$HOME/stc/exp_ablation2/pending.txt"
  log "launch $name (corpus=$corp)"
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

collect_all() {
  while IFS='|' read -r name out res; do
    docker cp "$name":/home/ubuntu/experiments/LightFTP/Source/Release/"$out" "$res/" >/dev/null 2>&1
    docker rm -f "$name" >/dev/null 2>&1
    log "collect $out -> $res"
  done < "$HOME/stc/exp_ablation2/pending.txt"
  rm -f "$HOME/stc/exp_ablation2/pending.txt"
}

log "===== ablation extra start ====="

# 第 4 次：三个臂并行
launch a2-rand-r4 random out-rnd-r4 "$HOME/stc/exp_random"
launch a2-v1-r4   v1     out-v1-r4  "$HOME/stc/exp_variants"
launch a2-v1b-r4  v1b    out-v1b-r4 "$HOME/stc/exp_variants"
wait_all a2-rand-r4 a2-v1-r4 a2-v1b-r4
collect_all

# 第 5 次：三个臂并行
launch a2-rand-r5 random out-rnd-r5 "$HOME/stc/exp_random"
launch a2-v1-r5   v1     out-v1-r5  "$HOME/stc/exp_variants"
launch a2-v1b-r5  v1b    out-v1b-r5 "$HOME/stc/exp_variants"
wait_all a2-rand-r5 a2-v1-r5 a2-v1b-r5
collect_all

log "===== ablation extra done ====="
