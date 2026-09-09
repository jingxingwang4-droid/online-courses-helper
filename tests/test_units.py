# -*- coding: utf-8 -*-
"""无需浏览器的纯逻辑单元测试。运行：python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
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


class TestFieldOrCurrent(unittest.TestCase):
    """严格合并：0 是合法值，None/缺失才回退旧值。"""

    def test_zero_is_kept(self):
        self.assertEqual(core.field_or_current({"learnDuration": 0}, "learnDuration", 500.0, float), 0.0)

    def test_none_keeps_current(self):
        self.assertEqual(core.field_or_current({"learnDuration": None}, "learnDuration", 500.0, float), 500.0)

    def test_missing_keeps_current(self):
        self.assertEqual(core.field_or_current({}, "learnDuration", 7.0, float), 7.0)

    def test_value_used(self):
        self.assertEqual(core.field_or_current({"progress": 73}, "progress", 0.0, float), 73.0)

    def test_cast_string(self):
        self.assertEqual(core.field_or_current({"learnDuration": "120"}, "learnDuration", 0, int), 120)

    def test_non_dict_entry(self):
        self.assertEqual(core.field_or_current(None, "x", 3.0, float), 3.0)

    def test_bad_cast_keeps_current(self):
        self.assertEqual(core.field_or_current({"progress": "abc"}, "progress", 9.9, float), 9.9)


class TestParseZeroValid(unittest.TestCase):
    """服务端 0 是合法值，不应被当作缺失回退默认。"""

    def test_progress_zero(self):
        self.assertEqual(core.parse_progress_items([{"courseName": "A", "progress": 0}])["A"]["progress"], 0.0)

    def test_learn_duration_zero(self):
        out = core.parse_progress_items([{"courseName": "A", "progress": 0, "learnDuration": 0}])
        self.assertEqual(out["A"]["learnDuration"], 0)
        self.assertEqual(out["A"]["progress"], 0.0)

    def test_duration_zero_kept(self):
        self.assertEqual(core.parse_progress_items([{"courseName": "A", "duration": 0}])["A"]["duration"], 0.0)

    def test_none_defaults(self):
        out = core.parse_progress_items([{"courseName": "A", "progress": None, "learnDuration": None, "duration": None}])
        self.assertEqual((out["A"]["progress"], out["A"]["learnDuration"], out["A"]["duration"]), (0.0, 0, 6300.0))

    def test_complete_even_with_zero(self):
        self.assertTrue(core.is_course_complete({"learnState": 2, "progress": 0, "learnDuration": 0}))


class TestSessionLogic(unittest.TestCase):
    """登录态相关纯逻辑：路径、文本判定、安全 JSON 读取。"""

    def test_logged_in_body(self):
        self.assertTrue(core.is_logged_in_by_body("学习中心 我的课程"))
        self.assertFalse(core.is_logged_in_by_body("首页 登录注册"))
        self.assertFalse(core.is_logged_in_by_body(None))

    def test_storage_path_shape(self):
        p = core.storage_state_path(r"E:\proj")
        self.assertTrue(p.endswith(os.path.join("session", "storage_state.json")))
        self.assertTrue(p.startswith(r"E:\proj"))

    def test_load_json_safe_missing(self):
        p = os.path.join(tempfile.gettempdir(), "__opencode_no_such.json")
        if os.path.exists(p):
            os.unlink(p)
        self.assertEqual(core.load_json_safe(p, "DEFAULT"), "DEFAULT")

    def test_load_json_safe_corrupt(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        f.write("{ broken json !!!")
        f.close()
        try:
            self.assertIsNone(core.load_json_safe(f.name, None))
        finally:
            os.unlink(f.name)

    def test_load_json_safe_valid(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"cookies": [], "origins": []}, f)
        f.close()
        try:
            self.assertEqual(core.load_json_safe(f.name), {"cookies": [], "origins": []})
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
