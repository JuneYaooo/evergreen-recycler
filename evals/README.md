# 评测（Evals V1）

本目录保存 evergreen-recycler 的行为证据：题集、量表、运行协议、真实产物与逐题判断。

## 评测分层

1. **脚本行为层**：对 [fixtures/](fixtures/README.md) 的合成夹具运行
   `scripts/build_schedule.py`（日期基准统一 `--as-of 2026-09-19`），逐条核对
   [cases_v1.jsonl](cases_v1.jsonl) 的 required/forbidden 原子检查，共 32 项
   （脚本为确定性统计与排期，case e7 显式验证两次运行三份输出 sha256 一致）。
2. **Agent 工作流层**：Agent 按 SKILL.md 第 4 步对排期表逐条填写理由位与文案变体方向，
   产物见 [runs_v1/agent_variants_sample.md](runs_v1/agent_variants_sample.md)，
   按 [rubric_v1.md](rubric_v1.md) 三维度判定。

## 当前状态（2026-09-19，v0.1.0）

- **9/9 用例通过，0 硬失败，32/32 原子检查通过**；逐题判断见
  [judgments_v1.jsonl](judgments_v1.jsonl)，汇总见 [summary_v1.json](summary_v1.json)
  （均值：理解 3.67 / 真实效果 4.0 / 迭代 3.44 / 评测 3.89 / 展示诚信 3.44，0–4 分制）。
- 覆盖：赢家检测（是否落在设计的高互动帖）、排期约束（7 天滚动上限/1 天间隔/60 天
  再发间隔）、稀疏平台降级、ledger 防重复、全输家诚实空结果、冷启动建议、确定性
  sha256、缺字段容忍、变体红线九类行为。
- 真实产物与哈希：[runs_v1/](runs_v1/)（主夹具排期表/CSV/JSON、ledger 对照、
  全输家、冷启动、两次确定性运行、Agent 变体填写示例）。
- 夹具全部为合成样本（见 [fixtures/README.md](fixtures/README.md)），账号、标题、
  链接、数据均为虚构。
- **已知限制**：判定为开发 Agent 自评（model_only），未独立人工复核；夹具是"赢家
  是否落在设计高互动帖"的构造性验证，不等于真实账号上的翻红效果（后者需要真实
  发布后的回流数据）。

## 复现

命令与参数见 [docs/usage.md](../docs/usage.md)；脚本层全程离线，无需任何 API 密钥。
两轮真实缺陷与修复见 [iteration_notes.md](iteration_notes.md)。
