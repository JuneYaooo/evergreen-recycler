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
