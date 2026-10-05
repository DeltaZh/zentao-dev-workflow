#!/usr/bin/env python3
"""校验纯函数与写命令拒绝路径。不访问真实禅道。"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


def load_cli():
    script = Path(__file__).with_name("zentao.py")
    spec = importlib.util.spec_from_file_location("zentao_cli_under_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zentao = load_cli()


def init_repo(path: Path, *, origin: str | None = "git@example.com:org/repo.git") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    if origin:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True, capture_output=True, text=True)
    return path


def write_config(path: Path, repos: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "baseUrl": "https://zentao.example.com",
                "account": "me",
                "password": "secret",
                "policy": {},
                "repos": repos,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class LoadPolicyTests(unittest.TestCase):
    def test_missing_policy_uses_defaults_and_marks_them(self) -> None:
        policy = zentao.load_policy({"defaults": {"hourBias": "high_efficiency", "assignToSelf": False}})
        self.assertEqual(policy["hourMethod"], "senior_by_volume_and_difficulty")
        self.assertTrue(policy["assignToSelf"])
        self.assertIn("assignToSelf", policy["defaultsUsed"])
        self.assertIn("hourMethod", policy["defaultsUsed"])
        self.assertTrue(policy["hourMethodRecognized"])
        self.assertFalse(policy["titleStyleNeedsAsk"])

    def test_policy_assign_to_self_false_wins_over_defaults(self) -> None:
        policy = zentao.load_policy({"defaults": {"assignToSelf": True}, "policy": {"assignToSelf": False}})
        self.assertFalse(policy["assignToSelf"])
        self.assertNotIn("assignToSelf", policy["defaultsUsed"])

    def test_unknown_hour_method_is_not_treated_as_recognized(self) -> None:
        policy = zentao.load_policy({"policy": {"hourMethod": "custom"}})
        self.assertEqual(policy["hourMethod"], "custom")
        self.assertFalse(policy["hourMethodRecognized"])

    def test_custom_title_without_note_needs_ask(self) -> None:
        policy = zentao.load_policy({"policy": {"titleStyle": "team-template"}})
        self.assertTrue(policy["titleStyleNeedsAsk"])

    def test_custom_title_with_note_does_not_need_ask(self) -> None:
        policy = zentao.load_policy(
            {"policy": {"titleStyle": "team-template", "titleStyleNote": "模块名加结果"}}
        )
        self.assertFalse(policy["titleStyleNeedsAsk"])
        self.assertEqual(policy["titleStyleNote"], "模块名加结果")


class GitRootTests(unittest.TestCase):
    def test_subdirectory_is_rejected_with_real_root_and_remote(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            sub = root / "src"
            sub.mkdir()
            with self.assertRaises(zentao.GuardError) as caught:
                zentao.assert_git_root(str(sub))
            self.assertEqual(caught.exception.details["gitRoot"], str(root.resolve()))
            self.assertEqual(caught.exception.details["remote"], "git@example.com:org/repo.git")
            self.assertIn("不是 git 根目录", str(caught.exception))

    def test_git_root_returns_remote_and_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo", origin=None)
            info = zentao.assert_git_root(str(root))
            self.assertEqual(info["gitRoot"], str(root.resolve()))
            self.assertIsNone(info["remote"])
            self.assertTrue(info["branch"])

    def test_not_a_repo(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(zentao.GuardError) as caught:
                zentao.assert_git_root(raw)
            self.assertNotIn("gitRoot", caught.exception.details)


class TaskOwnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = zentao.load_policy({})

    def test_string_opened_by_self(self) -> None:
        self.assertEqual(zentao.assert_task_owner({"id": 1, "openedBy": "me"}, "me", self.policy), "me")

    def test_object_opened_by_self(self) -> None:
        self.assertEqual(
            zentao.assert_task_owner({"id": 2, "openedBy": {"account": "me", "realname": "我"}}, "me", self.policy),
            "me",
        )

    def test_other_user_rejected(self) -> None:
        with self.assertRaises(zentao.GuardError) as caught:
            zentao.assert_task_owner({"id": 3, "openedBy": "other", "assignedTo": "me"}, "me", self.policy)
        self.assertEqual(caught.exception.details["openedBy"], "other")
        self.assertEqual(caught.exception.details["taskId"], 3)
        self.assertEqual(caught.exception.details["policyKey"], "allowModifyOthersTasks")

    def test_unknown_opened_by_is_readonly_even_if_modify_others_allowed(self) -> None:
        policy = zentao.load_policy({"policy": {"allowModifyOthersTasks": True}})
        with self.assertRaises(zentao.GuardError) as caught:
            zentao.assert_task_owner({"id": 4, "openedBy": {"realname": "未知"}}, "me", policy)
        self.assertTrue(caught.exception.details["unknown"])

    def test_modify_others_allowed_when_policy_says_so(self) -> None:
        policy = zentao.load_policy({"policy": {"allowModifyOthersTasks": True}})
        self.assertEqual(zentao.assert_task_owner({"id": 5, "openedBy": "other"}, "me", policy), "other")


class AssignSelfTests(unittest.TestCase):
    def test_rejects_other_assignee(self) -> None:
        policy = zentao.load_policy({})
        with self.assertRaises(zentao.GuardError) as caught:
            zentao.assert_assign_self("other", "me", policy)
        self.assertEqual(caught.exception.details["policyKey"], "assignToSelf")

    def test_blank_assignee_becomes_account(self) -> None:
        policy = zentao.load_policy({})
        self.assertEqual(zentao.assert_assign_self(None, "me", policy), "me")

    def test_policy_off_keeps_other_assignee(self) -> None:
        policy = zentao.load_policy({"policy": {"assignToSelf": False}})
        self.assertEqual(zentao.assert_assign_self("other", "me", policy), "other")


class VisibleTaskTests(unittest.TestCase):
    def test_filter_hides_others_and_unknown_when_read_disabled(self) -> None:
        policy = zentao.load_policy({"policy": {"allowReadOthersTasks": False}})
        tasks = [
            {"id": 1, "name": "自己的", "openedBy": "me", "assignedTo": "me", "estimate": 4, "status": "wait"},
            {"id": 2, "name": "别人的", "openedBy": {"account": "other"}, "estimate": 2, "status": "doing"},
            {"id": 3, "name": "不明", "openedBy": "", "estimate": 1, "status": "wait"},
        ]
        visible = zentao.visible_tasks(tasks, "me", policy)
        self.assertEqual([item["id"] for item in visible], [1])
        self.assertEqual(visible[0]["openedBy"], "me")

    def test_read_enabled_keeps_others(self) -> None:
        policy = zentao.load_policy({})
        visible = zentao.visible_tasks([{"id": 2, "name": "别人的", "openedBy": "other"}], "me", policy)
        self.assertEqual(visible[0]["openedBy"], "other")
        self.assertTrue(visible[0]["openedByKnown"])


class BindingTests(unittest.TestCase):
    def test_subdirectory_binding_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            sub = str((root / "src").resolve())
            (root / "src").mkdir()
            binding, binding_path, is_root = zentao.find_binding(
                {"repos": {sub: {"productId": 1}}},
                str(root.resolve()),
            )
            self.assertEqual(binding["productId"], 1)
            self.assertEqual(binding_path, sub)
            self.assertFalse(is_root)


class CommandRejectTests(unittest.TestCase):
    def test_create_tasks_subdirectory_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            sub = root / "src"
            sub.mkdir()
            cfg = Path(raw) / "config.json"
            write_config(cfg, {})
            payload = Path(raw) / "tasks.json"
            payload.write_text(
                json.dumps({"executionId": 1, "tasks": [{"name": "实现导出", "type": "devel", "estimate": 4}]}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["ZENTAO_CONFIG"] = str(cfg)
            env["ZENTAO_TOKEN_CACHE"] = str(Path(raw) / "token.json")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("zentao.py")),
                    "create-tasks",
                    "--payload",
                    str(payload),
                    "--cwd",
                    str(sub),
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(str(root.resolve()), proc.stderr)
            self.assertIn("git@example.com:org/repo.git", proc.stderr)
            self.assertNotIn("secret", proc.stderr)

    def test_create_tasks_unbound_root_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            cfg = Path(raw) / "config.json"
            write_config(cfg, {})
            payload = Path(raw) / "tasks.json"
            payload.write_text(
                json.dumps({"executionId": 1, "tasks": [{"name": "实现导出", "type": "devel"}]}),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["ZENTAO_CONFIG"] = str(cfg)
            env["ZENTAO_TOKEN_CACHE"] = str(Path(raw) / "token.json")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("zentao.py")),
                    "create-tasks",
                    "--payload",
                    str(payload),
                    "--cwd",
                    str(root),
                ],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("未绑定", proc.stderr)

    def test_update_status_rejects_other_owner_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            cfg = Path(raw) / "config.json"
            write_config(cfg, {str(root.resolve()): {"productId": 1, "projectId": 2}})
            env = os.environ.copy()
            env["ZENTAO_CONFIG"] = str(cfg)
            env["ZENTAO_TOKEN_CACHE"] = str(Path(raw) / "token.json")
            args = zentao.build_parser().parse_args(
                ["update-status", "--type", "task", "--id", "9", "--status", "done", "--cwd", str(root)]
            )
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(zentao, "fetch_task", return_value={"id": 9, "openedBy": "other", "name": "别人的"}):
                    with mock.patch.object(zentao, "request_with_auth", side_effect=AssertionError("不应写入")):
                        stderr = io.StringIO()
                        with redirect_stderr(stderr):
                            with self.assertRaises(SystemExit) as caught:
                                zentao.cmd_update_status(args)
            self.assertNotEqual(caught.exception.code, 0)
            self.assertIn("other", stderr.getvalue())
            self.assertNotIn("secret", stderr.getvalue())

    def test_create_tasks_rejects_foreign_assignee_before_post(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            cfg = Path(raw) / "config.json"
            write_config(cfg, {str(root.resolve()): {"productId": 1, "projectId": 2}})
            payload = Path(raw) / "tasks.json"
            payload.write_text(
                json.dumps(
                    {
                        "executionId": 3,
                        "tasks": [{"name": "实现导出", "type": "devel", "assignedTo": "other"}],
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["ZENTAO_CONFIG"] = str(cfg)
            env["ZENTAO_TOKEN_CACHE"] = str(Path(raw) / "token.json")
            args = zentao.build_parser().parse_args(
                ["create-tasks", "--payload", str(payload), "--cwd", str(root)]
            )
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(zentao, "request_with_auth", side_effect=AssertionError("不应写入")):
                    with self.assertRaises(SystemExit) as caught:
                        zentao.cmd_create_tasks(args)
            self.assertNotEqual(caught.exception.code, 0)

    def test_story_update_rejects_name_and_estimate(self) -> None:
        args = zentao.build_parser().parse_args(
            ["update-status", "--type", "story", "--id", "1", "--status", "active", "--name", "新标题"]
        )
        with self.assertRaises(SystemExit) as caught:
            zentao.cmd_update_status(args)
        self.assertNotEqual(caught.exception.code, 0)


class ApiPitTests(unittest.TestCase):
    def test_timestamps_follow_server_offset_without_z(self) -> None:
        now = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)
        started, finished = zentao.task_action_timestamps(1.5, now=now, offset_hours=8)
        self.assertEqual(started, "2026-10-05T09:30:00")
        self.assertEqual(finished, "2026-10-05T11:00:00")
        self.assertNotIn("Z", started + finished)

    def test_integer_offset_and_interval_are_accepted(self) -> None:
        policy = zentao.load_policy({"policy": {"serverUtcOffsetHours": 8, "writeIntervalSeconds": 1}})
        self.assertEqual(policy["serverUtcOffsetHours"], 8)
        self.assertEqual(policy["writeIntervalSeconds"], 1)
        self.assertNotIn("serverUtcOffsetHours", policy["defaultsUsed"])

    def test_strip_keeps_execution_status(self) -> None:
        payload = {"name": "迭代", "realBegan": "2026-10-01", "realEnd": "2026-10-05", "status": "closed", "days": 3}
        removed = zentao.strip_silent_fields(payload, ("realBegan", "realEnd"))
        self.assertEqual(removed, ["realBegan", "realEnd"])
        self.assertEqual(payload["status"], "closed")
        self.assertEqual(payload["days"], 3)

    def test_html_200_refreshes_token_and_retries(self) -> None:
        calls = {"n": 0}

        def fake_api(cfg, method, path, token=None, body=None, query=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise zentao.ZenTaoError("响应不是 JSON: <html>", status=200, body="<html>login", not_json=True)
            return {"id": 1}

        with mock.patch.object(zentao, "api_request", fake_api), mock.patch.object(
            zentao, "fetch_token", side_effect=["old", "new"]
        ) as fetch, mock.patch.object(zentao, "clear_token_cache") as clear, mock.patch.object(
            zentao.time, "sleep"
        ):
            result = zentao.request_with_auth({}, "GET", "/api.php/v1/tasks/1")
        self.assertEqual(result, {"id": 1})
        clear.assert_called()
        self.assertTrue(fetch.call_args_list[1].kwargs["force"])

    def test_pause_only_between_writes(self) -> None:
        slept: list[float] = []
        zentao.pause_between_writes(0, 0.35, sleep=slept.append)
        zentao.pause_between_writes(1, 0.35, sleep=slept.append)
        self.assertEqual(slept, [0.35])

    def _done_args(self, root: Path):
        return zentao.build_parser().parse_args(
            ["update-status", "--type", "task", "--id", "9", "--status", "done", "--cwd", str(root)]
        )

    def test_done_uses_start_and_finish_not_put(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = init_repo(Path(raw) / "repo")
            cfg = Path(raw) / "config.json"
            write_config(cfg, {str(root.resolve()): {"productId": 1, "projectId": 2}})
            env = os.environ.copy()
            env["ZENTAO_CONFIG"] = str(cfg)
            env["ZENTAO_TOKEN_CACHE"] = str(Path(raw) / "token.json")
            recorded: list[tuple[str, str, dict]] = []

            def fake_request(cfg, method, path, body=None, query=None):
                recorded.append((method, path, body or {}))
                if path.endswith("/start"):
                    raise zentao.ZenTaoError("任务已经开始", status=400, body="已经开始")
                return {"id": 9}

            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
                zentao, "fetch_task", return_value={"id": 9, "openedBy": "me", "estimate": 1.5, "name": "实现导出"}
            ), mock.patch.object(zentao, "request_with_auth", fake_request), mock.patch.object(
                zentao, "task_action_timestamps", return_value=("2026-10-05T09:30:00", "2026-10-05T11:00:00")
            ):
                with redirect_stdout(io.StringIO()):
                    zentao.cmd_update_status(self._done_args(root))
        self.assertTrue(recorded[0][1].endswith("/start"))
        self.assertEqual(recorded[0][2]["realStarted"], "2026-10-05T09:30:00")
        self.assertTrue(recorded[1][1].endswith("/finish"))
        self.assertEqual(recorded[1][2]["finishedDate"], "2026-10-05T11:00:00")
        self.assertNotIn("Z", recorded[1][2]["finishedDate"])
        self.assertFalse(any(method == "PUT" for method, _, _ in recorded))


if __name__ == "__main__":
    unittest.main()
