"""build_schedule.py 的单元测试：python3 -m unittest discover tests"""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_schedule as bs

AS_OF = date(2026, 9, 19)


def make_post(**kwargs):
    base = {"platform": "xiaohongshu", "post_id": "p1", "title": "标题", "url": "https://example.com/p1",
            "publish_date": date(2026, 1, 1), "views": 1000, "likes": 100, "comments": 10,
            "missing_metrics": []}
    base.update(kwargs)
    return base


class ParseTests(unittest.TestCase):
    def test_parse_date_formats(self):
        for text in ("2026-09-01", "2026/9/1", "2026.09.01", "2026年9月1日"):
            self.assertEqual(bs.parse_date(text, "d"), date(2026, 9, 1))

    def test_parse_date_bad(self):
        with self.assertRaises(bs.SchemaError):
            bs.parse_date("去年夏天", "d")
        with self.assertRaises(bs.SchemaError):
            bs.parse_date("", "d")

    def test_parse_int_tolerant(self):
        self.assertEqual(bs.parse_int("1,200"), 1200)
        self.assertEqual(bs.parse_int(""), None)
        self.assertEqual(bs.parse_int("abc"), None)

    def test_column_aliases_and_missing_required(self):
        mapping = bs.normalize_columns(["平台", "帖子id", "标题", "发布日期", "播放量", "点赞", "评论"])
        self.assertEqual(mapping["platform"], "平台")
        self.assertEqual(mapping["views"], "播放量")
        with self.assertRaises(bs.SchemaError):
            bs.normalize_columns(["title", "views"])


class PercentileTests(unittest.TestCase):
    def test_single_and_median_position(self):
        self.assertEqual(bs.percentile([5.0], 75), 5.0)
        self.assertEqual(bs.percentile([1.0, 2.0, 3.0, 4.0], 75), 3.25)
        self.assertEqual(bs.percentile([], 75), 0.0)


class WinnerTests(unittest.TestCase):
    def _posts(self):
        posts = [make_post(post_id=f"n{i}", views=1000, likes=50, comments=10) for i in range(12)]
        hot = make_post(post_id="hot", views=12000, likes=800, comments=200)
        return posts + [hot]

    def test_winner_detected(self):
        winners = bs.detect_winners(self._posts(), 2, 3, 3.0, 75.0, 10)
        self.assertEqual([item["post"]["post_id"] for item in winners], ["hot"])
        self.assertFalse(winners[0]["degraded_only"])

    def test_sparse_platform_degraded(self):
        posts = [make_post(post_id=f"s{i}", views=500 + i * 30) for i in range(6)]
        posts.append(make_post(post_id="hot", views=9000, likes=600, comments=100))
        winners = bs.detect_winners(posts, 2, 3, 3.0, 75.0, 10)
        self.assertTrue(all(item["degraded_only"] for item in winners))

    def test_uniform_account_no_winner(self):
        posts = [make_post(post_id=f"u{i}", views=1000 + (i % 3) * 10) for i in range(20)]
        self.assertEqual(bs.detect_winners(posts, 2, 3, 3.0, 75.0, 10), [])


class MetricTests(unittest.TestCase):
    """赢家口径对照：累计（total）vs 日均（per_day）。

    18 条基准帖互动量 2000、发布 2026-06-30（存活 81 天，日均 24.69）；
    old_high 累计 7000（3.5x 中位数）但存活 353 天，日均 19.83（低于中位数）；
    new_fast 累计 5000（仅 2.5x 中位数）但只存活 7 天，日均 714.29（28.9x 中位数）。
    两种口径各选出不同赢家。
    """

    def _posts(self):
        posts = [make_post(post_id=f"m{i:02d}", publish_date=date(2026, 6, 30),
                           views=1550, likes=150, comments=50) for i in range(18)]
        posts.append(make_post(post_id="old_high", publish_date=date(2025, 10, 1),
                               views=5200, likes=600, comments=200))
        posts.append(make_post(post_id="new_fast", publish_date=date(2026, 9, 12),
                               views=3200, likes=600, comments=200))
        return posts

    def test_total_picks_old_high_per_day_picks_new_fast(self):
        total = bs.detect_winners(self._posts(), 2, 3, 3.0, 75.0, 10,
                                  as_of=AS_OF, metric="total")
        per_day = bs.detect_winners(self._posts(), 2, 3, 3.0, 75.0, 10,
                                    as_of=AS_OF, metric="per_day")
        self.assertEqual([w["post"]["post_id"] for w in total], ["old_high"])
        self.assertEqual([w["post"]["post_id"] for w in per_day], ["new_fast"])
        # 累计口径与 v0.1.0 一致：multiple 基于原始互动量
        self.assertAlmostEqual(total[0]["multiple"], 3.5)
        self.assertAlmostEqual(per_day[0]["multiple"], 5000 / 7 / (2000 / 81), places=2)

    def test_per_day_same_day_post_uses_floor_of_one_day(self):
        posts = self._posts()
        posts.append(make_post(post_id="today", publish_date=AS_OF,
                               views=8000, likes=0, comments=0))
        winners = bs.detect_winners(posts, 2, 3, 3.0, 75.0, 10,
                                    as_of=AS_OF, metric="per_day")
        ids = [w["post"]["post_id"] for w in winners]
        self.assertIn("today", ids)      # 存活 0 天按 1 天计，日均 8000 最高
        self.assertNotIn("old_high", ids)

    def test_per_day_requires_as_of_and_rejects_unknown_metric(self):
        with self.assertRaises(ValueError):
            bs.detect_winners(self._posts(), 2, 3, 3.0, 75.0, 10, metric="per_day")
        with self.assertRaises(ValueError):
            bs.detect_winners(self._posts(), 2, 3, 3.0, 75.0, 10,
                              as_of=AS_OF, metric="weekly")


