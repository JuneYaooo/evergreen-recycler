# 评测（Evals V2，v0.3.0）

本目录保存 evergreen-recycler 的行为证据：题集、量表、运行协议、真实产物、改前改后对照和逐题判断。
V1（v0.1.0–v0.2.0）的材料原样保留，用来追溯历史。

## 当前状态（2026-11-02，v0.3.0）

- **18/18 用例通过，0 硬失败**：脚本层 17 个用例共 **47/47 项原子检查**由
  [scripts/check_v2.py](scripts/check_v2.py) 对真实产物自动复算（结果见
  [runs_v2/check_results.json](runs_v2/check_results.json)）；Agent 层 1 个用例按量表自评。
  单元测试 30/30 通过。
- 逐题判断：[judgments_v2.jsonl](judgments_v2.jsonl)；汇总：[summary_v2.json](summary_v2.json)
  （由 [scripts/aggregate_results.py](scripts/aggregate_results.py) 从逐题判断生成，
  通过率 Wilson 95% 区间 [0.82, 1.00]）。
- 题集 [cases_v2.jsonl](cases_v2.jsonl)、量表 [rubric_v2.md](rubric_v2.md)、协议 [protocol_v2.json](protocol_v2.json)。

## 评测分层

1. **脚本行为层**：对 [fixtures/](fixtures/README.md) 的合成夹具运行 `scripts/build_schedule.py`
   （基准日统一 2026-09-19），复现命令在 [scripts/run_v2.sh](scripts/run_v2.sh)。e1–e10 沿用 V1 用例；
   其中 e2、e9、e10 按 v0.3.0 的新约束更新了期望。e11–e17 是本轮针对调研发现的问题新增的回归用例：
   录错日期、新帖冷却、收藏/转发、滚动基线、`--min-sample` 贯通、时效提示、互动全空。
2. **Agent 工作流层**：Agent 按 SKILL.md 第 3-4 步处理脚本信号并填写理由与变体方向，
   产物 [runs_v2/agent_variants_sample_v2.md](runs_v2/agent_variants_sample_v2.md)。

## 改前 / 改后对照

同一输入下 v0.2.0 与 v0.3.0 的差异见 [runs_v2/before_after.md](runs_v2/before_after.md)。要点：

- 逻辑夹具上，v0.2.0 排出的 4 条里有 2 条是错的：一条发布日期录错（距首发 -16 天），
  一条发布才 18 天。v0.3.0 跳过前者、把后者放进待定，并找回了收藏型干货。
- 旧主夹具上，排期的日期、平台、帖子逐行不变，默认参数向后兼容。

## 已知限制

- 全部夹具是合成样本，**没有在真实账号上验证翻红效果**；评测验证的是「规则是否按设计执行」，
  不是「翻红后流量会涨」。
- Agent 层判定是开发 Agent 自评（model_only），没有独立人工复核。
- 没有「无 Skill」baseline 条件，对照对象是上一版本 v0.2.0。

## V1 历史材料

[cases_v1.jsonl](cases_v1.jsonl)、[rubric_v1.md](rubric_v1.md)、[protocol_v1.json](protocol_v1.json)、
[judgments_v1.jsonl](judgments_v1.jsonl)、[summary_v1.json](summary_v1.json)、[runs_v1/](runs_v1/)：
v0.2.0 时期 10/10 用例、46 项原子检查（GLM / ZCode CLI 自评）。V1 的 e9 期望里包含
「小红书 180 天内容指纹」，本轮查不到官方出处，已在 V2 改为禁止项。

缺陷与修复的完整过程见 [iteration_notes.md](iteration_notes.md)。
