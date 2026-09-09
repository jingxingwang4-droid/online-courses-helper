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
            {"courseId": 1, "courseName": "A", "progress": 73.0, "learnState": 1, "duration": 6300, "learnDuration": 4600, "finishDate": None},
            {"courseId": 2, "courseName": "B", "progress": 100.0, "learnState": 2, "duration": 8100, "learnDuration": 8100, "finishDate": "2026-09-06"},
        ]
        out = core.parse_progress_items(items)
        self.assertEqual(set(out.keys()), {"1", "2"})
        self.assertEqual(out["1"]["progress"], 73.0)
        self.assertEqual(out["1"]["learnDuration"], 4600)
        self.assertEqual(out["1"]["name"], "A")
        self.assertEqual(out["2"]["learnState"], 2)

    def test_keyed_by_id_not_name(self):
        # 两个同名但 ID 不同的课程，必须互不串课
        out = core.parse_progress_items([
            {"courseId": 10, "courseName": "同名课", "progress": 20, "learnDuration": 1200},
            {"courseId": 11, "courseName": "同名课", "progress": 80, "learnDuration": 4800},
        ])
        self.assertEqual(set(out.keys()), {"10", "11"})
        self.assertEqual(out["10"]["progress"], 20.0)
        self.assertEqual(out["11"]["progress"], 80.0)

    def test_fallback_name_when_no_id(self):
        out = core.parse_progress_items([{"courseName": "孤立课", "progress": 50}])
        self.assertEqual(set(out.keys()), {"name:孤立课"})
        self.assertEqual(out["name:孤立课"]["cid"], "")

    def test_empty_name_and_no_id_skipped(self):
        out = core.parse_progress_items([{"courseName": "  ", "progress": 1}])
        self.assertEqual(len(out), 0)

    def test_none_returns_empty(self):
        self.assertEqual(core.parse_progress_items(None), {})

    def test_missing_fields_use_defaults(self):
        out = core.parse_progress_items([{"courseId": 9, "courseName": "缺损"}])
        e = out["9"]
        self.assertEqual((e["progress"], e["learnDuration"]), (0.0, 0))
        self.assertEqual(e["duration"], 6300.0)
        self.assertEqual(e["finishDate"], None)


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
        self.assertEqual(core.parse_progress_items([{"courseId": 1, "courseName": "A", "progress": 0}])["1"]["progress"], 0.0)

    def test_learn_duration_zero(self):
        out = core.parse_progress_items([{"courseId": 1, "courseName": "A", "progress": 0, "learnDuration": 0}])
        self.assertEqual(out["1"]["learnDuration"], 0)
        self.assertEqual(out["1"]["progress"], 0.0)

    def test_duration_zero_kept(self):
        self.assertEqual(core.parse_progress_items([{"courseId": 1, "courseName": "A", "duration": 0}])["1"]["duration"], 0.0)

    def test_none_defaults(self):
        out = core.parse_progress_items([{"courseId": 1, "courseName": "A", "progress": None, "learnDuration": None, "duration": None}])
        self.assertEqual((out["1"]["progress"], out["1"]["learnDuration"], out["1"]["duration"]), (0.0, 0, 6300.0))

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


class TestLoginMode(unittest.TestCase):
    """登录策略：账号密码只是自动填写的便利项，不应成为运行的必要条件。"""

    def test_resume_with_storage_no_creds(self):
        self.assertEqual(core.login_mode(True, False), "resume")

    def test_resume_with_storage_and_creds(self):
        self.assertEqual(core.login_mode(True, True), "resume")

    def test_auto_fill_no_storage_with_creds(self):
        self.assertEqual(core.login_mode(False, True), "auto_fill")

    def test_manual_no_storage_no_creds_allows_run(self):
        # 无 storage 也无账号密码时，仍应允许进入 headed 手动登录，而不是拒绝运行
        self.assertEqual(core.login_mode(False, False), "manual")


class TestAdvanceFailCount(unittest.TestCase):
    """服务端进度连续失败计数：成功清零，连续达阈值触发停止。"""

    def test_fail_increments(self):
        self.assertEqual(core.advance_fail_count(0, False, 3), (1, False))
        self.assertEqual(core.advance_fail_count(1, False, 3), (2, False))

    def test_success_resets_to_zero(self):
        self.assertEqual(core.advance_fail_count(2, True, 3), (0, False))
        self.assertEqual(core.advance_fail_count(5, True, 3), (0, False))

    def test_threshold_triggers_stop(self):
        self.assertEqual(core.advance_fail_count(2, False, 3), (3, True))

    def test_below_threshold_no_stop(self):
        self.assertEqual(core.advance_fail_count(0, False, 3)[1], False)

    def test_zero_gap_never_stops(self):
        # 失败后立刻成功，不应累积
        self.assertEqual(core.advance_fail_count(core.advance_fail_count(0, False, 3)[0], True, 3), (0, False))


