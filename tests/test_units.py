# -*- coding: utf-8 -*-
"""无需浏览器的纯逻辑单元测试。运行：python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import core  # noqa: E402


class TestParseThemeUrl(unittest.TestCase):
    def test_full_url(self):
        url, tid = core.parse_theme_url("https://k.cnki.net/themeInfo/2046")
        self.assertEqual(url, "https://k.cnki.net/themeInfo/2046")
        self.assertEqual(tid, "2046")

    def test_bare_id(self):
        url, tid = core.parse_theme_url("2046")
        self.assertEqual(url, "https://k.cnki.net/themeInfo/2046")
        self.assertEqual(tid, "2046")

    def test_random_text_with_id(self):
        url, tid = core.parse_theme_url("随便 12345 文本")
        self.assertEqual(tid, "12345")
        self.assertTrue(url.startswith("https://k.cnki.net/themeInfo/"))

    def test_empty_falls_back(self):
        url, tid = core.parse_theme_url("")
        self.assertEqual(tid, "2046")


class TestParseCredsText(unittest.TestCase):
    def test_parse_both(self):
        u, p = core.parse_creds_text("账号：13800138000\n密码：abc123\n")
        self.assertEqual(u, "13800138000")
        self.assertEqual(p, "abc123")

    def test_fullwidth_colon(self):
        u, p = core.parse_creds_text("账号：hello\n密码：world")
        self.assertEqual((u, p), ("hello", "world"))

    def test_empty(self):
        u, p = core.parse_creds_text("")
        self.assertEqual((u, p), ("", ""))

    def test_missing_password(self):
        u, p = core.parse_creds_text("账号：foo")
        self.assertEqual(p, "")


class TestFmtHms(unittest.TestCase):
    def test_hours(self):
        self.assertEqual(core.fmt_hms(16 * 3600 + 50 * 60 + 6), "16:50:06")

    def test_minutes_only(self):
        self.assertEqual(core.fmt_hms(125), "2:05")

    def test_zero(self):
        self.assertEqual(core.fmt_hms(0), "0:00")

    def test_negative_clamped(self):
        self.assertEqual(core.fmt_hms(-5), "0:00")


class TestParseProgressItems(unittest.TestCase):
    def test_basic(self):
        items = [
            {"courseName": "A", "progress": 73.0, "learnState": 1, "duration": 6300, "learnDuration": 4600, "finishDate": None},
            {"courseName": "B", "progress": 100.0, "learnState": 2, "duration": 8100, "learnDuration": 8100, "finishDate": "2026-09-06"},
        ]
        out = core.parse_progress_items(items)
        self.assertEqual(set(out.keys()), {"A", "B"})
        self.assertEqual(out["A"]["progress"], 73.0)
        self.assertEqual(out["A"]["learnDuration"], 4600)
        self.assertEqual(out["B"]["learnState"], 2)

    def test_empty_name_skipped(self):
        out = core.parse_progress_items([{"courseName": "  ", "progress": 1}])
        self.assertEqual(len(out), 0)

    def test_none_returns_empty(self):
        self.assertEqual(core.parse_progress_items(None), {})


class TestIsCourseComplete(unittest.TestCase):
    def test_by_learn_state(self):
        self.assertTrue(core.is_course_complete({"learnState": 2}))
        self.assertFalse(core.is_course_complete({"learnState": 1}))

    def test_by_progress(self):
        self.assertTrue(core.is_course_complete({"progress": 100}))
        self.assertTrue(core.is_course_complete({"progress": 123}))
        self.assertFalse(core.is_course_complete({"progress": 73}))

    def test_by_finish_date(self):
        self.assertTrue(core.is_course_complete({"finishDate": "2026-09-06"}))

    def test_empty_entry(self):
        self.assertFalse(core.is_course_complete({}))
        self.assertFalse(core.is_course_complete(None))


class TestTotalLearned(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(core.total_learned([7450, 8100, 9200]), 24750.0)

    def test_empty(self):
        self.assertEqual(core.total_learned([]), 0.0)

    def test_nulls(self):
        self.assertEqual(core.total_learned([100, None, 50]), 150.0)


if __name__ == "__main__":
    unittest.main()
