# 使用与维护文档

## 命令

```bash
python3 scripts/build_schedule.py posts.csv --as-of 2026-09-19 \
    -o 排期表.md --csv schedule.csv --json 汇总.json \
    --ledger ledger.json
```

## 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `posts`（位置参数） | 必填 | 历史帖子 CSV，字段定义见 references/排期规则与字段.md |
| `-o, --output` | 打印到 stdout | 排期表 Markdown 输出路径 |
| `--csv` | 不输出 | schedule.csv 输出路径（utf-8-sig，Excel 可直接打开） |
| `--json` | 不输出 | 结构化汇总 JSON（模式、参数、各平台统计、排期与待定清单） |
| `--as-of` | 今天 | 基准日（ISO 格式）；评测与复现时固定该值 |
| `--start-date` | 基准日次日 | 排期起始日 |
| `--weeks` | 4 | 规划周数 |
| `--weekly-cap` | 3 | 每平台任意 7 天内排期上限 |
| `--min-gap-days` | 1 | 同平台两次排期日最小间隔 |
| `--recycle-gap-days` | 60 | 同帖距上次发布（含首发）的最小间隔 |
| `--min-sample` | 10 | 平台样本低于该数时降级为仅标记不排期 |
| `--median-x` | 3.0 | 赢家中位数倍数阈值 |
| `--min-percentile` | 75.0 | 赢家分位数下限 |
| `--like-weight` | 2 | 互动量中点赞权重（互动量 = views + likes×2 + comments×3） |
| `--comment-weight` | 3 | 互动量中评论权重 |
| `--metric` | total | 赢家口径：`total`=累计互动量（v0.1.0 行为）；`per_day`=日均互动量 = 互动量 ÷ max(存活天数, 1)，修正老帖的累计优势；报告与 CSV 均标注所用口径 |
| `--baseline` | platform | 赢家基线：`platform`=平台全量中位数（v0.2.0 行为）；`rolling`=同平台发布日期最近的 N 条（不含自身），账号体量变化大时用 |
| `--rolling-window` | 20 | 滚动基线样本数（≥3） |
| `--save-weight` | 2 | 互动量中收藏权重（CSV 有收藏列时生效） |
| `--share-weight` | 3 | 互动量中转发/分享权重（CSV 有转发/分享列时生效） |
| `--max-recycles` | 0 | 同帖累计再发次数上限（按 ledger 计），0=不限 |
| `--ledger` | 不读取 | 已再发记录 ledger.json，格式见 references/排期规则与字段.md |

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功（含冷启动建议、全账号无赢家等"诚实空结果"，都是正常输出） |
| 2 | 输入文件不存在 |
| 3 | 输入格式错误（缺必需列、坏 ledger JSON 等，stderr 给中文原因） |

## 运行模式

| 模式 | 触发条件 | 行为 |
| --- | --- | --- |
| schedule | 总有效帖 ≥20 | 常规赢家检测 + 排期 |
| cold_start | 总有效帖 <20 | 不排期，输出「先攒数据」建议与数据体检 |

## 测试与评测

```bash
python3 -m unittest discover tests     # 30 项单元测试
bash evals/scripts/run_v2.sh           # 重新生成 evals/runs_v2/ 全部产物
python3 evals/scripts/check_v2.py      # 对产物自动复算 47 项原子检查
python3 scripts/build_schedule.py evals/fixtures/posts_main_v1.csv \
    --as-of 2026-09-19 --ledger evals/fixtures/ledger_v1.json \
    -o /tmp/s.md --csv /tmp/s.csv --json /tmp/s.json
# 赢家口径对照（同一夹具、两种口径选出不同赢家）：
python3 scripts/build_schedule.py evals/fixtures/posts_metric_v1.csv \
    --as-of 2026-09-19 --metric total -o /tmp/mt.md
python3 scripts/build_schedule.py evals/fixtures/posts_metric_v1.csv \
    --as-of 2026-09-19 --metric per_day -o /tmp/mpd.md
```

完整评测流程与证据见 [evals/README.md](../evals/README.md)。

## v0.3.0 变更与兼容性

- 默认参数下，旧主夹具的排期结论与 v0.2.0 逐行一致。
- **行为变更**：发布不足 `--recycle-gap-days` 天的赢家不再立即排期，而是进入待定；
  发布日期晚于基准日的行改为跳过。想恢复「刚发就可以翻」的旧行为，可调小 `--recycle-gap-days`
  （不建议）。
- CSV 末尾追加 4 列；JSON 新增若干字段，没有删除或改名。
- 库函数 `load_posts(path)` 不传 `as_of` 时不过滤未来日期，保持兼容。
