#!/usr/bin/env python3
"""从博主历史帖子 CSV 检测赢家内容，生成「变体重发」排期表。

输入：
  posts.csv  历史帖子导出（platform, post_id, title, url, publish_date,
             views, likes, comments；字段缺失容忍，常见中文列名自动映射）
  --ledger   可选，已再发记录 ledger.json（{"<post_id>": ["YYYY-MM-DD", ...]}），
             用于防止同帖短期内重复安排
输出：
  排期表 Markdown（-o）+ schedule.csv（--csv）+ 汇总 JSON（--json）

赢家口径（--metric）：互动量（views + likes×2 + comments×3 + 收藏×2 + 转发×3，
收藏/转发列存在时才计入）≥ 基线中位数 ×3.0 且 ≥ P75；total 按累计互动量（默认），
per_day 按日均互动量（互动量 ÷ max(距基准日存活天数, 1)）。
基线（--baseline）：platform=平台内全部帖子（默认，v0.2.0 行为）；rolling=同平台
发布日期最接近的 N 条帖子（不含自身），对齐「同时期、同账号体量」的比较。
平台样本不足 --min-sample 条时降级为「仅标记不排期」。
排期硬约束：每平台任意 7 天 ≤3 条、同帖距上次发布（含首发）≥60 天、同平台排期日
间隔 ≥1 天；可选 --max-recycles 限制同帖累计再发次数。
红线：输出是「变体重发」建议，绝不建议原样重发（平台明确打击批量同质化/搬运内容）；
重发也不等于删除原帖。

只做本地统计与排期，零网络；同输入同参数输出一致。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

VERSION = "0.3.0"

COLD_START_POSTS = 20          # 有效帖少于该数 → 冷启动建议，不硬排
DEFAULT_WEEKLY_CAP = 3         # 每平台每周上限（对齐 ReQueue 常青组经验值）
DEFAULT_MIN_GAP_DAYS = 1       # 同平台两次排期日最小间隔
DEFAULT_RECYCLE_GAP_DAYS = 60  # 同帖两次再发最小间隔（保守默认，可配）
DEFAULT_MIN_SAMPLE = 10        # 平台样本低于该数 → 降级「仅标记不排期」
DEFAULT_MEDIAN_X = 3.0         # 赢家中位数倍数阈值
DEFAULT_MIN_PERCENTILE = 75.0  # 赢家分位数下限
DEFAULT_LIKE_WEIGHT = 2        # 互动量 = views + likes×2 + comments×3 + saves×2 + shares×3
DEFAULT_COMMENT_WEIGHT = 3
DEFAULT_SAVE_WEIGHT = 2        # 收藏与点赞同权、转发与评论同权：沿用小红书 CES 第三方口径的相对比例
DEFAULT_SHARE_WEIGHT = 3       # （赞1:藏1:评4:转4），收藏/转发列缺失时不影响 v0.2.0 结果
DEFAULT_BASELINE = "platform"  # 基线：platform=平台全量（默认）；rolling=发布日期最近的 N 条
BASELINE_CHOICES = ("platform", "rolling")
DEFAULT_ROLLING_WINDOW = 20    # 滚动基线样本数（基准 20-30 条为高置信，见 references/benchmarks.md）
DEFAULT_MAX_RECYCLES = 0       # 同帖累计再发上限，0=不限（v0.2.0 行为）
DRIFT_RATIO = 2.0              # 最新 1/3 与最早 1/3 帖子中位数相差 ≥2 倍 → 提示基线漂移
METRIC_KEYS = ("views", "likes", "comments", "saves", "shares")
TIME_SENSITIVE_PATTERN = re.compile(
    r"(20[12]\d\s*年|20[12]\d(?=\s)|双十一|双11|双十二|双12|618|年货|春节|元旦|中秋|国庆|圣诞|情人节|七夕|"
    r"开学季|高考|考研|跨年|直播|抽奖|福利|限时|截止|今天|明天|本周|上新|最新)")
DEFAULT_METRIC = "total"       # 赢家口径：total=累计互动量（默认），per_day=日均互动量
METRIC_CHOICES = ("total", "per_day")

RED_LINE = ("输出为「变体重发」建议：绝不建议原样重发——小红书 2026 年 AI 内容治理规则点名"
            "「套用模板批量生产同质化内容」，抖音《恶意营销号治理规范》点名「频繁发布抄袭搬运内容、"
            "批量发布同质化内容」，同账号自我重复的具体判定阈值平台未公开；重发也不等于删除原帖。")

REQUIRED_COLUMNS = ("platform", "post_id", "publish_date")
COLUMN_ALIASES = {
    "platform": ("platform", "平台"),
    "post_id": ("post_id", "postid", "id", "帖子id", "笔记id", "视频id"),
    "title": ("title", "标题", "题目"),
    "url": ("url", "链接", "地址"),
    "publish_date": ("publish_date", "发布日期", "发布时间", "日期", "发布于"),
    "views": ("views", "播放量", "观看量", "阅读量", "播放", "阅读", "浏览量", "曝光"),
    "likes": ("likes", "点赞", "点赞数", "赞", "获赞", "在看"),
    "comments": ("comments", "评论", "评论数", "回复"),
    "saves": ("saves", "collects", "favorites", "收藏", "收藏数", "收藏量"),
    "shares": ("shares", "reposts", "分享", "分享数", "分享量", "转发", "转发数", "转发量"),
}


class SchemaError(ValueError):
    pass


def normalize_columns(fieldnames: list[str]) -> dict[str, str]:
    """把导出 CSV 的列名映射到规范字段名，缺必需列时抛 SchemaError。"""
    lookup = {}
    for name in fieldnames:
        key = (name or "").strip().lower()
        if key:
            lookup[key] = name
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[canonical] = lookup[alias]
                break
    missing = [col for col in REQUIRED_COLUMNS if col not in mapping]
    if missing:
        raise SchemaError("posts.csv 缺少必需列：" + "、".join(missing)
                          + "（支持中文别名，如 平台/标题/发布日期/播放量/点赞/评论）")
    return mapping


def parse_date(value, field: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise SchemaError(f"字段 {field} 为空，无法解析日期")
    normalized = (text.replace("年", "-").replace("月", "-").replace("日", "")
                  .replace("/", "-").replace(".", "-").strip("-"))
    parts = normalized.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        raise ValueError
    except (ValueError, TypeError) as exc:
        raise SchemaError(f"日期字段 {field} 无法解析：{value!r}（支持 YYYY-MM-DD 等）") from exc


def parse_int(value) -> int | None:
    text = str(value or "").strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def load_posts(path: Path, as_of: date | None = None) -> tuple[list[dict], dict]:
    """读取帖子 CSV；字段缺失容忍，坏行跳过并计数。

    发布日期晚于基准日的行视为坏行跳过（v0.3.0 起）：此类行"距首发"为负，
    既无法判断存活时长，也会让同帖再发间隔失效。
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SchemaError("posts.csv 是空表：缺少表头")
        mapping = normalize_columns(reader.fieldnames)
        posts: list[dict] = []
        skip_reasons: dict[str, int] = {}
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue  # 纯空行不算坏行
            post = {canonical: (row.get(actual) or "").strip()
                    for canonical, actual in mapping.items()}
            if not post["post_id"]:
                skip_reasons["缺 post_id"] = skip_reasons.get("缺 post_id", 0) + 1
                continue
            if not post["platform"]:
                skip_reasons["缺 platform"] = skip_reasons.get("缺 platform", 0) + 1
                continue
            try:
                post["publish_date"] = parse_date(post.get("publish_date"), "publish_date")
            except SchemaError:
                skip_reasons["发布日期无法解析"] = skip_reasons.get("发布日期无法解析", 0) + 1
                continue
            if as_of is not None and post["publish_date"] > as_of:
                skip_reasons["发布日期晚于基准日"] = skip_reasons.get("发布日期晚于基准日", 0) + 1
                continue
            missing_metrics = []
            present_columns = 0
            for key in METRIC_KEYS:
                if key not in mapping:
                    post[key] = 0
                    continue
                present_columns += 1
                number = parse_int(post.get(key))
                if number is None:
                    missing_metrics.append(key)
                    number = 0
                post[key] = number
            post["missing_metrics"] = [key for key in missing_metrics
                                       if key in ("views", "likes", "comments")]
            # 全部互动列都为空：不是"0 互动"，而是没有数据；不进基线、不参与赢家竞争
            post["no_metrics"] = present_columns > 0 and len(missing_metrics) == present_columns
            posts.append(post)
    health = {
        "total_rows": len(posts) + sum(skip_reasons.values()),
        "valid_rows": len(posts),
        "skipped": skip_reasons,
        "missing_metric_rows": sum(1 for post in posts if post["missing_metrics"]),
        "no_metric_rows": sum(1 for post in posts if post.get("no_metrics")),
        "extra_metric_columns": [key for key in ("saves", "shares") if key in mapping],
    }
    return posts, health