class TestHasFullCreds(unittest.TestCase):
    """完整凭据 = 同时有账号与密码；缺任一项视为不完整。"""

    def test_both_required(self):
        self.assertTrue(core.has_full_creds("13800", "pwd"))
        self.assertFalse(core.has_full_creds("13800", ""))
        self.assertFalse(core.has_full_creds("", "pwd"))
        self.assertFalse(core.has_full_creds("", ""))

    def test_single_creds_treated_as_incomplete(self):
        # 只有账号或只有密码 -> 视为无完整凭据 -> manual（进入 headed 手动登录，而非自动填写）
        self.assertEqual(core.login_mode(False, core.has_full_creds("u", "")), "manual")
        self.assertEqual(core.login_mode(False, core.has_full_creds("", "p")), "manual")
        self.assertEqual(core.login_mode(False, core.has_full_creds("u", "p")), "auto_fill")
        self.assertEqual(core.login_mode(True, core.has_full_creds("u", "")), "resume")


class TestProgressForCourse(unittest.TestCase):
    """按课程 ID 取进度；ID 未命中/缺失时回退课程名。"""

    def _map(self):
        return core.parse_progress_items([
            {"courseId": 10, "courseName": "同名", "progress": 30, "learnDuration": 1800, "duration": 6000},
            {"courseId": 11, "courseName": "同名", "progress": 90, "learnDuration": 5400, "duration": 6000},
        ])

    def test_lookup_by_id(self):
        pm = self._map()
        self.assertEqual(core.progress_for_course(pm, 10, "同名")["progress"], 30.0)
        self.assertEqual(core.progress_for_course(pm, 11, "同名")["progress"], 90.0)

    def test_duplicate_names_not_merged(self):
        pm = self._map()
        self.assertNotEqual(core.progress_for_course(pm, 10, "同名")["progress"], core.progress_for_course(pm, 11, "同名")["progress"])

    def test_fallback_by_name_when_id_absent(self):
        pm = core.parse_progress_items([{"courseName": "孤立", "progress": 55}])
        self.assertEqual(core.progress_for_course(pm, None, "孤立")["progress"], 55.0)
        # ID 不在 map 里但名称命中，也应回退成功
        self.assertEqual(core.progress_for_course(pm, 99999, "孤立")["progress"], 55.0)

    def test_missing_returns_empty(self):
        self.assertEqual(core.progress_for_course({}, 1, "无"), {})
        self.assertEqual(core.progress_for_course(None, 1, "无"), {})


class TestOverallProgress(unittest.TestCase):
    """总进度为按课程时长加权，且限制在 0~100%。"""

    def test_weighted_vs_arithmetic(self):
        # 两门课：A 4800秒学满(100%)，B 12000秒只有一半(50%)。长课程B是低进度 -> 时长加权会比算术平均(75%)更小。
        entries = [
            {"learn_sec": 4800, "target": 4800},
            {"learn_sec": 6000, "target": 12000},
        ]
        self.assertAlmostEqual(core.overall_progress(entries), (4800 + 6000) / (4800 + 12000) * 100.0)

    def test_empty_returns_zero(self):
        self.assertEqual(core.overall_progress([]), 0.0)
        self.assertEqual(core.overall_progress(None), 0.0)

    def test_zero_and_missing_duration_fallback_no_exception(self):
        entries = [
            {"learn_sec": 3000, "target": 0},       # 0 时长 -> 兜底不崩
            {"learn_sec": 2000, "target": None},    # 缺失 -> 兜底不崩
        ]
        pct = core.overall_progress(entries)
        self.assertIsInstance(pct, float)
        self.assertTrue(0.0 <= pct <= 100.0)

    def test_clamped_to_100(self):
        entries = [{"learn_sec": 999999, "target": 5000}]
        self.assertEqual(core.overall_progress(entries), 100.0)

    def test_over_watch_capped_per_course(self):
        entries = [{"learn_sec": 8000, "target": 4000}]
        self.assertEqual(core.overall_progress(entries), 100.0)


