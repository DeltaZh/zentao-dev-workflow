#!/usr/bin/env python3
"""禅道 REST CLI：供 zentao-dev-workflow Skill 调用。仅用 Python 标准库。"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

def config_path() -> Path:
    return Path(os.environ.get("ZENTAO_CONFIG", Path.home() / ".config" / "zentao" / "config.json"))


TOKEN_CACHE_PATH = Path(
    os.environ.get("ZENTAO_TOKEN_CACHE", Path.home() / ".config/zentao/token-cache.json")
)


class ZenTaoError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
        not_json: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.body = body
        self.not_json = not_json


def emit(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        die(
            f"缺少配置文件: {path}\n"
            "请复制 skill 内 config.example.json 到该路径并填写 baseUrl/account/password。"
        )
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"配置文件 JSON 无效: {exc}")
    for key in ("baseUrl", "account", "password"):
        if not cfg.get(key):
            die(f"配置缺少必填字段: {key}")
    cfg["baseUrl"] = str(cfg["baseUrl"]).rstrip("/")
    cfg.setdefault("defaults", {})
    cfg.setdefault("statusMap", {})
    cfg.setdefault("repos", {})
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_token_cache() -> dict[str, Any]:
    if not TOKEN_CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_token_cache(cache: dict[str, Any]) -> None:
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        TOKEN_CACHE_PATH.chmod(0o600)
    except OSError:
        pass


def clear_token_cache() -> None:
    if TOKEN_CACHE_PATH.is_file():
        TOKEN_CACHE_PATH.unlink()


def api_request(
    cfg: dict[str, Any],
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: Any = None,
    query: dict[str, Any] | None = None,
) -> Any:
    url = cfg["baseUrl"] + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Token"] = token

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    # 公司禅道常见自签证书：配置 verifySsl=false 时可关闭校验
    if cfg.get("verifySsl", True) is False:
        context = ssl._create_unverified_context()
    else:
        context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ZenTaoError(
                    f"响应不是 JSON: {raw[:300]}",
                    status=resp.status,
                    body=raw,
                    not_json=True,
                ) from exc
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        parsed: Any
        try:
            parsed = json.loads(raw) if raw.strip() else raw
        except json.JSONDecodeError:
            parsed = raw
        raise ZenTaoError(f"HTTP {exc.code}: {parsed}", status=exc.code, body=parsed) from exc
    except urllib.error.URLError as exc:
        raise ZenTaoError(f"网络错误: {exc.reason}") from exc


def fetch_token(cfg: dict[str, Any], *, force: bool = False) -> str:
    cache = load_token_cache()
    account = cfg["account"]
    base = cfg["baseUrl"]
    if not force and cache.get("baseUrl") == base and cache.get("account") == account and cache.get("token"):
        return str(cache["token"])

    result = api_request(
        cfg,
        "POST",
        "/api.php/v1/tokens",
        body={"account": account, "password": cfg["password"]},
    )
    token = None
    if isinstance(result, dict):
        token = result.get("token")
    if not token:
        raise ZenTaoError(f"获取 token 失败: {result}")
    save_token_cache(
        {
            "baseUrl": base,
            "account": account,
            "token": token,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    return str(token)


def request_with_auth(
    cfg: dict[str, Any],
    method: str,
    path: str,
    *,
    body: Any = None,
    query: dict[str, Any] | None = None,
) -> Any:
    policy = load_policy(cfg)
    retries = int(policy.get("authRetries") or 0)
    backoff = float(policy.get("authBackoffSeconds") or 0)
    last: ZenTaoError | None = None
    for attempt in range(retries + 1):
        if attempt:
            clear_token_cache()
            if backoff > 0:
                time.sleep(backoff * attempt)
        try:
            token = fetch_token(cfg, force=attempt > 0)
            return api_request(cfg, method, path, token=token, body=body, query=query)
        except ZenTaoError as exc:
            last = exc
            # 过期 token 常返回登录页 HTML，HTTP 仍是 200，不是 401。502 后也可能紧接着拿到登录页。
            retryable = exc.not_json or exc.status in (401, 502, 503, 504)
            if not retryable or attempt == retries:
                raise
    if last is not None:
        raise last
    raise ZenTaoError("请求失败")


def normalize_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # 有些实例直接把对象字典用 id 做 key
        if payload and all(isinstance(v, dict) for v in payload.values()):
            return list(payload.values())  # type: ignore[arg-type]
    return []


def pick_fields(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields:
        if f in item:
            out[f] = item[f]
    if "id" in item and "id" not in out:
        out["id"] = item["id"]
    if "name" in item and "name" not in out:
        out["name"] = item["name"]
    return out


def resolve_cwd(cwd: str | None) -> str:
    path = Path(cwd or os.getcwd()).expanduser().resolve()
    return str(path)


class GuardError(Exception):
    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.details = {key: value for key, value in details.items() if value is not None}


def raise_guard(exc: GuardError) -> None:
    lines = [str(exc)]
    for key in ("gitRoot", "remote", "taskId", "openedBy", "bindingPath", "policyKey"):
        value = exc.details.get(key)
        if value is not None and value != "":
            lines.append(f"{key}={value}")
    die("\n".join(lines))


POLICY_DEFAULTS: dict[str, Any] = {
    "hourMethod": "senior_by_volume_and_difficulty",
    "titleStyle": "verb_result",
    "allowReadOthersTasks": True,
    "allowModifyOthersTasks": False,
    "requirePreview": True,
    "previewSurface": "canvas",
    "repoLock": "session_git_root",
    "assignToSelf": True,
    "titleStyleNote": "",
    "serverUtcOffsetHours": 8,
    "writeIntervalSeconds": 0.35,
    "authRetries": 2,
    "authBackoffSeconds": 0.5,
}

POLICY_TYPES: dict[str, type] = {
    "hourMethod": str,
    "titleStyle": str,
    "allowReadOthersTasks": bool,
    "allowModifyOthersTasks": bool,
    "requirePreview": bool,
    "previewSurface": str,
    "repoLock": str,
    "assignToSelf": bool,
    "titleStyleNote": str,
    "serverUtcOffsetHours": float,
    "writeIntervalSeconds": float,
    "authRetries": int,
    "authBackoffSeconds": float,
}

KNOWN_HOUR_METHODS = {"senior_by_volume_and_difficulty"}
KNOWN_TITLE_STYLES = {"verb_result"}
KNOWN_PREVIEW_SURFACES = {"canvas", "text"}
KNOWN_REPO_LOCKS = {"session_git_root"}


def load_policy(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("policy")
    if not isinstance(raw, dict):
        raw = {}
    policy: dict[str, Any] = {}
    defaults_used: list[str] = []
    for key, default in POLICY_DEFAULTS.items():
        value = raw.get(key)
        if key in raw and value is not None and policy_type_matches(POLICY_TYPES[key], value):
            policy[key] = value
        else:
            policy[key] = default
            defaults_used.append(key)
    policy["defaultsUsed"] = defaults_used
    policy["hourMethodRecognized"] = policy["hourMethod"] in KNOWN_HOUR_METHODS
    policy["previewSurfaceRecognized"] = policy["previewSurface"] in KNOWN_PREVIEW_SURFACES
    policy["repoLockRecognized"] = policy["repoLock"] in KNOWN_REPO_LOCKS
    note = str(policy.get("titleStyleNote") or "").strip()
    if policy["titleStyle"] == "verb_result":
        policy["titleStyleNeedsAsk"] = False
    elif note:
        policy["titleStyleNeedsAsk"] = False
    else:
        policy["titleStyleNeedsAsk"] = True
    return policy


def policy_type_matches(expected: type, value: Any) -> bool:
    if expected is bool:
        return isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def pause_between_writes(index: int, interval: float, sleep: Any = time.sleep) -> None:
    if index > 0 and interval > 0:
        sleep(interval)


def strip_silent_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    removed: list[str] = []
    for key in fields:
        if key in payload:
            payload.pop(key)
            removed.append(key)
    return removed


def task_action_timestamps(
    estimate_hours: float | None,
    *,
    now: datetime,
    offset_hours: float,
) -> tuple[str, str]:
    """动作接口把无时区字符串当服务器本地时间，再存成 UTC。带 Z 会被再减一次时差。"""
    zone = timezone(timedelta(hours=float(offset_hours)))
    end = now.astimezone(zone)
    hours = float(estimate_hours or 0)
    start = end - timedelta(hours=hours) if hours > 0 else end
    fmt = "%Y-%m-%dT%H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


def plan_task_status_writes(
    task_id: int,
    status: str,
    account: str,
    estimate_hours: float | None,
    *,
    now: datetime,
    offset_hours: float,
) -> list[dict[str, Any]]:
    if status not in ("doing", "done"):
        return []
    started, finished = task_action_timestamps(estimate_hours, now=now, offset_hours=offset_hours)
    actions = [
        {
            "method": "POST",
            "path": f"/api.php/v1/tasks/{int(task_id)}/start",
            "body": {"realStarted": started, "assignedTo": account},
        }
    ]
    if status == "done":
        finish_body: dict[str, Any] = {"finishedDate": finished, "assignedTo": account, "left": 0}
        if estimate_hours is not None:
            finish_body["currentConsumed"] = float(estimate_hours)
        actions.append(
            {
                "method": "POST",
                "path": f"/api.php/v1/tasks/{int(task_id)}/finish",
                "body": finish_body,
            }
        )
    return actions


def start_error_is_already_started(exc: ZenTaoError) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("已经开始", "已经启动", "already started", "has started"))


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def assert_git_root(cwd: str) -> dict[str, Any]:
    raw = Path(cwd).expanduser()
    if not raw.exists() or not raw.is_dir():
        raise GuardError(f"路径不存在: {cwd}", policyKey="repoLock")
    path = raw.resolve()
    top = run_git(path, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        raise GuardError(f"不是 git 仓库: {path}。请改用 git 根目录。", policyKey="repoLock")
    git_root = Path(top.stdout.strip()).resolve()
    remote_proc = run_git(git_root, "remote", "get-url", "origin")
    remote = remote_proc.stdout.strip() if remote_proc.returncode == 0 and remote_proc.stdout.strip() else None
    if path != git_root:
        raise GuardError(
            f"--cwd 不是 git 根目录。请改用 {git_root}，不要使用子目录。",
            gitRoot=str(git_root),
            remote=remote,
            policyKey="repoLock",
        )
    branch_proc = run_git(git_root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 and branch_proc.stdout.strip() else "HEAD"
    return {"gitRoot": str(git_root), "remote": remote, "branch": branch}


def require_git_cwd(cwd: str | None) -> dict[str, Any]:
    try:
        if not cwd:
            raise GuardError("写操作必须带 --cwd，且必须是 git 根目录。", policyKey="repoLock")
        return assert_git_root(cwd)
    except GuardError as exc:
        raise_guard(exc)
        raise AssertionError("raise_guard 不会返回")


def find_binding(cfg: dict[str, Any], git_root: str) -> tuple[dict[str, Any] | None, str | None, bool]:
    repos = cfg.get("repos") or {}
    if not isinstance(repos, dict):
        return None, None, False
    root = Path(git_root).expanduser().resolve()
    related: tuple[dict[str, Any], str, bool] | None = None
    for key, binding in repos.items():
        if not isinstance(binding, dict):
            continue
        try:
            key_path = Path(str(key)).expanduser().resolve()
        except OSError:
            continue
        if key_path == root:
            return binding, str(key), True
        if root in key_path.parents or key_path in root.parents:
            related = (binding, str(key), False)
    if related:
        return related
    return None, None, False


def assert_bound_root(cfg: dict[str, Any], git_root: str) -> dict[str, Any]:
    binding, binding_path, is_root = find_binding(cfg, git_root)
    if binding is not None and is_root:
        return binding
    if binding is not None and not is_root:
        raise GuardError(
            "绑定路径不是 git 根目录，请重新绑定。不会自动改写配置。",
            gitRoot=git_root,
            bindingPath=binding_path,
            policyKey="repoLock",
        )
    raise GuardError("仓库未绑定。请先 bind-repo。", gitRoot=git_root, policyKey="repoLock")


def parse_account(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        item = value.get("account")
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def assert_task_owner(task: dict[str, Any], account: str, policy: dict[str, Any]) -> str:
    opened = parse_account(task.get("openedBy"))
    task_id = task.get("id")
    if opened is None:
        raise GuardError(
            "创建人字段解析不出，该条只读，不修改。",
            taskId=task_id,
            unknown=True,
            policyKey="allowModifyOthersTasks",
        )
    if opened != account and not policy.get("allowModifyOthersTasks"):
        raise GuardError(
            "openedBy 不是当前账号，拒绝修改。可调整 policy.allowModifyOthersTasks。",
            taskId=task_id,
            openedBy=opened,
            policyKey="allowModifyOthersTasks",
        )
    return opened


def assert_assign_self(assigned_to: str | None, account: str, policy: dict[str, Any]) -> str:
    if not policy.get("assignToSelf", True):
        return assigned_to or account
    if assigned_to and assigned_to != account:
        raise GuardError(
            f"assignToSelf 为 true 时不能指派给 {assigned_to}。请改 policy.assignToSelf，或改为当前账号。",
            policyKey="assignToSelf",
        )
    return account


def task_summary(task: dict[str, Any]) -> dict[str, Any]:
    opened = parse_account(task.get("openedBy"))
    assigned = parse_account(task.get("assignedTo"))
    if assigned is None and isinstance(task.get("assignedTo"), str):
        assigned = task.get("assignedTo")
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "openedBy": opened,
        "openedByKnown": opened is not None,
        "assignedTo": assigned,
        "estimate": task.get("estimate"),
        "status": task.get("status"),
    }


def visible_tasks(tasks: list[dict[str, Any]], account: str, policy: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = [task_summary(task) for task in tasks if isinstance(task, dict)]
    if policy.get("allowReadOthersTasks", True):
        return summaries
    return [item for item in summaries if item.get("openedBy") == account]


def unwrap_task(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if "openedBy" in payload or "name" in payload:
            return payload
        for key in ("task", "data"):
            inner = payload.get(key)
            if isinstance(inner, dict):
                return inner
        return payload
    raise GuardError("读取任务失败，无法确认创建人，该条只读。", unknown=True, policyKey="allowModifyOthersTasks")


def fetch_task(cfg: dict[str, Any], task_id: int) -> dict[str, Any]:
    result = request_with_auth(cfg, "GET", f"/api.php/v1/tasks/{int(task_id)}")
    return unwrap_task(result)


def fetch_execution_tasks(cfg: dict[str, Any], execution_id: int) -> list[dict[str, Any]]:
    payload = request_with_auth(
        cfg,
        "GET",
        f"/api.php/v1/executions/{int(execution_id)}/tasks",
        query={"limit": 1000, "page": 1},
    )
    return normalize_list(payload, ("tasks", "data"))


def find_by_id(items: list[dict[str, Any]], item_id: int) -> dict[str, Any] | None:
    for item in items:
        try:
            if int(item.get("id")) == int(item_id):
                return item
        except (TypeError, ValueError):
            continue
    return None


def product_ids_of_project(project: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    products = project.get("products")
    if isinstance(products, list):
        for p in products:
            if isinstance(p, dict) and p.get("id") is not None:
                ids.add(int(p["id"]))
            elif isinstance(p, (int, str)) and str(p).isdigit():
                ids.add(int(p))
    elif isinstance(products, dict):
        for k, v in products.items():
            if str(k).isdigit():
                ids.add(int(k))
            if isinstance(v, dict) and v.get("id") is not None:
                ids.add(int(v["id"]))
            elif isinstance(v, (int, str)) and str(v).isdigit():
                ids.add(int(v))
    for key in ("product", "productID"):
        if project.get(key) is not None and str(project[key]).isdigit():
            ids.add(int(project[key]))
    return ids


def cmd_auth(_: argparse.Namespace) -> None:
    cfg = load_config()
    token = fetch_token(cfg, force=True)
    emit({"ok": True, "baseUrl": cfg["baseUrl"], "account": cfg["account"], "tokenPrefix": token[:6] + "..."})


def suggest_code(name: str, prefix: str = "item") -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "", name or "")
    if ascii_part:
        return ascii_part[:30]
    return f"{prefix}{int(datetime.now().timestamp())}"


def product_url(cfg: dict[str, Any], product_id: int) -> str:
    return f"{cfg['baseUrl']}/product-view-{product_id}.html"


def project_url(cfg: dict[str, Any], project_id: int) -> str:
    return f"{cfg['baseUrl']}/project-view-{project_id}.html"


def cmd_list_programs(_: argparse.Namespace) -> None:
    cfg = load_config()
    payload = request_with_auth(cfg, "GET", "/api.php/v1/programs", query={"limit": 1000, "page": 1})
    items = normalize_list(payload, ("programs", "data"))
    emit(
        {
            "ok": True,
            "count": len(items),
            "programs": [pick_fields(i, ("id", "name", "status", "parent", "begin", "end")) for i in items],
        }
    )


def cmd_list_products(_: argparse.Namespace) -> None:
    cfg = load_config()
    payload = request_with_auth(cfg, "GET", "/api.php/v1/products", query={"limit": 1000, "page": 1})
    items = normalize_list(payload, ("products", "data"))
    emit({"ok": True, "count": len(items), "products": [pick_fields(i, ("id", "name", "code", "status")) for i in items]})


def cmd_list_projects(args: argparse.Namespace) -> None:
    cfg = load_config()
    payload = request_with_auth(cfg, "GET", "/api.php/v1/projects", query={"limit": 1000, "page": 1})
    items = normalize_list(payload, ("projects", "data"))
    product_id = int(args.product) if args.product is not None else None
    warning = None
    if product_id is not None:
        filtered: list[dict[str, Any]] = []
        any_has_products = False
        for item in items:
            pids = product_ids_of_project(item)
            if pids:
                any_has_products = True
                if product_id in pids:
                    filtered.append(item)
        if any_has_products:
            items = filtered
        else:
            warning = "接口未返回项目-产品关联，已返回全部项目，请按名称核对"
    result: dict[str, Any] = {
        "ok": True,
        "count": len(items),
        "projects": [pick_fields(i, ("id", "name", "code", "status", "model")) for i in items],
    }
    if warning:
        result["warning"] = warning
    emit(result)


def cmd_list_executions(args: argparse.Namespace) -> None:
    cfg = load_config()
    project_id = int(args.project)
    payload = request_with_auth(
        cfg,
        "GET",
        f"/api.php/v1/projects/{project_id}/executions",
        query={"limit": 1000, "page": 1},
    )
    items = normalize_list(payload, ("executions", "data"))
    emit(
        {
            "ok": True,
            "projectId": project_id,
            "count": len(items),
            "executions": [pick_fields(i, ("id", "name", "code", "status", "begin", "end")) for i in items],
        }
    )


def cmd_show_repo(args: argparse.Namespace) -> None:
    cfg = load_config()
    cwd = resolve_cwd(args.cwd)
    binding = cfg.get("repos", {}).get(cwd)
    emit({"ok": True, "cwd": cwd, "bound": binding is not None, "binding": binding})


def cmd_bind_repo(args: argparse.Namespace) -> None:
    cfg = load_config()
    info = require_git_cwd(args.cwd)
    cwd = info["gitRoot"]
    products = normalize_list(
        request_with_auth(cfg, "GET", "/api.php/v1/products", query={"limit": 1000, "page": 1}),
        ("products", "data"),
    )
    projects = normalize_list(
        request_with_auth(cfg, "GET", "/api.php/v1/projects", query={"limit": 1000, "page": 1}),
        ("projects", "data"),
    )
    product = find_by_id(products, int(args.product))
    project = find_by_id(projects, int(args.project))
    if not product:
        die(f"未找到产品 id={args.product}")
    if not project:
        die(f"未找到项目 id={args.project}")

    execution_name = None
    execution_id = None
    if args.execution is not None:
        executions = normalize_list(
            request_with_auth(
                cfg,
                "GET",
                f"/api.php/v1/projects/{int(args.project)}/executions",
                query={"limit": 1000, "page": 1},
            ),
            ("executions", "data"),
        )
        execution = find_by_id(executions, int(args.execution))
        if not execution:
            die(f"未找到执行 id={args.execution}")
        execution_id = int(execution["id"])
        execution_name = execution.get("name")

    existing = cfg.setdefault("repos", {}).get(cwd, {})
    binding = {
        "productId": int(product["id"]),
        "productName": product.get("name"),
        "projectId": int(project["id"]),
        "projectName": project.get("name"),
        "executionId": execution_id,
        "executionName": execution_name,
        "lastStoryId": existing.get("lastStoryId"),
    }
    cfg["repos"][cwd] = binding
    save_config(cfg)
    emit({"ok": True, "cwd": cwd, "binding": binding, "configPath": str(config_path())})


def read_payload(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        die(f"payload 文件不存在: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"payload JSON 无效: {exc}")
    if not isinstance(data, dict):
        die("payload 必须是 JSON 对象")
    return data


def story_url(cfg: dict[str, Any], story_id: int) -> str:
    return f"{cfg['baseUrl']}/story-view-{story_id}.html"


def task_url(cfg: dict[str, Any], task_id: int) -> str:
    return f"{cfg['baseUrl']}/task-view-{task_id}.html"


def cmd_create_product(args: argparse.Namespace) -> None:
    cfg = load_config()
    payload = read_payload(args.payload)
    if not payload.get("name"):
        die("payload 缺少必填字段: name")
    if payload.get("program") is None:
        die("payload 缺少必填字段: program（所属项目集 id；可先 list-programs）")
    payload.setdefault("code", suggest_code(str(payload["name"]), "product"))
    payload.setdefault("type", "normal")
    payload.setdefault("acl", "open")
    payload["program"] = int(payload["program"])

    result = request_with_auth(cfg, "POST", "/api.php/v1/products", body=payload)
    product_id = result.get("id") if isinstance(result, dict) else None
    if product_id is None and isinstance(result, dict):
        # 少数实例可能把新建结果包在 products 里
        products = normalize_list(result, ("products", "data"))
        if products:
            product_id = products[-1].get("id")
    if product_id is None:
        raise ZenTaoError(f"创建产品未返回 id: {result}")

    emit(
        {
            "ok": True,
            "productId": int(product_id),
            "name": payload.get("name"),
            "code": payload.get("code"),
            "program": payload.get("program"),
            "url": product_url(cfg, int(product_id)),
            "raw": result,
        }
    )


def cmd_create_project(args: argparse.Namespace) -> None:
    cfg = load_config()
    payload = read_payload(args.payload)
    for key in ("name", "products"):
        if key not in payload:
            die(f"payload 缺少必填字段: {key}")
    products = payload["products"]
    if not isinstance(products, list) or not products:
        die("payload.products 必须是非空数组，例如 [12]")
    payload["products"] = [int(x) for x in products]
    payload.setdefault("code", suggest_code(str(payload["name"]), "project"))
    payload.setdefault("model", "scrum")
    payload.setdefault("parent", 0)
    if not payload.get("begin") or not payload.get("end"):
        start = date.today()
        end = start + timedelta(days=90)
        payload.setdefault("begin", start.isoformat())
        payload.setdefault("end", end.isoformat())

    result = request_with_auth(cfg, "POST", "/api.php/v1/projects", body=payload)
    project_id = result.get("id") if isinstance(result, dict) else None
    if project_id is None:
        raise ZenTaoError(f"创建项目未返回 id: {result}")

    emit(
        {
            "ok": True,
            "projectId": int(project_id),
            "name": payload.get("name"),
            "code": payload.get("code"),
            "products": payload.get("products"),
            "begin": payload.get("begin"),
            "end": payload.get("end"),
            "url": project_url(cfg, int(project_id)),
            "raw": result,
        }
    )


def execution_url(cfg: dict[str, Any], execution_id: int) -> str:
    return f"{cfg['baseUrl']}/execution-view-{execution_id}.html"


def cmd_get_story(args: argparse.Namespace) -> None:
    cfg = load_config()
    story_id = int(args.id)
    result = request_with_auth(cfg, "GET", f"/api.php/v1/stories/{story_id}")
    story = result if isinstance(result, dict) else {}
    if isinstance(result, dict) and isinstance(result.get("story"), dict):
        story = result["story"]
    status = story.get("status")
    stage = story.get("stage")
    emit(
        {
            "ok": True,
            "storyId": story_id,
            "status": status,
            "stage": stage,
            "title": story.get("title"),
            "needsReview": status in ("draft", "changing", "changed", "reviewing", None),
            "readyForExecution": status == "active",
            "url": story_url(cfg, story_id),
            "raw": result,
        }
    )


def cmd_review_story(args: argparse.Namespace) -> None:
    """尽力将需求评审为激活。官方 REST 对评审支持不稳定，多路径尝试。"""
    cfg = load_config()
    story_id = int(args.id)
    account = cfg.get("account")
    assigned = args.assigned_to or account
    comment = args.comment or "Cursor Skill 评审通过"
    body_activate = {"assignedTo": assigned, "comment": comment}
    body_review = {
        "result": "pass",
        "assignedTo": assigned,
        "reviewedBy": assigned,
        "comment": comment,
        "reviewer": [assigned] if assigned else [],
    }
    attempts = [
        ("PUT", f"/api.php/v1/stories/{story_id}/activate", body_activate),
        ("PUT", f"/api.php/v2/stories/{story_id}/activate", body_activate),
        ("POST", f"/api.php/v1/stories/{story_id}/activate", body_activate),
        ("POST", f"/api.php/v2/stories/{story_id}/activate", body_activate),
        ("PUT", f"/api.php/v1/stories/{story_id}/review", body_review),
        ("POST", f"/api.php/v1/stories/{story_id}/review", body_review),
        ("PUT", f"/api.php/v1/stories/{story_id}", {"status": "active", "assignedTo": assigned}),
    ]
    errors = []
    for method, path, body in attempts:
        try:
            result = request_with_auth(cfg, method, path, body=body)
            # 再读一次确认状态
            check = None
            try:
                check = request_with_auth(cfg, "GET", f"/api.php/v1/stories/{story_id}")
            except ZenTaoError:
                check = None
            status = None
            if isinstance(check, dict):
                status = check.get("status")
                if isinstance(check.get("story"), dict):
                    status = check["story"].get("status", status)
            emit(
                {
                    "ok": True,
                    "storyId": story_id,
                    "method": method,
                    "path": path,
                    "status": status,
                    "readyForExecution": status == "active",
                    "url": story_url(cfg, story_id),
                    "raw": result,
                    "check": check,
                    "note": None
                    if status == "active"
                    else "接口已调用，但状态可能仍非 active；请在禅道 UI 确认评审结果后再继续建迭代/任务",
                }
            )
            return
        except ZenTaoError as exc:
            errors.append({"method": method, "path": path, "error": str(exc)})
    emit(
        {
            "ok": False,
            "storyId": story_id,
            "message": "自动评审/激活失败。请在禅道 UI 用评审人账号完成「评审通过」后，再继续建迭代与任务。",
            "errors": errors,
            "url": story_url(cfg, story_id),
        }
    )
    raise SystemExit(4)


def cmd_create_execution(args: argparse.Namespace) -> None:
    cfg = load_config()
    info = require_git_cwd(args.cwd)
    payload = read_payload(args.payload)
    project_id = payload.get("project") or payload.get("projectId")
    if project_id is None:
        die("payload 需要 project（所属项目 id）")
    if not payload.get("name"):
        die("payload 缺少必填字段: name")
    payload["project"] = int(project_id)
    payload.setdefault("code", suggest_code(str(payload["name"]), "sprint"))
    account = cfg.get("account")
    if account:
        payload.setdefault("PM", account)
        payload.setdefault("teamMembers", [account])
    if not payload.get("begin") or not payload.get("end"):
        start = date.today()
        end = start + timedelta(days=14)
        payload.setdefault("begin", start.isoformat())
        payload.setdefault("end", end.isoformat())
    ignored = strip_silent_fields(payload, ("realBegan", "realEnd"))

    result = request_with_auth(
        cfg,
        "POST",
        f"/api.php/v1/projects/{int(project_id)}/executions",
        body=payload,
    )
    execution_id = result.get("id") if isinstance(result, dict) else None
    if execution_id is None:
        raise ZenTaoError(f"创建执行未返回 id: {result}")

    cwd = info["gitRoot"]
    binding, binding_path, is_root = find_binding(cfg, cwd)
    if binding and is_root and binding_path:
        cfg["repos"][binding_path]["executionId"] = int(execution_id)
        cfg["repos"][binding_path]["executionName"] = payload.get("name")
        save_config(cfg)

    emitted: dict[str, Any] = {
        "ok": True,
        "executionId": int(execution_id),
        "projectId": int(project_id),
        "name": payload.get("name"),
        "code": payload.get("code"),
        "url": execution_url(cfg, int(execution_id)),
        "raw": result,
        "updatedRepo": cwd,
    }
    if ignored:
        emitted["ignoredFields"] = ignored
        emitted["warning"] = "realBegan/realEnd 会被接口静默忽略，未写入。关闭迭代时 closedDate 由服务器时钟填写，可能和本机差一天。"
    emit(emitted)


def cmd_create_story(args: argparse.Namespace) -> None:
    cfg = load_config()
    info = require_git_cwd(args.cwd)
    payload = read_payload(args.payload)
    for key in ("title", "product", "pri", "category"):
        if key not in payload:
            die(f"payload 缺少必填字段: {key}")

    account = cfg.get("account")
    if account:
        payload.setdefault("assignedTo", account)
        # 开启评审时需要 reviewer；默认本人
        if "reviewer" not in payload:
            payload["reviewer"] = [account]

    result = request_with_auth(cfg, "POST", "/api.php/v1/stories", body=payload)
    story_id = None
    if isinstance(result, dict):
        story_id = result.get("id")
    if story_id is None:
        raise ZenTaoError(f"创建需求未返回 id: {result}")

    cwd = info["gitRoot"]
    binding, binding_path, is_root = find_binding(cfg, cwd)
    if binding and is_root and binding_path:
        cfg["repos"][binding_path]["lastStoryId"] = int(story_id)
        save_config(cfg)

    emit(
        {
            "ok": True,
            "storyId": int(story_id),
            "url": story_url(cfg, int(story_id)),
            "raw": result,
            "updatedRepo": cwd,
            "next": "必须先评审/激活需求（review-story），再创建迭代、关联、建任务",
        }
    )


def default_task_dates(estimate_hours: float | None) -> tuple[str, str]:
    start = date.today()
    hours = float(estimate_hours or 1)
    days = max(1, int((hours + 7.9) // 8))
    end = start + timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def cmd_create_tasks(args: argparse.Namespace) -> None:
    cfg = load_config()
    payload = read_payload(args.payload)
    info = require_git_cwd(args.cwd)
    try:
        assert_bound_root(cfg, info["gitRoot"])
    except GuardError as exc:
        raise_guard(exc)
    execution_id = payload.get("executionId") or payload.get("execution")
    tasks = payload.get("tasks")
    if execution_id is None:
        die("payload 需要 executionId")
    if not isinstance(tasks, list) or not tasks:
        die("payload.tasks 必须是非空数组")

    policy = load_policy(cfg)
    account = str(cfg.get("account") or "")
    top_assignee = payload.get("assignedTo")
    for task in tasks:
        if not isinstance(task, dict):
            continue
        explicit = task.get("assignedTo") or top_assignee
        try:
            assert_assign_self(str(explicit) if explicit else None, account, policy)
        except GuardError as exc:
            raise_guard(exc)

    created = []
    errors = []
    write_index = 0
    interval = float(policy.get("writeIntervalSeconds") or 0)
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append({"index": idx, "error": "task 不是对象"})
            continue
        if not task.get("name") or not task.get("type"):
            errors.append({"index": idx, "error": "缺少 name 或 type"})
            continue
        body = dict(task)
        explicit = task.get("assignedTo") or top_assignee
        try:
            body["assignedTo"] = assert_assign_self(str(explicit) if explicit else None, account, policy)
        except GuardError as exc:
            raise_guard(exc)
        body.setdefault("pri", 3)
        strip_silent_fields(body, ("realStarted", "finishedDate", "realBegan", "realEnd"))
        if "estimate" in body and body["estimate"] is not None:
            body["estimate"] = float(body["estimate"])
        if not body.get("estStarted") or not body.get("deadline"):
            est, deadline = default_task_dates(body.get("estimate"))
            body.setdefault("estStarted", est)
            body.setdefault("deadline", deadline)
        try:
            pause_between_writes(write_index, interval)
            write_index += 1
            result = request_with_auth(
                cfg,
                "POST",
                f"/api.php/v1/executions/{int(execution_id)}/tasks",
                body=body,
            )
            task_id = result.get("id") if isinstance(result, dict) else None
            created.append(
                {
                    "index": idx,
                    "taskId": int(task_id) if task_id is not None else None,
                    "name": body.get("name"),
                    "url": task_url(cfg, int(task_id)) if task_id is not None else None,
                    "raw": result,
                }
            )
        except ZenTaoError as exc:
            errors.append({"index": idx, "name": task.get("name"), "error": str(exc), "body": exc.body})

    emit(
        {
            "ok": len(errors) == 0,
            "executionId": int(execution_id),
            "created": created,
            "errors": errors,
        }
    )
    if errors:
        raise SystemExit(2)


def cmd_update_status(args: argparse.Namespace) -> None:
    if args.type == "story" and (args.name or args.estimate is not None):
        die("需求的 update-status 只接受 status 和 stage，不接受标题、描述、验收、工时。")

    cfg = load_config()
    entity = args.type
    entity_id = int(args.id)
    status = args.status
    if entity == "story":
        path = f"/api.php/v1/stories/{entity_id}"
        body: dict[str, Any] = {"status": status}
        if args.stage:
            body["stage"] = args.stage
        result = put_status(cfg, entity, entity_id, path, body)
        emit({"ok": True, "type": entity, "id": entity_id, "status": status, "raw": result})
        return
    if entity != "task":
        die("type 只能是 story 或 task")

    info = require_git_cwd(args.cwd)
    try:
        assert_bound_root(cfg, info["gitRoot"])
        task = fetch_task(cfg, entity_id)
        assert_task_owner(task, str(cfg.get("account") or ""), load_policy(cfg))
    except GuardError as exc:
        raise_guard(exc)

    policy = load_policy(cfg)
    account = str(cfg.get("account") or "")
    interval = float(policy.get("writeIntervalSeconds") or 0)
    estimate = args.estimate if args.estimate is not None else task.get("estimate")
    step = 0
    put_result = None
    if args.name or args.estimate is not None:
        put_body: dict[str, Any] = {}
        if args.name:
            put_body["name"] = args.name
        if args.estimate is not None:
            put_body["estimate"] = float(args.estimate)
        strip_silent_fields(put_body, ("realStarted", "finishedDate", "realBegan", "realEnd"))
        pause_between_writes(step, interval)
        step += 1
        put_result = put_status(cfg, "task", entity_id, f"/api.php/v1/tasks/{entity_id}", put_body)

    actions = plan_task_status_writes(
        entity_id,
        status,
        account,
        float(estimate) if estimate is not None else None,
        now=datetime.now(timezone.utc),
        offset_hours=float(policy.get("serverUtcOffsetHours") or 0),
    )
    action_results = []
    if actions:
        for action in actions:
            pause_between_writes(step, interval)
            step += 1
            try:
                raw = request_with_auth(cfg, action["method"], action["path"], body=action["body"])
            except ZenTaoError as exc:
                if action["path"].endswith("/start") and start_error_is_already_started(exc):
                    action_results.append({"path": action["path"], "skipped": True, "reason": str(exc)})
                    continue
                raise
            action_results.append({"path": action["path"], "body": action["body"], "raw": raw})
    elif put_result is None:
        put_body = {"status": status}
        put_result = put_status(cfg, "task", entity_id, f"/api.php/v1/tasks/{entity_id}", put_body)

    emit(
        {
            "ok": True,
            "type": "task",
            "id": entity_id,
            "status": status,
            "actions": action_results,
            "raw": put_result,
        }
    )


def put_status(
    cfg: dict[str, Any],
    entity: str,
    entity_id: int,
    path: str,
    body: dict[str, Any],
) -> Any:
    try:
        return request_with_auth(cfg, "PUT", path, body=body)
    except ZenTaoError as exc:
        if exc.status in (404, 405, 400):
            alt = f"/api.php/v1/{entity}s/{entity_id}/status" if entity == "task" else path
            try:
                return request_with_auth(cfg, "POST", alt, body=body)
            except ZenTaoError:
                raise exc from None
        raise


def cmd_link_story_execution(args: argparse.Namespace) -> None:
    cfg = load_config()
    story_id = int(args.story)
    execution_id = int(args.execution)
    attempts = [
        ("POST", f"/api.php/v1/executions/{execution_id}/stories", {"stories": [story_id]}),
        ("POST", f"/api.php/v1/stories/{story_id}/executions", {"executions": [execution_id]}),
        ("PUT", f"/api.php/v1/stories/{story_id}", {"executions": [execution_id]}),
    ]
    errors = []
    for method, path, body in attempts:
        try:
            result = request_with_auth(cfg, method, path, body=body)
            emit(
                {
                    "ok": True,
                    "storyId": story_id,
                    "executionId": execution_id,
                    "method": method,
                    "path": path,
                    "raw": result,
                }
            )
            return
        except ZenTaoError as exc:
            errors.append({"method": method, "path": path, "error": str(exc)})
    emit(
        {
            "ok": False,
            "skipped": True,
            "storyId": story_id,
            "executionId": execution_id,
            "message": "当前实例未找到可用的需求关联执行接口，请在禅道 UI 手动关联或告知可用 API",
            "errors": errors,
        }
    )
    raise SystemExit(3)


def cmd_show_policy(_: argparse.Namespace) -> None:
    cfg = load_config()
    emit({"ok": True, "policy": load_policy(cfg)})


def cmd_inspect_repo(args: argparse.Namespace) -> None:
    cfg = load_config()
    info = require_git_cwd(args.cwd)
    binding, binding_path, is_root = find_binding(cfg, info["gitRoot"])
    result: dict[str, Any] = {
        "ok": True,
        "gitRoot": info["gitRoot"],
        "remote": info["remote"],
        "branch": info["branch"],
        "bound": binding is not None and is_root,
        "binding": binding if binding is not None and is_root else None,
        "bindingPath": binding_path,
        "bindingPathIsGitRoot": is_root if binding_path else None,
    }
    messages: list[str] = []
    if binding_path and not is_root:
        messages.append("绑定路径不是 git 根目录，请重新绑定。不会自动改写配置。")
    if info["remote"] is None:
        messages.append("无 origin。确认这条路径之前不要写入。")
    if messages:
        result["message"] = " ".join(messages)
    emit(result)


def cmd_list_tasks(args: argparse.Namespace) -> None:
    cfg = load_config()
    policy = load_policy(cfg)
    tasks = fetch_execution_tasks(cfg, int(args.execution))
    visible = visible_tasks(tasks, str(cfg.get("account") or ""), policy)
    emit({"ok": True, "executionId": int(args.execution), "count": len(visible), "tasks": visible})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="禅道 REST CLI（zentao-dev-workflow）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("auth", help="获取/刷新 Token")
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("list-programs", help="列出项目集（创建产品前选用）")
    p.set_defaults(func=cmd_list_programs)

    p = sub.add_parser("list-products", help="列出产品")
    p.set_defaults(func=cmd_list_products)

    p = sub.add_parser("list-projects", help="列出项目")
    p.add_argument("--product", type=int, help="可选：按产品 id 过滤")
    p.set_defaults(func=cmd_list_projects)

    p = sub.add_parser("list-executions", help="列出项目下执行/迭代")
    p.add_argument("--project", type=int, required=True)
    p.set_defaults(func=cmd_list_executions)

    p = sub.add_parser("show-policy", help="打印合并默认值后的 policy")
    p.set_defaults(func=cmd_show_policy)

    p = sub.add_parser("inspect-repo", help="查看 git 根目录、远程和绑定")
    p.add_argument("--cwd", required=True)
    p.set_defaults(func=cmd_inspect_repo)

    p = sub.add_parser("list-tasks", help="列出执行下任务，供去重和区分创建人")
    p.add_argument("--execution", type=int, required=True)
    p.set_defaults(func=cmd_list_tasks)

    p = sub.add_parser("show-repo", help="查看当前仓库绑定")
    p.add_argument("--cwd", default=None)
    p.set_defaults(func=cmd_show_repo)

    p = sub.add_parser("bind-repo", help="绑定仓库到产品/项目/执行")
    p.add_argument("--cwd", default=None)
    p.add_argument("--product", type=int, required=True)
    p.add_argument("--project", type=int, required=True)
    p.add_argument("--execution", type=int, default=None)
    p.set_defaults(func=cmd_bind_repo)

    p = sub.add_parser("create-product", help="创建产品")
    p.add_argument("--payload", required=True, help="JSON 文件路径")
    p.set_defaults(func=cmd_create_product)

    p = sub.add_parser("create-project", help="创建项目（需关联已有产品）")
    p.add_argument("--payload", required=True, help="JSON 文件路径")
    p.set_defaults(func=cmd_create_project)

    p = sub.add_parser("create-story", help="创建需求")
    p.add_argument("--payload", required=True, help="JSON 文件路径")
    p.add_argument("--cwd", default=None, help="若提供且已绑定，则更新 lastStoryId")
    p.set_defaults(func=cmd_create_story)

    p = sub.add_parser("get-story", help="查看需求状态（是否已激活、是否需重新评审）")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_get_story)

    p = sub.add_parser("review-story", help="评审/激活需求（多路径尝试；失败则需 UI 评审）")
    p.add_argument("--id", required=True)
    p.add_argument("--assigned-to", default=None, help="指派给，默认配置 account")
    p.add_argument("--comment", default=None)
    p.set_defaults(func=cmd_review_story)

    p = sub.add_parser("create-execution", help="在项目下创建执行/迭代")
    p.add_argument("--payload", required=True)
    p.add_argument("--cwd", default=None, help="若提供且已绑定，则更新 executionId")
    p.set_defaults(func=cmd_create_execution)

    p = sub.add_parser("create-tasks", help="在执行下批量创建任务")
    p.add_argument("--payload", required=True)
    p.add_argument("--cwd", default=None, help="必须是已绑定的 git 根目录")
    p.set_defaults(func=cmd_create_tasks)

    p = sub.add_parser("update-status", help="更新需求或任务状态")
    p.add_argument("--type", required=True, choices=["story", "task"])
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--stage", default=None, help="可选，需求阶段如 developing/developed")
    p.add_argument("--name", default=None, help="仅任务：修改标题")
    p.add_argument("--estimate", type=float, default=None, help="仅任务：修改预计工时")
    p.add_argument("--cwd", default=None, help="任务更新时必须是已绑定的 git 根目录")
    p.set_defaults(func=cmd_update_status)

    p = sub.add_parser("link-story-execution", help="尝试将需求关联到执行")
    p.add_argument("--story", required=True, type=int)
    p.add_argument("--execution", required=True, type=int)
    p.set_defaults(func=cmd_link_story_execution)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except ZenTaoError as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