def load_ledger(path: Path) -> dict[str, list[date]]:
    """ledger.json：{"<post_id>": ["YYYY-MM-DD", ...]} 同帖历史再发日期。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"ledger.json 不是合法 JSON：{exc.msg}（第 {exc.lineno} 行）") from exc
    if not isinstance(data, dict):
        raise SchemaError("ledger.json 需要是对象：{\"<post_id>\": [\"YYYY-MM-DD\", ...]}")
    ledger: dict[str, list[date]] = {}
    for post_id, dates in data.items():
        if not isinstance(dates, list):
            raise SchemaError(f"ledger.json 中 {post_id} 的值需为日期数组")
        parsed = []
        for item in dates:
            try:
                parsed.append(date.fromisoformat(str(item).strip()))
            except ValueError as exc:
                raise SchemaError(f"ledger.json 中 {post_id} 含无法解析的日期：{item!r}") from exc
        ledger[str(post_id)] = parsed
    return ledger


def engagement(post: dict, like_weight: int, comment_weight: int,
               save_weight: int = DEFAULT_SAVE_WEIGHT,
               share_weight: int = DEFAULT_SHARE_WEIGHT) -> float:
    return (post["views"] + like_weight * post["likes"] + comment_weight * post["comments"]
            + save_weight * post.get("saves", 0) + share_weight * post.get("shares", 0))


def time_sensitive_hint(title: str) -> str:
    """标题含日期/节日/活动类词 → 返回命中词（疑似时效内容，需人工确认仍成立）。"""
    match = TIME_SENSITIVE_PATTERN.search(title or "")
    return match.group(0).strip() if match else ""


def baseline_drift(group: list[dict]) -> float | None:
    """按发布日期排序后，最新 1/3 与最早 1/3 的互动量中位数之比；样本 <9 返回 None。"""
    valid = sorted((p for p in group if not p.get("no_metrics")),
                   key=lambda p: (p["publish_date"], p["post_id"]))
    if len(valid) < 9:
        return None
    third = len(valid) // 3
    old = median(p["engagement"] for p in valid[:third])
    new = median(p["engagement"] for p in valid[-third:])
    if old <= 0 or new <= 0:
        return None
    return round(new / old, 2)


def metric_value(post: dict, as_of: date | None, metric: str,
                 like_weight: int, comment_weight: int,
                 save_weight: int = DEFAULT_SAVE_WEIGHT,
                 share_weight: int = DEFAULT_SHARE_WEIGHT) -> float:
    """赢家口径的比较值：total=累计互动量；per_day=日均互动量。

    per_day = 互动量 ÷ max(距基准日存活天数, 1)；发布当天或日期晚于基准日按
    1 天计，避免除零，也避免极新帖被无限放大。
    """
    value = engagement(post, like_weight, comment_weight, save_weight, share_weight)
    if metric == "per_day":
        age_days = (as_of - post["publish_date"]).days
        return value / max(age_days, 1)
    return value


def percentile(sorted_values: list[float], pct: float) -> float:
    """线性插值分位数；空列表返回 0。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def detect_winners(posts: list[dict], like_weight: int, comment_weight: int,
                   median_x: float, min_percentile: float, min_sample: int,
                   as_of: date | None = None, metric: str = DEFAULT_METRIC,
                   baseline: str = DEFAULT_BASELINE,
                   rolling_window: int = DEFAULT_ROLLING_WINDOW,
                   save_weight: int = DEFAULT_SAVE_WEIGHT,
                   share_weight: int = DEFAULT_SHARE_WEIGHT) -> list[dict]:
    """平台内赢家检测：所选口径值 ≥ 中位数×median_x 且 ≥ P75；样本不足降级标注。

    metric="total"（默认）按累计互动量比较，与 v0.1.0 行为一致；metric="per_day"
    按日均互动量比较，修正老帖的累计优势，此时必须提供 as_of 基准日。
    报告与 CSV 中所有倍数均按所选口径标注（累计/日均）。
    """
    if metric not in METRIC_CHOICES:
        raise ValueError(f"未知口径：{metric!r}（支持 {'/'.join(METRIC_CHOICES)}）")
    if metric == "per_day" and as_of is None:
        raise ValueError("口径 per_day 需要提供 as_of 基准日")
    if baseline not in BASELINE_CHOICES:
        raise ValueError(f"未知基线：{baseline!r}（支持 {'/'.join(BASELINE_CHOICES)}）")
    if rolling_window < 3:
        raise ValueError("滚动基线样本数 rolling_window 至少为 3")
    by_platform: dict[str, list[dict]] = {}
    for post in posts:
        post["engagement"] = engagement(post, like_weight, comment_weight,
                                        save_weight, share_weight)
        post["metric_value"] = metric_value(post, as_of, metric, like_weight,
                                            comment_weight, save_weight, share_weight)
        by_platform.setdefault(post["platform"], []).append(post)

    winners: list[dict] = []
    for platform in sorted(by_platform):
        group = by_platform[platform]
        valid = [post for post in group if not post.get("no_metrics")]
        platform_values = sorted(post["metric_value"] for post in valid)
        degraded = len(group) < min_sample
        if not platform_values:
            continue
        for post in valid:
            if baseline == "rolling":
                values = rolling_values(valid, post, rolling_window)
                if not values:
                    continue
            else:
                values = platform_values
            med = median(values)
            p75 = percentile(values, 75.0)
            if med <= 0 or post["metric_value"] <= 0:
                continue
            multiple = post["metric_value"] / med
            if baseline == "rolling":
                # 滚动基线不含自身：分位数按"自身在 窗口+自身 中的位置"计算
                rank = (100.0 * (sum(1 for value in values if value <= post["metric_value"]) + 1)
                        / (len(values) + 1))
            else:
                rank = 100.0 * sum(1 for value in values if value <= post["metric_value"]) / len(values)
            post["median_multiple"] = round(multiple, 2)
            post["percentile_rank"] = round(rank, 1)
            post["platform_median"] = round(med, 1)
            post["platform_p75"] = round(p75, 1)
            if multiple >= median_x and rank >= min_percentile:
                winners.append({
                    "post": post,
                    "platform": platform,
                    "degraded_only": degraded,
                    "metric": metric,
                    "metric_value": post["metric_value"],
                    "multiple": multiple,
                    "rank": rank,
                    "baseline": baseline,
                })
    winners.sort(key=lambda item: (-item["multiple"], -item["post"]["metric_value"],
                                   item["platform"], item["post"]["post_id"]))
    return winners