def winner_item(post, degraded=False):
    return {"post": post, "platform": post["platform"], "degraded_only": degraded,
            "multiple": 4.0, "rank": 90.0}


class ScheduleTests(unittest.TestCase):
    def test_weekly_cap_and_min_gap(self):
        posts = [make_post(post_id=f"p{i}") for i in range(10)]
        start = date(2026, 9, 20)
        scheduled, backlog = bs.build_schedule([winner_item(p) for p in posts], {},
                                               start, weeks=1, weekly_cap=3,
                                               min_gap_days=1, recycle_gap_days=60)
        self.assertEqual(len(scheduled), 3)  # 一周上限 3 条
        days = [row["planned_date"] for row in scheduled]
        self.assertEqual(days, [date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22)])
        self.assertEqual(len(backlog), 7)

    def test_recycle_gap_from_ledger(self):
        post = make_post(post_id="old")
        scheduled, backlog = bs.build_schedule([winner_item(post)],
                                               {"old": [date(2026, 9, 1)]},
                                               date(2026, 9, 20), weeks=2, weekly_cap=3,
                                               min_gap_days=1, recycle_gap_days=60)
        self.assertEqual(scheduled, [])
        self.assertIn("2026-10-31", backlog[0]["reason"])  # 09-01 + 60 天

    def test_ledger_gap_passed_allows_reschedule(self):
        post = make_post(post_id="old")
        scheduled, _ = bs.build_schedule([winner_item(post)],
                                         {"old": [date(2026, 7, 1)]},
                                         date(2026, 9, 20), weeks=1, weekly_cap=3,
                                         min_gap_days=1, recycle_gap_days=60)
        self.assertEqual(scheduled[0]["planned_date"], date(2026, 9, 20))
        self.assertEqual(scheduled[0]["days_since_previous"], 81)


class LoadTests(unittest.TestCase):
    def _write(self, name, content, suffix):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / f"{name}{suffix}"
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_fields_tolerated_and_bad_rows_skipped(self):
        csv_text = ("platform,post_id,title,url,publish_date,views,likes,comments\n"
                    "xiaohongshu,ok1,帖子,,2026-01-05,1000,,\n"
                    "xiaohongshu,,坏行缺id,,2026-01-06,10,1,1\n"
                    "douyin,baddate,坏行日期,,去年夏天,10,1,1\n"
                    "\n")
        posts, health = bs.load_posts(self._write("p", csv_text, ".csv"))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["views"], 1000)
        self.assertEqual(posts[0]["likes"], 0)
        self.assertEqual(posts[0]["missing_metrics"], ["likes", "comments"])
        self.assertEqual(health["skipped"], {"缺 post_id": 1, "发布日期无法解析": 1})

    def test_ledger_bad_json(self):
        path = self._write("l", "{not json", ".json")
        with self.assertRaises(bs.SchemaError):
            bs.load_ledger(path)


