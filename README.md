# MsgMend

**Repairing Stateful Protocol Message Sequences with Runtime State Provenance**

---

## What this is

Stateful protocol fuzzers (AFLNet, ChatAFL, StateAFL) produce sequences of protocol messages. A sequence often stalls at a server-side state check: the server rejects one command because some earlier message left its internal state in a condition that fails the check. Everything downstream of the rejected branch is then never executed, and coverage plateaus.

The common instinct is to edit the rejected command. Empirically, **the rejected command is usually fine** — the defect is an earlier message that wrote the wrong value.

This repository implements a repair layer that:

1. **Collects runtime evidence** at the failing check — the two operands being compared, and which message last wrote that state.
2. **Classifies the failure** into one of two families: a missing prerequisite message, or a wrong value that must be rebound.
3. **Repairs only what the evidence points to**, producing a new message sequence.
4. **Returns the repaired sequence to the fuzzer's seed corpus.**

It runs **on top of** existing fuzzers; it does not modify them. The fuzzer's queue is read, repaired sequences are written back as seeds.

> 中文摘要：针对有状态协议模糊测试的覆盖停滞，在服务器做状态检查的位置采集两样运行时信息——比较的两个值、以及这个状态最后由哪条消息写入——据此判断缺的是一条前置消息还是一个需要绑定的值，只修补定位到的那条消息，把修好的序列放回 fuzzer 的种子集合。本仓库只包含修复层本身，不含汇报材料与参考文献。

---

## Repository layout

```
scripts/
  auto_provenance.py       Collect runtime evidence for a failing sequence
  find_natural_case.py     Replay helper (runs a sequence against a local server)
  find_identity_case.py    Scan a queue directory for candidate sequences
  eval_lib.py              Unified replay/judging library (stable message IDs, binds)
  oracle_tests.py          9 regression tests for the evaluator
  rejudge.py               Re-judge saved results with the unified evaluator
  nat_ablation.py          Compare repair strategies on natural cases
  make_variants.py         Build alternative-repair corpora (V1, V1b)
  make_random_repair.py    Build the random-repair control corpus
  make_evidence_packs.py   Build E0–E3 evidence packs for the LLM experiments
  run_rq2.py               Single-sample LLM experiment driver
  run_rq2_reps.py          Repeated-sampling LLM driver
  run_rq2_v2.py            Frozen-prompt experiment (15 cases, dev/holdout split)
  rq3_seed_repair.py       Batch-produce repaired sequences from a queue
  build_pairs.py           Build paired corpora and the pairing manifest
  scan_rtsp.py             Scan RTSP queues for session-lookup failures
  test_rtsp_repair.py      Verify session binding repair on RTSP
  run_*.sh                 Experiment drivers (paired, ablation, baselines)

analysis/
  analyze_pair5.py         Paired coverage experiment, n=5
  analyze_five5.py         Five-arm ablation, n=5

protocol/
  protocol_v2.md           Pre-registered sampling and evaluation rules

results/
  repair_quality_47_cases.csv     Repair hit rate on 47 natural cases
  coverage_paired_n5.json         Paired coverage results (n=5)
  ablation_five_arms_n5.json      Five-arm ablation results (n=5)
  llm_evidence_ablation.json      LLM evidence-condition results
```

---

## Requirements

- Linux (tested on Ubuntu 22.04, 4 cores)
- Python 3.8+
- Docker
- [ProFuzzBench](https://github.com/profuzzbench/profuzzbench) — provides the instrumented targets and the coverage pipeline
- AFLNet 2.56b (or ChatAFL) inside the ProFuzzBench images
- Two system settings, required by AFL; they reset on reboot:

```bash
echo core | sudo tee /proc/sys/kernel/core_pattern
sudo sysctl -w kernel.randomize_va_space=0
```

For the LLM experiments, an API key is read from `~/.dskey` at runtime. **No credentials are stored in this repository.**

---

## How the pieces fit

**Evidence collection** (`auto_provenance.py`) replays one queue entry against an instrumented server, finds the first command rejected by a state check, and walks back through the trace to the write that produced the current value. Three conditions are enforced:

- message identity is stable (replace keeps the ID, insert allocates a new one);
- the write must precede the read **in full trace order**, not by comparing message numbers;
- writer and reader must belong to the same session.

**Judging** (`eval_lib.py`) works at the sequence level: a repair is counted as correct when the edit lands on the message that actually wrote the state (or its paired neighbor). This does not require re-execution.

**Evaluation** (`oracle_tests.py`) covers the failure modes that matter: empty trace, early exit, still blocked, genuine flip, flip-then-blocked-again, unobserved check, duplicate command names, bind-after-insert, and RTSP lookup.

---

## Results

All numbers are branch coverage (`b_abs`, gcov) after 1 hour, five independent runs per arm.

**Paired experiment** — two corpora with the same number of seeds (36) from the same source; only difference is whether the sequences were repaired:

| Arm | Branch coverage | Relative |
|---|---|---|
| Baseline (original sequences) | 334.8 ± 0.8 | — |
| Ours (repaired sequences) | 362.0 ± 2.3 | +8.1% |

Vargha–Delaney Â12 = 1.000 over 25 cross-arm pairs. A second, independently sourced corpus gives +8.3%.

**Ablation** — same edit budget for every arm (72 edits):

| Arm | Branch coverage | Relative |
|---|---|---|
| Baseline | 334.8 ± 0.8 | — |
| Random edits | 346.4 ± 7.9 | +3.5% |
| V1b — rewrite all logins | 359.0 ± 0.7 | +7.2% |
| V1 — rewrite the first login | 359.4 ± 1.1 | +7.3% |
| **Ours (V2) — repair by provenance** | **362.0 ± 2.3** | **+8.1%** |

Roughly 43% of the gain comes from any structural edit; 57% comes from editing the right message.

**Repair quality** — on 47 natural failing sequences:

| Repair strategy | Level-gate cases (23) | Not-logged-in cases (24) | Mean edits |
|---|---|---|---|
| Position-only | 0 | 0 | 2.0 |
| Rewrite all logins | 20 | 0 | 4.3 |
| **Provenance-guided** | **20** | **24** | **1.7** |

**LLM evidence ablation** — 15 cases, 9 development / 6 held out, frozen prompt:

| Condition | Dev hit rate | Holdout hit rate |
|---|---|---|
| E0 — comparison values | 30.8% | 22.2% |
| E1 — + write site and old/new value | 33.3% | 22.2% |
| **E2 — + which message wrote it** | **74.1%** | **61.1%** |
| E3 — + human note | 59.3% | 50.0% |

E1 does not improve over E0 at all; adding message identity roughly doubles the hit rate on held-out cases.

---

## Limitations

- **Scale.** 1 hour × 5 runs × 2 targets. Published work in this area typically reports 24 hours × 10 runs × 6–13 targets.
- **Corpus size.** Official AFLNet and StateAFL baselines start from 2 seeds; the experiments here use 36. Absolute coverage between those settings is **not comparable**, and no such comparison is claimed.
- **No system-level head-to-head.** ChatAFL has not yet been run as a complete tool against this method on equal footing.
- **Cross-protocol scope.** On Live555 (RTSP) the mechanism was verified — 88% of sampled queue entries fail at session lookup, and binding every message that carries the session ID repairs 12/12 — but no coverage experiment was run there. The session ID is generated at runtime and cannot be baked into a static seed corpus.
- **No vulnerability claims.** Crashes have not been deduplicated or root-caused.

---

## Status

Research prototype accompanying an ongoing paper. Interfaces will change.

---

## License

Released under the MIT License.
