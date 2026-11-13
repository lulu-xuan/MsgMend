#!/bin/bash
# 随机修复对照：单臂 3 次独立运行。
# 与已有的 ChatAFL baseline 3 次运行同配置，可直接对比。

set -u
IMG=lightftp-chatafl:latest
SEEDS=$HOME/stc/pairs/chatafl-random
RES=$HOME/stc/exp_random
T=${T:-3600}
SKIP=${SKIP:-10}
mkdir -p "$RES"
log() { echo "[$(date +%m-%d\ %H:%M:%S)] $*" | tee -a "$RES/timeline.log"; }

for r in 1 2 3; do
  docker rm -f "pr-r$r" >/dev/null 2>&1
  docker run -d --name "pr-r$r" -v "$SEEDS":/seeds:ro -e INPUTS=/seeds "$IMG" \
    bash -lc "cd /home/ubuntu/experiments && ./run aflnet out-rnd-r$r '-P FTP -D 10000 -q 3 -s 3 -E -K -m none -t 20000+' $T $SKIP" >/dev/null 2>&1
  log "launch pr-r$r"
done

while true; do
  alive=0
  for r in 1 2 3; do docker ps --format '{{.Names}}' | grep -qx "pr-r$r" && alive=1; done
  [ "$alive" -eq 0 ] && break
  sleep 60
done

for r in 1 2 3; do
  docker cp "pr-r$r":/home/ubuntu/experiments/LightFTP/Source/Release/out-rnd-r$r "$RES/" >/dev/null 2>&1
  docker rm -f "pr-r$r" >/dev/null 2>&1
  log "collect out-rnd-r$r"
done
log "===== random-repair experiment done ====="
