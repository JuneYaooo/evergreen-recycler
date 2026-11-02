#!/usr/bin/env python3
"""对 evals/runs_v2/ 的真实产物逐条复算 cases_v2.jsonl 的原子检查（脚本层）。

用法（仓库根目录）：bash evals/scripts/run_v2.sh && python3 evals/scripts/check_v2.py
输出每个用例的通过/失败项，并写 evals/runs_v2/check_results.json。
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "evals" / "runs_v2"
F = ROOT / "evals" / "fixtures"


def read(name: str) -> str:
    return (R / name).read_text(encoding="utf-8")


def rows(name: str) -> list[dict]:
    with (R / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def js(name: str) -> dict:
    return json.loads(read(name))


def window_ok(sched: list[dict], cap: int = 3) -> bool:
    by: dict[str, list[date]] = {}
    for row in sched:
        by.setdefault(row["platform"], []).append(date.fromisoformat(row["planned_date"]))
    for days in by.values():
        for d in days:
            if sum(1 for x in days if 0 <= (x - d).days < 7) > cap:
                return False
        if len(set(days)) != len(days):
            return False
    return True


def main() -> int:
    checks: dict[str, list[tuple[str, bool]]] = {}

    def add(case: str, label: str, ok: bool) -> None:
        checks.setdefault(case, []).append((label, bool(ok)))

    design = {"xhs_003", "xhs_011", "xhs_019", "xhs_021", "dy_004", "dy_012", "wb_002"}
    main_rows = rows("main_schedule.csv")
    main_md = read("main_schedule.md")
    add("e1-winner-detection", "排期恰好为 7 个设计赢家", {r["post_id"] for r in main_rows} == design and len(main_rows) == 7)
    add("e1-winner-detection", "每行附倍数与分位数", all(r["median_multiple"] and r["percentile_rank"] for r in main_rows))
    add("e1-winner-detection", "数据体检 65/67 与两类跳过原因", "有效帖子 65/67 行（跳过：发布日期无法解析 1 行、缺 post_id 1 行）" in main_md)

    add("e2-schedule-constraints", "任意 7 天 ≤3 条且无同日双排", window_ok(main_rows))
    days = [date.fromisoformat(r["planned_date"]) for r in main_rows]
    add("e2-schedule-constraints", "全部落在 2026-09-20 ~ 2026-10-17", all(date(2026, 9, 20) <= d <= date(2026, 10, 17) for d in days))
    add("e2-schedule-constraints", "排期日距首发 ≥60 天（v0.3.0 新约束）",
        all((date.fromisoformat(r["planned_date"]) - date.fromisoformat(r["publish_date"])).days >= 60 for r in main_rows))

    main_js = js("main_summary.json")
    add("e3-sparse-platform-degraded", "bi_002 仅标记不排期", any(b["post_id"] == "bi_002" and "样本不足 10 条" in b["reason"] for b in main_js["backlog"]))
    add("e3-sparse-platform-degraded", "无 bilibili/wechat 排期行", not any(r["platform"] in ("bilibili", "wechat") for r in main_rows))

    led_rows = rows("ledger_schedule.csv")
    led_js = js("ledger_summary.json")
    add("e4-ledger-recycle-gap", "xhs_003 待定且最早 2026-10-29", any(b["post_id"] == "xhs_003" and "2026-10-29" in b["reason"] for b in led_js["backlog"]))
    add("e4-ledger-recycle-gap", "wb_002 距上次再发 81 天", any(r["post_id"] == "wb_002" and r["days_since_previous"] == "81" for r in led_rows))
    add("e4-ledger-recycle-gap", "6 条且含 xhs_011", len(led_rows) == 6 and any(r["post_id"] == "xhs_011" for r in led_rows))

    add("e5-all-losers-honest-empty", "报告说明没有可排赢家", "本期没有可排的赢家" in read("all_losers_report.md"))
    add("e5-all-losers-honest-empty", "CSV 只有表头", rows("all_losers_schedule.csv") == [])

    cold = read("cold_start_report.md")
    add("e6-cold-start", "先攒数据 + 具体门槛", "先攒数据" in cold and "攒到 20 条以上、每平台至少 10 条" in cold)
    add("e6-cold-start", "含数据体检且无排期", "## 数据体检" in cold and "## 再发排期" not in cold)

    sha = [line.split() for line in read("determinism_sha256.txt").splitlines() if line.strip()]
    by_name = {name: digest for digest, name in sha}
    add("e7-determinism", "两次运行三份输出 sha256 一致",
        all(by_name[f"det_a.{ext}"] == by_name[f"det_b.{ext}"] for ext in ("md", "csv", "json")))

    add("e8-missing-field-tolerance", "数据体检提示 2 行缺字段", "2 行缺少播放/点赞/评论字段" in main_md)
    add("e8-missing-field-tolerance", "xhs_021 纯标题展示", "| 没有链接的旧帖（缺 url） |" in main_md)
    add("e8-missing-field-tolerance", "wb_013 不入选", "wb_013" not in {r["post_id"] for r in main_rows})

    for name in ("main_schedule.md", "ledger_schedule.md"):
        md = read(name)
        table_rows = [line for line in md.splitlines() if line.startswith("| 2026-")]
        add("e9-variant-redline", f"{name} 每行有理由位与变体空栏",
            table_rows and all("（Agent 填写：新钩子 / 新角度 / 换开头案例）" in line and "Agent 结合内容补全" in line for line in table_rows))
        add("e9-variant-redline", f"{name} 红线引用可查证规则且声明不删原帖",
            "绝不建议原样重发" in md and "同质化" in md and "重发也不等于删除原帖" in md and "判定阈值平台未公开" in md)
        add("e9-variant-redline", f"{name} 不再把 180 天内容指纹当事实", "180 天内容指纹" not in md)

    mt = js("metric_total_summary.json")
    mp = js("metric_perday_summary.json")
    add("e10-metric-per-day", "total 唯一排期 old_high", mt["scheduled_posts"] == ["old_high"])
    add("e10-metric-per-day", "per_day 唯一赢家 new_fast 进待定（距首发不足 60 天，最早 2026-11-11）",
        mp["scheduled_posts"] == [] and [b["post_id"] for b in mp["backlog"]] == ["new_fast"]
        and "2026-11-11" in mp["backlog"][0]["reason"])
    add("e10-metric-per-day", "报告标注口径", "累计互动量" in read("metric_total_report.md") and "日均互动量" in read("metric_perday_report.md"))
    add("e10-metric-per-day", "per_day 倍数 28.93x", "28.93x（日均" in read("metric_perday_report.md"))

    lg = js("logic_summary.json")
    lmd = read("logic_schedule.md")
    lrows = rows("logic_schedule.csv")
    add("e11-future-date-skipped", "xg_future 计为坏行跳过", lg["data_health"]["skipped"] == {"发布日期晚于基准日": 1})
    add("e11-future-date-skipped", "xg_future 不在任何输出", "xg_future" not in lmd and "xg_future" not in json.dumps(lg))

    add("e12-young-winner-cooldown", "xg_young_hot 待定，最早 2026-10-31",
        any(b["post_id"] == "xg_young_hot" and "距首发不足 60 天" in b["reason"] and "2026-10-31" in b["reason"] for b in lg["backlog"]))
    add("e12-young-winner-cooldown", "全部排期日距首发 ≥60 天",
        all((date.fromisoformat(r["planned_date"]) - date.fromisoformat(r["publish_date"])).days >= 60 for r in lrows))

    add("e13-saves-shares", "识别收藏/转发列", "识别到附加互动列：收藏、转发/分享" in lmd)
    add("e13-saves-shares", "xg_saves_star 入选", "xg_saves_star" in lg["scheduled_posts"])
    saves = next(r for r in lrows if r["post_id"] == "xg_saves_star")
    add("e13-saves-shares", "engagement 复算 = 2400+160×2+40×3+3000×2+400×3",
        int(saves["engagement"]) == 2400 + 320 + 120 + 6000 + 1200)

    rl = js("logic_rolling_summary.json")
    rmd = read("logic_rolling.md")
    add("e14-rolling-baseline", "默认报告提示基线漂移", "基线漂移：xiaohongshu" in lmd and "--baseline rolling" in lmd)
    add("e14-rolling-baseline", "rolling 找回 xg_early_star，默认不选",
        "xg_early_star" in rl["scheduled_posts"] and "xg_early_star" not in lg["scheduled_posts"])
    add("e14-rolling-baseline", "rolling 倍数标注「滚动」且参数记录",
        "（累计·滚动）" in rmd and rl["params"]["baseline"] == "rolling" and rl["params"]["rolling_window"] == 20)
    # 独立复算 early_star 的滚动倍数
    with (F / "posts_logic_v2.csv").open(encoding="utf-8") as handle:
        fx = [r for r in csv.DictReader(handle) if r["platform"] == "xiaohongshu"
              and r["publish_date"] <= "2026-09-19" and r["views"]]
    def eng(r):
        return int(r["views"]) + 2 * int(r["likes"]) + 3 * int(r["comments"]) + 2 * int(r["收藏"]) + 3 * int(r["转发"])
    star = next(r for r in fx if r["post_id"] == "xg_early_star")
    sd = date.fromisoformat(star["publish_date"])
    others = sorted((r for r in fx if r is not star),
                    key=lambda r: (abs((date.fromisoformat(r["publish_date"]) - sd).days), r["publish_date"], r["post_id"]))[:20]
    expect = round(eng(star) / median(eng(r) for r in others), 2)
    add("e14-rolling-baseline", f"xg_early_star 滚动倍数独立复算 {expect}x", f"{expect}x（累计·滚动）" in rmd)

    ms = read("logic_minsample15.md")
    add("e15-min-sample-param", "待定理由写不足 15 条", "平台样本不足 15 条，仅标记不排期" in ms)
    add("e15-min-sample-param", "数据体检列出 douyin 稀疏", "样本不足（<15 条）平台：douyin" in ms)

    fest = next(line for line in lmd.splitlines() if "xg_festival" in line)
    add("e16-time-sensitive-hint", "双十一帖理由位标疑似时效", "疑似时效" in fest)
    add("e16-time-sensitive-hint", "其余排期行不误标",
        all("疑似时效" not in line for line in lmd.splitlines() if line.startswith("| 2026-") and "xg_festival" not in line))
    add("e16-time-sensitive-hint", "CSV time_sensitive_hint 仅双十一帖非空",
        [r["post_id"] for r in lrows if r["time_sensitive_hint"]] == ["xg_festival"])

    xhs = next(p for p in lg["platforms"] if p["platform"] == "xiaohongshu")
    add("e17-blank-metrics", "数据体检提示 1 行互动全空", "1 行互动数据全空" in lmd)
    add("e17-blank-metrics", "小红书中位数排除全空行（独立复算）", xhs["median_engagement"] == round(median(eng(r) for r in fx), 1))

    results = {case: {"passed": sum(ok for _, ok in items), "total": len(items),
                      "failed": [label for label, ok in items if not ok]}
               for case, items in checks.items()}
    (R / "check_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(v["total"] for v in results.values())
    passed = sum(v["passed"] for v in results.values())
    for case, v in results.items():
        print(f"{case}: {v['passed']}/{v['total']}" + (f"  FAILED {v['failed']}" if v["failed"] else ""))
    print(f"TOTAL {passed}/{total} atomic checks, {sum(1 for v in results.values() if not v['failed'])}/{len(results)} cases")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
