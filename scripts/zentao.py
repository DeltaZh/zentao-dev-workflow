#!/usr/bin/env python3
"""禅道 REST CLI：供 zentao-dev-workflow Skill 调用。仅用 Python 标准库。"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("ZENTAO_CONFIG", Path.home() / ".config/zentao/config.json"))
TOKEN_CACHE_PATH = Path(
    os.environ.get("ZENTAO_TOKEN_CACHE", Path.home() / ".config/zentao/token-cache.json")
)


class ZenTaoError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def emit(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        die(
            f"缺少配置文件: {CONFIG_PATH}\n"
            "请复制 skill 内 config.example.json 到该路径并填写 baseUrl/account/password。"
        )
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
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
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ZenTaoError(f"响应不是 JSON: {raw[:300]}", status=resp.status, body=raw) from exc
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
    token = fetch_token(cfg)
    try:
        return api_request(cfg, method, path, token=token, body=body, query=query)
    except ZenTaoError as exc:
        if exc.status == 401:
            clear_token_cache()
            token = fetch_token(cfg, force=True)
            return api_request(cfg, method, path, token=token, body=body, query=query)
        raise


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
    cwd = resolve_cwd(args.cwd)
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
    emit({"ok": True, "cwd": cwd, "binding": binding, "configPath": str(CONFIG_PATH)})


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


def cmd_create_story(args: argparse.Namespace) -> None:
    cfg = load_config()
    payload = read_payload(args.payload)
    for key in ("title", "product", "pri", "category"):
        if key not in payload:
            die(f"payload 缺少必填字段: {key}")

    result = request_with_auth(cfg, "POST", "/api.php/v1/stories", body=payload)
    story_id = None
    if isinstance(result, dict):
        story_id = result.get("id")
    if story_id is None:
        raise ZenTaoError(f"创建需求未返回 id: {result}")

    cwd = resolve_cwd(args.cwd) if args.cwd else None
    if cwd and cwd in cfg.get("repos", {}):
        cfg["repos"][cwd]["lastStoryId"] = int(story_id)
        save_config(cfg)

    emit(
        {
            "ok": True,
            "storyId": int(story_id),
            "url": story_url(cfg, int(story_id)),
            "raw": result,
            "updatedRepo": cwd,
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
    execution_id = payload.get("executionId") or payload.get("execution")
    tasks = payload.get("tasks")
    if execution_id is None:
        die("payload 需要 executionId")
    if not isinstance(tasks, list) or not tasks:
        die("payload.tasks 必须是非空数组")

    account = payload.get("assignedTo") or cfg.get("account")
    created = []
    errors = []
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append({"index": idx, "error": "task 不是对象"})
            continue
        if not task.get("name") or not task.get("type"):
            errors.append({"index": idx, "error": "缺少 name 或 type"})
            continue
        body = dict(task)
        body.setdefault("assignedTo", account)
        body.setdefault("pri", 3)
        if "estimate" in body and body["estimate"] is not None:
            body["estimate"] = float(body["estimate"])
        if not body.get("estStarted") or not body.get("deadline"):
            est, deadline = default_task_dates(body.get("estimate"))
            body.setdefault("estStarted", est)
            body.setdefault("deadline", deadline)
        try:
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
    cfg = load_config()
    entity = args.type
    entity_id = int(args.id)
    status = args.status
    if entity == "story":
        path = f"/api.php/v1/stories/{entity_id}"
    elif entity == "task":
        path = f"/api.php/v1/tasks/{entity_id}"
    else:
        die("type 只能是 story 或 task")

    body: dict[str, Any] = {"status": status}
    if args.stage:
        body["stage"] = args.stage

    # 不同版本可能是 PUT 或 POST；先 PUT，失败再尝试常见变更接口
    try:
        result = request_with_auth(cfg, "PUT", path, body=body)
    except ZenTaoError as exc:
        if exc.status in (404, 405, 400):
            alt = f"/api.php/v1/{entity}s/{entity_id}/status" if entity == "task" else path
            try:
                result = request_with_auth(cfg, "POST", alt, body=body)
            except ZenTaoError:
                raise exc from None
        else:
            raise
    emit({"ok": True, "type": entity, "id": entity_id, "status": status, "raw": result})


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="禅道 REST CLI（zentao-dev-workflow）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("auth", help="获取/刷新 Token")
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("list-products", help="列出产品")
    p.set_defaults(func=cmd_list_products)

    p = sub.add_parser("list-projects", help="列出项目")
    p.add_argument("--product", type=int, help="可选：按产品 id 过滤")
    p.set_defaults(func=cmd_list_projects)

    p = sub.add_parser("list-executions", help="列出项目下执行/迭代")
    p.add_argument("--project", type=int, required=True)
    p.set_defaults(func=cmd_list_executions)

    p = sub.add_parser("show-repo", help="查看当前仓库绑定")
    p.add_argument("--cwd", default=None)
    p.set_defaults(func=cmd_show_repo)

    p = sub.add_parser("bind-repo", help="绑定仓库到产品/项目/执行")
    p.add_argument("--cwd", default=None)
    p.add_argument("--product", type=int, required=True)
    p.add_argument("--project", type=int, required=True)
    p.add_argument("--execution", type=int, default=None)
    p.set_defaults(func=cmd_bind_repo)

    p = sub.add_parser("create-story", help="创建需求")
    p.add_argument("--payload", required=True, help="JSON 文件路径")
    p.add_argument("--cwd", default=None, help="若提供且已绑定，则更新 lastStoryId")
    p.set_defaults(func=cmd_create_story)

    p = sub.add_parser("create-tasks", help="在执行下批量创建任务")
    p.add_argument("--payload", required=True)
    p.set_defaults(func=cmd_create_tasks)

    p = sub.add_parser("update-status", help="更新需求或任务状态")
    p.add_argument("--type", required=True, choices=["story", "task"])
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--stage", default=None, help="可选，需求阶段如 developing/developed")
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