class TestReachedCertTarget(unittest.TestCase):
    def test_below(self):
        self.assertFalse(core.reached_cert_target(53999, 54000))

    def test_at(self):
        self.assertTrue(core.reached_cert_target(54000, 54000))

    def test_above(self):
        self.assertTrue(core.reached_cert_target(60000, 54000))

    def test_zero_target_never_reached(self):
        self.assertFalse(core.reached_cert_target(100, 0))

    def test_none_safe(self):
        self.assertFalse(core.reached_cert_target(None, 54000))


class _FakePage:
    """极简 fake page：只提供 fetch_progress 所需的 evaluate 返回字符串。"""

    def __init__(self, payload):
        self._payload = payload

    def evaluate(self, *args, **kwargs):
        return self._payload


class TestCnkiClientProgress(unittest.TestCase):
    """cnki_client.fetch_progress 与页面数据解耦（fake page 注入），覆盖空列表/缺失/异常。"""

    def test_success_parse(self):
        import cnki_client
        payload = json.dumps({"success": True, "data": {"list": [{"courseId": 1, "courseName": "A", "progress": 73, "learnDuration": 4600, "duration": 6300}]}})
        auth = {"lid": "l", "uid": "u", "authtoken": "t"}
        res = cnki_client.fetch_progress(_FakePage(payload), auth)
        self.assertEqual(res["1"]["progress"], 73.0)
        self.assertEqual(res["1"]["learnDuration"], 4600)

    def test_empty_list_is_success(self):
        import cnki_client
        payload = json.dumps({"success": True, "data": {"list": []}})
        self.assertEqual(cnki_client.fetch_progress(_FakePage(payload), {"authtoken": "t"}), {})

    def test_missing_fields_default(self):
        import cnki_client
        payload = json.dumps({"success": True, "data": {"list": [{"courseId": 2, "courseName": "B"}]}})
        res = cnki_client.fetch_progress(_FakePage(payload), {"authtoken": "t"})
        self.assertEqual((res["2"]["progress"], res["2"]["learnDuration"]), (0.0, 0))

    def test_bad_json_returns_none(self):
        import cnki_client
        self.assertIsNone(cnki_client.fetch_progress(_FakePage("not json"), {"authtoken": "t"}))
        self.assertIsNone(cnki_client.fetch_progress(_FakePage(json.dumps({"success": False})), {"authtoken": "t"}))

    def test_no_token_returns_none(self):
        import cnki_client
        self.assertIsNone(cnki_client.fetch_progress(_FakePage("{}"), {"authtoken": ""}))


class TestRunScopedDefaults(unittest.TestCase):
    """新任务开始时应重置的生命周期字段，避免上一轮达标/暂停/停用状态残留。"""

    def test_defaults_clear_cert_reached(self):
        d = core.run_scoped_defaults()
        self.assertIs(d["cert_reached"], False)

    def test_defaults_clear_run_flags(self):
        d = core.run_scoped_defaults()
        self.assertIs(d["stop_requested"], False)
        self.assertIs(d["paused"], False)
        self.assertIs(d["done"], False)


class TestFallbackAmbiguity(unittest.TestCase):
    """缺 courseId 的名称兜底：单个可兜底；同名重复视为歧义，跳过自动关联，不静默覆盖。"""

    def test_single_missing_id_ok(self):
        pm = core.parse_progress_items([{"courseName": "孤立课", "progress": 50}])
        self.assertEqual(pm["name:孤立课"]["progress"], 50.0)
        self.assertEqual(core.progress_for_course(pm, None, "孤立课")["progress"], 50.0)
        single, amb = core.fallback_summary(pm)
        self.assertEqual(single, ["孤立课"])
        self.assertEqual(amb, [])

    def test_duplicate_missing_id_ambiguous(self):
        pm = core.parse_progress_items([
            {"courseName": "同名课", "progress": 10},
            {"courseName": "同名课", "progress": 90},
        ])
        self.assertIsNone(pm["name:同名课"])
        # 歧义 -> 不再自动匹配（返回空），绝不静默取其中之一
        self.assertEqual(core.progress_for_course(pm, None, "同名课"), {})
        single, amb = core.fallback_summary(pm)
        self.assertEqual(amb, ["同名课"])
        self.assertEqual(single, [])

    def test_different_ids_same_name_untouched(self):
        pm = core.parse_progress_items([
            {"courseId": 10, "courseName": "同名课", "progress": 20},
            {"courseId": 11, "courseName": "同名课", "progress": 80},
        ])
        self.assertEqual(pm["10"]["progress"], 20.0)
        self.assertEqual(pm["11"]["progress"], 80.0)
        self.assertEqual(core.fallback_summary(pm), ([], []))


if __name__ == "__main__":
    unittest.main()
