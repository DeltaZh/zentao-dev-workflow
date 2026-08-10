# 禅道开发工作流 Skill Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地个人 Skill + CLI，使 Agent 能在确认后通过禅道 REST API 绑定仓库、创建需求/任务、填工时并改状态。

**Architecture:** `SKILL.md` 指导 Agent 流程；`scripts/zentao.py` 封装 REST；凭证与仓库绑定在 `~/.config/zentao/config.json`。

**Tech Stack:** Python 3 标准库；Cursor Agent Skills；禅道 `api.php/v1`。

## Global Constraints

- 凭证只存 `~/.config/zentao/config.json`，不进仓库
- 写操作必须先经用户确认
- 绑定以列表选择 id 为准
- 工时按偏高效率估算
- 无第三方 Python 依赖

---

### Task 1: 仓库骨架与设计入库

**Files:**
- Create: `.gitignore`
- Create: `docs/superpowers/plans/2026-08-10-zentao-dev-workflow.md`
- Keep: `docs/2026-08-10-zentao-dev-workflow-design.md`

- [x] 初始化 git 并提交设计/计划

---

### Task 2: CLI 核心（auth / 列表 / 绑定）

**Files:**
- Create: `scripts/zentao.py`
- Create: `config.example.json`

- [ ] 实现配置读写、Token 缓存、HTTP JSON
- [ ] 实现 `auth` / `list-products` / `list-projects` / `list-executions` / `bind-repo` / `show-repo`
- [ ] 本地 `--help` 与无配置时的错误路径冒烟

---

### Task 3: CLI 写操作

**Files:**
- Modify: `scripts/zentao.py`

- [ ] 实现 `create-story` / `create-tasks` / `update-status` / `link-story-execution`
- [ ] stdout 统一 JSON；错误走 stderr 非零退出

---

### Task 4: Skill 文档

**Files:**
- Create: `SKILL.md`
- Create: `reference.md`
- Create: `README.md`

- [ ] 写触发条件、开工/收工流程、确认门禁、命令表
- [ ] reference 记录 API 字段与状态映射

---

### Task 5: 提交实现

- [ ] 本地 git 提交实现（不含真实凭证）