def rolling_values(valid: list[dict], post: dict, window: int) -> list[float]:
    """同平台发布日期最接近的 window 条帖子（不含自身）的口径值，升序。

    对齐 vidIQ「同时期频道均值」与 age-matched outlier 口径：同期帖子存活时长相近、
    账号体量相近，可同时缓解累计口径的老帖优势与账号涨粉带来的基线漂移。
    同距离时按发布日期、post_id 排序保证确定性。
    """
    others = [other for other in valid if other is not post]
    others.sort(key=lambda other: (abs((other["publish_date"] - post["publish_date"]).days),
                                   other["publish_date"], other["post_id"]))
    return sorted(other["metric_value"] for other in others[:window])


def build_schedule(winners: list[dict], ledger: dict[str, list[date]],
                   start: date, weeks: int, weekly_cap: int, min_gap_days: int,
                   recycle_gap_days: int, min_sample: int = DEFAULT_MIN_SAMPLE,
                   max_recycles: int = DEFAULT_MAX_RECYCLES
                   ) -> tuple[list[dict], list[dict]]:
    """贪心排期：基线倍数降序入槽，违反任一约束就顺延或进后备列表。

    每周上限按「滚动 7 天窗口」计算：任意连续 7 天内同平台不超过 weekly_cap 条，
    避免跨日历周边界时出现 4 天连发 4 条；排期日间隔对同平台所有已排日期生效，
    因此较低倍数的赢家也可以回填到已有排期之间的空档。

    v0.3.0 起，同帖再发间隔从「上次发布」算起，首发日期也算一次发布：发布不足
    recycle_gap_days 天的帖子不会被立即「翻红」（对齐 Revive Old Posts 的最小帖龄、
    各家常青队列的冷却期）。max_recycles>0 时，ledger 中已再发次数达到上限的帖子
    进入待定（对齐 CoSchedule 发送上限 / SmarterQueue 过期条件）。
    """
    horizon_end = start + timedelta(days=weeks * 7 - 1)
    scheduled_days: dict[str, list[date]] = {}
    scheduled: list[dict] = []
    backlog: list[dict] = []

    def within_cap(platform: str, day: date) -> bool:
        recent = sum(1 for d in scheduled_days.get(platform, [])
                     if 0 <= (day - d).days < 7)
        return recent < weekly_cap

    def respects_gap(platform: str, day: date) -> bool:
        return all(abs((day - d).days) >= min_gap_days
                   for d in scheduled_days.get(platform, []))

    for item in winners:
        if item["degraded_only"]:
            backlog.append({"item": item, "reason": f"平台样本不足 {min_sample} 条，仅标记不排期"})
            continue
        post = item["post"]
        platform = item["platform"]
        history = list(ledger.get(post["post_id"], []))
        if max_recycles > 0 and len(history) >= max_recycles:
            backlog.append({"item": item,
                            "reason": f"已再发 {len(history)} 次，达到 --max-recycles {max_recycles} 上限，"
                                      "建议改写成新选题而不是继续翻红"})
            continue
        previous = max(history) if history else None
        anchor = max([post["publish_date"]] + history)
        earliest = max(start, anchor + timedelta(days=recycle_gap_days))
        day = earliest
        placed = None
        while day <= horizon_end:
            if not within_cap(platform, day) or not respects_gap(platform, day):
                day += timedelta(days=1)
                continue
            placed = day
            break
        if placed is None:
            ready = anchor + timedelta(days=recycle_gap_days)
            if ready > horizon_end:
                if previous is not None and anchor == previous:
                    reason = (f"同帖再发间隔 ≥{recycle_gap_days} 天，"
                              f"最早可排 {ready.isoformat()}，超出本规划期")
                else:
                    reason = (f"距首发不足 {recycle_gap_days} 天（{post['publish_date'].isoformat()} 发布，"
                              f"可能仍在自然流量期），最早可排 {ready.isoformat()}，超出本规划期")
                backlog.append({"item": item, "reason": reason})
            else:
                backlog.append({"item": item, "reason": f"{weeks} 周内该平台配额已满（任意 7 天 ≤{weekly_cap} 条）"})
            continue
        scheduled_days.setdefault(platform, []).append(placed)
        scheduled.append({
            "planned_date": placed,
            "item": item,
            "days_since_previous": (placed - previous).days if previous is not None else None,
            "days_since_first_publish": (placed - post["publish_date"]).days,
        })
    scheduled.sort(key=lambda row: (row["planned_date"], row["item"]["platform"],
                                    row["item"]["post"]["post_id"]))
    return scheduled, backlog