class RunTests(unittest.TestCase):
    @staticmethod
    def _main_csv() -> str:
        header = "platform,post_id,title,url,publish_date,views,likes,comments\n"
        rows = ["xiaohongshu,p1,好帖,https://example.com/1,2026-01-01,9000,600,150\n"]
        rows += [f"xiaohongshu,n{i:02d},普通帖,https://example.com/n{i},"
                 f"2026-{1 + i % 8:02d}-{(i % 27) + 1:02d},100{i % 9},5{i % 9},1{i % 9}\n"
                 for i in range(19)]
        return header + "".join(rows)

    def _write(self, content, suffix=".csv", name="f"):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / f"{name}{suffix}"
        path.write_text(content, encoding="utf-8")
        return path

    def test_end_to_end_exit_codes(self):
        posts = self._write(self._main_csv())
        out_md = posts.parent / "s.md"
        out_csv = posts.parent / "s.csv"
        out_json = posts.parent / "s.json"
        code = bs.run([str(posts), "-o", str(out_md), "--csv", str(out_csv),
                       "--json", str(out_json), "--as-of", "2026-09-19"])
        self.assertEqual(code, 0)
        report = out_md.read_text(encoding="utf-8")
        self.assertIn("p1", out_csv.read_text(encoding="utf-8"))
        self.assertIn("变体重发", report)
        self.assertIn("排期日", report)
        summary = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(summary["scheduled_count"], 1)
        self.assertEqual(summary["scheduled_posts"], ["p1"])
        # 文件不存在 → 2
        self.assertEqual(bs.run([str(posts.parent / "nope.csv")]), 2)
        # 缺必需列 → 3
        bad = self._write("title,views\nx,1\n")
        self.assertEqual(bs.run([str(bad)]), 3)

    def test_cold_start_mode(self):
        csv_text = ("platform,post_id,title,url,publish_date,views,likes,comments\n"
                    "xiaohongshu,c1,帖子,https://example.com/1,2026-01-01,9000,600,150\n"
                    "xiaohongshu,c2,帖子,https://example.com/2,2026-01-02,100,5,1\n")
        posts = self._write(csv_text)
        out_md = posts.parent / "c.md"
        self.assertEqual(bs.run([str(posts), "-o", str(out_md), "--as-of", "2026-09-19"]), 0)
        report = out_md.read_text(encoding="utf-8")
        self.assertIn("先攒数据", report)
        self.assertNotIn("共 ", report.split("先攒数据")[1].split("##")[0])

    def test_metric_option_end_to_end(self):
        # 默认（--metric total）与显式 total 一致，选出累计赢家；per_day 选出日均赢家；
        # 报告与 CSV 标注口径；--json 记录口径参数。
        rows = ["platform,post_id,title,url,publish_date,views,likes,comments"]
        for i in range(18):
            rows.append(f"xiaohongshu,m{i:02d},基准帖,https://example.com/m{i},"
                        f"2026-06-30,1550,150,50")
        rows.append("xiaohongshu,old_high,老帖,https://example.com/oh,2025-10-01,5200,600,200")
        rows.append("xiaohongshu,new_fast,新帖,https://example.com/nf,2026-09-12,3200,600,200")
        posts = self._write("\n".join(rows) + "\n")

        json_default = posts.parent / "m_default.json"
        md_total = posts.parent / "m_total.md"
        json_total = posts.parent / "m_total.json"
        md_day = posts.parent / "m_day.md"
        csv_day = posts.parent / "m_day.csv"
        json_day = posts.parent / "m_day.json"

        self.assertEqual(bs.run([str(posts), "-o", str(md_total), "--json", str(json_default),
                                 "--as-of", "2026-09-19"]), 0)
        self.assertEqual(bs.run([str(posts), "-o", str(md_total), "--json", str(json_total),
                                 "--as-of", "2026-09-19", "--metric", "total"]), 0)
        self.assertEqual(bs.run([str(posts), "-o", str(md_day), "--csv", str(csv_day),
                                 "--json", str(json_day), "--as-of", "2026-09-19",
                                 "--metric", "per_day"]), 0)

        default = json.loads(json_default.read_text(encoding="utf-8"))
        total = json.loads(json_total.read_text(encoding="utf-8"))
        per_day = json.loads(json_day.read_text(encoding="utf-8"))
        self.assertEqual(default["params"]["metric"], "total")  # 默认向后兼容
        self.assertEqual(default["scheduled_posts"], ["old_high"])
        self.assertEqual(total["scheduled_posts"], ["old_high"])
        self.assertEqual(per_day["params"]["metric"], "per_day")
        self.assertEqual(per_day["scheduled_posts"], ["new_fast"])

        self.assertIn("累计互动量", md_total.read_text(encoding="utf-8"))
        report_day = md_day.read_text(encoding="utf-8")
        self.assertIn("日均互动量", report_day)
        self.assertNotIn("old_high", csv_day.read_text(encoding="utf-8"))
        self.assertIn("日均", csv_day.read_text(encoding="utf-8"))

    def test_determinism_same_bytes(self):
        import hashlib
        posts = self._write(self._main_csv())
        digests = []
        for _ in range(2):
            out_md = posts.parent / f"d{_}.md"
            out_csv = posts.parent / f"d{_}.csv"
            self.assertEqual(bs.run([str(posts), "-o", str(out_md), "--csv", str(out_csv),
                                     "--as-of", "2026-09-19"]), 0)
            digests.append((
                hashlib.sha256(out_md.read_bytes()).hexdigest(),
                hashlib.sha256(out_csv.read_bytes()).hexdigest(),
            ))
        self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
