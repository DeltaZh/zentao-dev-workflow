# 禅道预览与仓库边界 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 写禅道前用预览说明任务来源、工时和标题，并拦住非 git 根目录、未绑定仓库和别人的任务。

**Architecture:** 口径放在配置 `policy`，由 `load_policy` 合并默认值。仓库与归属判断集中在 `assert_git_root`、`assert_task_owner`、`assert_assign_self`。Agent 按 `SKILL.md` 出 Canvas 或文本预览；脚本不代替用户确认，也不改写工时数字。

**Tech Stack:** Python 3 标准库、unittest、Cursor Canvas（`cursor/canvas`）

## Global Constraints

- 需求顺序不变：建需求 → 评审激活 → 建迭代 → 关联需求 → 建任务 → 完成任务
- 评审后不改需求标题、描述、验收
- 当次口头指令高于 `policy`，`policy` 高于技能默认
- `openedBy` 才算自己的任务，不认 `assignedTo`
- 解析不出创建人时只读
- `--cwd` 必须已是 git 根目录；子目录直接失败并返回真实根目录和远程
- 绑定路径不是 git 根目录时不自动改写配置
- 建任务、改任务要求该根目录已绑定
- `assignToSelf=true` 时新建任务只能指派给当前账号
- CLI 不改小时数，不设最低工时
- 密码和 Token 不进 Canvas、不进仓库
- 测试不访问真实禅道

---

### Task 1: 纯函数校验

**Files:**
- Modify: `scripts/zentao.py`
- Test: `scripts/test_guards.py`

**Interfaces:**
- Produces: `load_policy(cfg) -> dict`，含 `defaultsUsed`、`hourMethodRecognized`、`titleStyleNeedsAsk`、`previewSurfaceRecognized`、`repoLockRecognized`
- Produces: `assert_git_root(cwd) -> {"gitRoot","remote","branch"}`，失败抛 `GuardError`
- Produces: `assert_task_owner(task, account, policy) -> str`
- Produces: `assert_assign_self(assigned_to, account, policy) -> str`
- Produces: `visible_tasks(tasks, account, policy) -> list[dict]`
- Produces: `find_binding(cfg, git_root) -> (binding, binding_path, is_git_root)`

- [x] **Step 1: 写失败测试并确认失败**

Run: `python3 scripts/test_guards.py`
Expected: FAIL，函数尚未定义

- [x] **Step 2: 实现上述函数**

- [x] **Step 3: 测试通过**

Run: `python3 scripts/test_guards.py`
Expected: PASS

### Task 2: 命令接入

**Files:**
- Modify: `scripts/zentao.py`
- Test: `scripts/test_guards.py`

**Interfaces:**
- Consumes: Task 1 的函数
- Produces: `show-policy`、`inspect-repo --cwd`、`list-tasks --execution`
- Produces: `bind-repo`、`create-story`、`create-execution`、`create-tasks`、任务 `update-status` 必须带 git 根目录 `--cwd`
- Produces: 任务 `update-status` 可选 `--name`、`--estimate`；需求拒绝这两项
- Produces: `config_path()` 每次读取 `ZENTAO_CONFIG`

- [x] **Step 1: 子目录、未绑定、别人的任务三个写命令非零退出**
- [x] **Step 2: 指派给别人时，在任何 POST 之前失败**
- [x] **Step 3: 测试通过**

### Task 3: 预览模板与说明

**Files:**
- Create: `templates/zentao-preview.canvas.tsx`
- Modify: `SKILL.md`、`README.md`、`reference.md`、`config.example.json`
- Modify: `docs/superpowers/specs/2026-10-04-zentao-preview-guard-design.md`（状态改为已确认）

- [x] **Step 1: 模板按规格展示仓库、工时依据、新建、修改、只读；空数组不渲染**
- [x] **Step 2: 文档去掉「AI 提速 / 0.5～4 小时」，README 不重复工时算法**
- [x] **Step 3: 搜索确认旧口径已删除**

Run: `rg -n "0\\.5～4|高效率|hourBias|AI 辅助" SKILL.md README.md reference.md config.example.json`
Expected: 无匹配