def fmt_number(value) -> str:
    return f"{int(value):,}"


def build_markdown(posts: list[dict], health: dict, winners: list[dict],
                   scheduled: list[dict], backlog: list[dict], args,
                   start: date, horizon_end: date, mode: str) -> str:
    by_platform: dict[str, list[dict]] = {}
    for post in posts:
        by_platform.setdefault(post["platform"], []).append(post)
    metric_short = "累计" if args.metric == "total" else "日均"
    metric_note = ("累计互动量" if args.metric == "total"
                   else "日均互动量（互动量 ÷ max(存活天数, 1)）")
    baseline_note = ("平台内全部帖子" if args.baseline == "platform"
                     else f"同平台发布日期最近的 {args.rolling_window} 条帖子（滚动基线，不含自身）")
    baseline_short = "平台" if args.baseline == "platform" else "滚动"
    lines = [
        "# 老帖翻红再发排期表",
        "",
        f"基准日 {args.as_of.isoformat()} ｜ 规划期 {start.isoformat()} ~ {horizon_end.isoformat()}"
        f"（{args.weeks} 周）｜ 赢家阈值：基线中位数 ≥{args.median_x:g}x 且 ≥P{args.min_percentile:g}"
        f" ｜ 赢家口径：{metric_note}（--metric {args.metric}）"
        f"｜ 基线：{baseline_note}（--baseline {args.baseline}）｜ 版本 {VERSION}",
        "",
    ]

    if mode == "cold_start":
        lines += [
            "## 先攒数据：暂不排期",
            "",
            f"当前有效帖子仅 {health['valid_rows']} 条（少于 {COLD_START_POSTS} 条）。样本太少时"
            "「中位数倍数」和分位数都不稳定，现在硬排期很容易把普通帖当赢家翻红，反而浪费发布位。建议：",
            "",
            f"- 先正常更新攒到 {COLD_START_POSTS} 条以上、每平台至少 {args.min_sample} 条，再回来跑排期；",
            "- 期间可以手动把表现突出的帖子记进台账（post_id + 数据），作为将来的种子；",
            "- 若某平台只是刚起步，可先只对样本充足的平台出排期。",
            "",
            "## 数据体检",
            "",
        ]
        lines += health_lines(health, by_platform)
        lines += ["", f"- {RED_LINE}", f"- 版本 {VERSION}。全部计算在本地完成，帖子数据不会上传。",
                  ""]
        return "\n".join(lines)

    lines += ["## 数据体检", ""]
    lines += health_lines(health, by_platform)
    sparse = sorted(name for name, group in by_platform.items() if len(group) < args.min_sample)
    if sparse:
        lines.append(f"- 样本不足（<{args.min_sample} 条）平台：{'、'.join(sparse)}"
                     f" → 这些平台的赢家仅标记、不排期")
    for name, group in sorted(by_platform.items()):
        drift = baseline_drift(group)
        if drift is not None and (drift >= DRIFT_RATIO or drift <= 1 / DRIFT_RATIO):
            hint = ("当前已用滚动基线" if args.baseline == "rolling"
                    else "全量中位数会混合不同时期的账号体量，建议加跑 --baseline rolling 对照")
            lines.append(f"- 基线漂移：{name} 最新 1/3 帖子的互动中位数是最早 1/3 的 {drift:g} 倍"
                         f"（账号涨粉/掉粉或累计口径的帖龄差）→ {hint}")
    lines.append("")

    lines += [
        "## 再发排期（变体重发，绝不原样重发）",
        "",
        f"共 {len(scheduled)} 条进入排期；赢家倍数按{metric_note}计算（口径 {args.metric}）。"
        f"同帖距上次发布（含首发）≥{args.recycle_gap_days} 天，"
        f"每平台任意 7 天内 ≤{args.weekly_cap} 条，同平台排期日间隔 ≥{args.min_gap_days} 天。"
        "「理由位」先给出脚本算出的依据，最终理由与「文案变体方向」由 Agent 结合帖子内容填写。",
        "",
    ]

    scheduled_by_platform: dict[str, list[dict]] = {}
    for row in scheduled:
        scheduled_by_platform.setdefault(row["item"]["platform"], []).append(row)
    for platform in sorted(scheduled_by_platform):
        lines.append(f"### {platform}（本期限 {len(scheduled_by_platform[platform])} 条，"
                     f"任意 7 天 ≤{args.weekly_cap} 条）")
        lines.append("")
        lines.append("| 排期日 | 帖子 | 原帖数据 | 基线倍数 | 距首发（基准日） | 再发窗口 | 理由位 | 文案变体方向（待填写） |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for row in scheduled_by_platform[platform]:
            post = row["item"]["post"]
            title = (post.get("title") or post["post_id"]).replace("|", "／")
            link = post.get("url") or ""
            name = f"[{title}]({link})" if link else title
            metrics = (f"播放/阅读 {fmt_number(post['views'])} ｜ 赞 {fmt_number(post['likes'])}"
                       f" ｜ 评 {fmt_number(post['comments'])}")
            if "saves" in health.get("extra_metric_columns", []):
                metrics += f" ｜ 藏 {fmt_number(post['saves'])}"
            if "shares" in health.get("extra_metric_columns", []):
                metrics += f" ｜ 转 {fmt_number(post['shares'])}"
            window = (f"首次再发（排期日距首发 {row['days_since_first_publish']} 天）"
                      if row["days_since_previous"] is None
                      else f"距上次再发 {row['days_since_previous']} 天（≥{args.recycle_gap_days} 天）")
            hint = time_sensitive_hint(post.get("title") or "")
            caution = f"；⚠ 标题含「{hint}」疑似时效内容，确认仍成立再排" if hint else ""
            lines.append(
                f"| {row['planned_date'].isoformat()}（{'周' + '一二三四五六日'[row['planned_date'].weekday()]}）"
                f" | {name} | {metrics}（{post['publish_date'].isoformat()} 发布）"
                f" | {post.get('median_multiple', '-')}x（{metric_short}·{baseline_short}）· P{post.get('percentile_rank', '-')}"
                f" | {(args.as_of - post['publish_date']).days} 天 | {window}"
                f" | {post.get('median_multiple', '-')}x {metric_short}基线·P{post.get('percentile_rank', '-')}"
                f"{caution}（Agent 结合内容补全） | （Agent 填写：新钩子 / 新角度 / 换开头案例） |"
            )
        lines.append("")

    if backlog:
        lines += ["## 已标记、本期待定", ""]
        for entry in backlog:
            post = entry["item"]["post"]
            title = (post.get("title") or post["post_id"]).replace("|", "／")
            lines.append(f"- {post['platform']}｜{title}｜{post.get('median_multiple', '-')}x"
                         f"（{metric_short}·{baseline_short}）—— {entry['reason']}")
        lines.append("")

    if not scheduled:
        lines += [
            "## 本期没有可排的赢家",
            "",
            f"这批数据里没有帖子同时满足「基线中位数 ≥{args.median_x:g}x 且 ≥P{args.min_percentile:g}」"
            "并通过排期约束"
            "——说明账号表现比较平均，没有明显跑赢基线的内容。这是正常且诚实的结论，不必硬凑排期：",
            "- 可以观察近期哪类选题互动更好，等出现明显的爆款再翻红；",
            f"- 或把阈值调低（如 --median-x 2）先看「候选清单」，但翻红优先级自担。",
            "",
        ]

    lines += [
        "## 边界说明",
        "",
        f"- {RED_LINE}",
        f"- 赢家口径：{metric_note}（--metric {args.metric}）。累计口径下老帖有累积优势，"
        "日均口径用存活天数归一近似修正，但发布不到 1 天的极新帖按 1 天计，单日爆发会被放大，取舍自负。",
        f"- 基线：{baseline_note}（--baseline {args.baseline}）。账号体量变化大时全量中位数会失真，"
        "滚动基线按同时期帖子比较；两种基线都只和账号自己比。",
        "- 平台对同账号重复内容的判定细则未公开且随时可能调整；本工具的间隔与配额"
        f"（--recycle-gap-days、--weekly-cap）都是参数，60 天默认值取行业常见 60-90 天区间的下沿，"
        "规则变化时自行收紧。标题含年份/节日/活动等词的帖子会标「疑似时效」，只提示不剔除。",
        "- 排期依据是账号自身历史数据内的相对比较（基线中位数倍数 + 分位数），不代表绝对流量承诺；"
        "发布后请回填 status 并在下一期导出新数据对比效果。",
        "- 全部计算在本地完成，零网络访问；帖子台账含账号信息，请勿公开原件。",
        f"- 版本 {VERSION}。",
        "",
    ]
    return "\n".join(lines)


def health_lines(health: dict, by_platform: dict[str, list[dict]]) -> list[str]:
    skipped = health["skipped"]
    skip_text = "、".join(f"{reason} {count} 行" for reason, count in sorted(skipped.items())) or "无"
    distribution = " ｜ ".join(f"{name} {len(group)} 条" for name, group in sorted(by_platform.items()))
    return [
        f"- 有效帖子 {health['valid_rows']}/{health['total_rows']} 行"
        f"（跳过：{skip_text}）",
        f"- 平台分布：{distribution or '无'}",
        f"- {health['missing_metric_rows']} 行缺少播放/点赞/评论字段，按 0 计入统计（字段缺失容忍，但会影响该行竞争力）",
    ] + ([f"- {health['no_metric_rows']} 行互动数据全空：保留计数，但不计入基线中位数、不参与赢家竞争"
          "（全空≠0 互动，按 0 计会压低基线）"] if health.get("no_metric_rows") else []) + (
        [f"- 识别到附加互动列：{'、'.join({'saves': '收藏', 'shares': '转发/分享'}[k] for k in health['extra_metric_columns'])}"
         "，按 收藏×2、转发×3 计入互动量"] if health.get("extra_metric_columns") else [])


def schedule_csv_rows(scheduled: list[dict], args) -> list[dict]:
    metric_short = "累计" if args.metric == "total" else "日均"
    rows = []
    for entry in scheduled:
        post = entry["item"]["post"]
        metric_value = post.get("metric_value", 0.0)
        metric_value_out = (int(metric_value) if float(metric_value).is_integer()
                            else round(metric_value, 2))
        rows.append({
            "planned_date": entry["planned_date"].isoformat(),
            "platform": entry["item"]["platform"],
            "post_id": post["post_id"],
            "title": post.get("title") or "",
            "url": post.get("url") or "",
            "publish_date": post["publish_date"].isoformat(),
            "views": post["views"],
            "likes": post["likes"],
            "comments": post["comments"],
            "engagement": int(post["engagement"]),
            "metric": args.metric,
            "metric_value": metric_value_out,
            "median_multiple": post.get("median_multiple", ""),
            "percentile_rank": post.get("percentile_rank", ""),
            "days_since_publish": (args.as_of - post["publish_date"]).days,
            "days_since_previous": entry["days_since_previous"]
            if entry["days_since_previous"] is not None else "",
            "reason_hint": f"{post.get('median_multiple', '-')}x {metric_short}基线 · P{post.get('percentile_rank', '-')}",
            "variant_direction": "",
            "status": "pending",
            "baseline": args.baseline,
            "saves": post.get("saves", 0),
            "shares": post.get("shares", 0),
            "time_sensitive_hint": time_sensitive_hint(post.get("title") or ""),
        })
    return rows


CSV_FIELDS = ["planned_date", "platform", "post_id", "title", "url", "publish_date",
              "views", "likes", "comments", "engagement", "metric", "metric_value",
              "median_multiple", "percentile_rank", "days_since_publish",
              "days_since_previous", "reason_hint", "variant_direction", "status",
              # v0.3.0 追加在末尾，按列名读取的旧表格不受影响
              "baseline", "saves", "shares", "time_sensitive_hint"]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("posts", type=Path, help="历史帖子 posts.csv")
    parser.add_argument("-o", "--output", type=Path, help="排期表 Markdown 输出路径（缺省打印到 stdout）")
    parser.add_argument("--csv", type=Path, help="schedule.csv 输出路径")
    parser.add_argument("--json", type=Path, help="结构化汇总 JSON 输出路径")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                        help="基准日（ISO 格式），默认今天；评测与复现时固定该值")
    parser.add_argument("--start-date", type=date.fromisoformat, default=None,
                        help="排期起始日（默认基准日次日）")
    parser.add_argument("--weeks", type=int, default=4, help="规划周数（默认 4）")
    parser.add_argument("--weekly-cap", type=int, default=DEFAULT_WEEKLY_CAP,
                        help=f"每平台每周排期上限（默认 {DEFAULT_WEEKLY_CAP}）")
    parser.add_argument("--min-gap-days", type=int, default=DEFAULT_MIN_GAP_DAYS,
                        help=f"同平台两次排期日最小间隔（默认 {DEFAULT_MIN_GAP_DAYS} 天）")
    parser.add_argument("--recycle-gap-days", type=int, default=DEFAULT_RECYCLE_GAP_DAYS,
                        help=f"同帖两次再发最小间隔（默认 {DEFAULT_RECYCLE_GAP_DAYS} 天）")
    parser.add_argument("--min-sample", type=int, default=DEFAULT_MIN_SAMPLE,
                        help=f"平台样本低于该数时降级为仅标记（默认 {DEFAULT_MIN_SAMPLE}）")
    parser.add_argument("--median-x", type=float, default=DEFAULT_MEDIAN_X,
                        help=f"赢家中位数倍数阈值（默认 {DEFAULT_MEDIAN_X:g}）")
    parser.add_argument("--min-percentile", type=float, default=DEFAULT_MIN_PERCENTILE,
                        help=f"赢家分位数下限（默认 P{DEFAULT_MIN_PERCENTILE:g}）")
    parser.add_argument("--like-weight", type=int, default=DEFAULT_LIKE_WEIGHT,
                        help=f"互动量中点赞权重（默认 {DEFAULT_LIKE_WEIGHT}）")
    parser.add_argument("--comment-weight", type=int, default=DEFAULT_COMMENT_WEIGHT,
                        help=f"互动量中评论权重（默认 {DEFAULT_COMMENT_WEIGHT}）")
    parser.add_argument("--metric", choices=METRIC_CHOICES, default=DEFAULT_METRIC,
                        help="赢家口径：total=累计互动量（默认）；per_day=日均互动量"
                             "（互动量 ÷ max(存活天数, 1)，修正老帖累计优势）")
    parser.add_argument("--baseline", choices=BASELINE_CHOICES, default=DEFAULT_BASELINE,
                        help="赢家基线：platform=平台内全部帖子（默认）；rolling=同平台发布日期最近的 N 条"
                             "（不含自身，适合账号体量变化大的历史）")
    parser.add_argument("--rolling-window", type=int, default=DEFAULT_ROLLING_WINDOW,
                        help=f"滚动基线样本数（默认 {DEFAULT_ROLLING_WINDOW}，至少 3）")
    parser.add_argument("--save-weight", type=int, default=DEFAULT_SAVE_WEIGHT,
                        help=f"互动量中收藏权重（默认 {DEFAULT_SAVE_WEIGHT}，仅当 CSV 有收藏列）")
    parser.add_argument("--share-weight", type=int, default=DEFAULT_SHARE_WEIGHT,
                        help=f"互动量中转发/分享权重（默认 {DEFAULT_SHARE_WEIGHT}，仅当 CSV 有转发列）")
    parser.add_argument("--max-recycles", type=int, default=DEFAULT_MAX_RECYCLES,
                        help="同帖累计再发次数上限（按 ledger 计），0=不限（默认）")
    parser.add_argument("--ledger", type=Path, help="已再发记录 ledger.json，防止同帖短期内重复排期")
    args = parser.parse_args(argv)
    if args.rolling_window < 3:
        parser.error("--rolling-window 至少为 3")

    for path in ([args.posts] if args.posts else []) + ([args.ledger] if args.ledger else []):
        if not path.is_file():
            print(f"输入文件不存在：{path}", file=sys.stderr)
            return 2
    try:
        posts, health = load_posts(args.posts, as_of=args.as_of)
        ledger = load_ledger(args.ledger) if args.ledger else {}
    except SchemaError as exc:
        print(f"输入格式错误：{exc}", file=sys.stderr)
        return 3

    start = args.start_date or args.as_of + timedelta(days=1)
    horizon_end = start + timedelta(days=args.weeks * 7 - 1)
    mode = "cold_start" if health["valid_rows"] < COLD_START_POSTS else "schedule"

    winners: list[dict] = []
    scheduled: list[dict] = []
    backlog: list[dict] = []
    if mode == "schedule":
        winners = detect_winners(posts, args.like_weight, args.comment_weight,
                                 args.median_x, args.min_percentile, args.min_sample,
                                 as_of=args.as_of, metric=args.metric,
                                 baseline=args.baseline, rolling_window=args.rolling_window,
                                 save_weight=args.save_weight, share_weight=args.share_weight)
        scheduled, backlog = build_schedule(winners, ledger, start, args.weeks,
                                            args.weekly_cap, args.min_gap_days,
                                            args.recycle_gap_days,
                                            min_sample=args.min_sample,
                                            max_recycles=args.max_recycles)

    report = build_markdown(posts, health, winners, scheduled, backlog, args,
                            start, horizon_end, mode)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(schedule_csv_rows(scheduled, args))

    if args.json:
        by_platform: dict[str, list[dict]] = {}
        for post in posts:
            by_platform.setdefault(post["platform"], []).append(post)
        payload = {
            "version": VERSION,
            "mode": mode,
            "as_of": args.as_of.isoformat(),
            "params": {
                "weeks": args.weeks, "weekly_cap": args.weekly_cap,
                "min_gap_days": args.min_gap_days,
                "recycle_gap_days": args.recycle_gap_days,
                "min_sample": args.min_sample, "median_x": args.median_x,
                "min_percentile": args.min_percentile,
                "like_weight": args.like_weight,
                "comment_weight": args.comment_weight,
                "metric": args.metric,
                "baseline": args.baseline,
                "rolling_window": args.rolling_window,
                "save_weight": args.save_weight,
                "share_weight": args.share_weight,
                "max_recycles": args.max_recycles,
                "start_date": start.isoformat(),
            },
            "data_health": health,
            "platforms": [
                {
                    "platform": name,
                    "posts": len(group),
                    "degraded": len(group) < args.min_sample,
                    "median_engagement": round(median(sorted(post["engagement"] for post in group
                                                             if not post.get("no_metrics"))), 1)
                    if mode == "schedule" and any(not p.get("no_metrics") for p in group) else None,
                    "median_metric_value": round(median(sorted(post["metric_value"] for post in group
                                                               if not post.get("no_metrics"))), 1)
                    if mode == "schedule" and any(not p.get("no_metrics") for p in group) else None,
                    "baseline_drift_ratio": baseline_drift(group) if mode == "schedule" else None,
                    "winner_count": sum(1 for item in winners if item["platform"] == name),
                    "scheduled_count": sum(1 for row in scheduled if row["item"]["platform"] == name),
                }
                for name, group in sorted(by_platform.items())
            ],
            "scheduled_count": len(scheduled),
            "backlog_count": len(backlog),
            "scheduled_posts": [row["item"]["post"]["post_id"] for row in scheduled],
            "backlog": [
                {"post_id": entry["item"]["post"]["post_id"],
                 "platform": entry["item"]["platform"],
                 "reason": entry["reason"]}
                for entry in backlog
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
