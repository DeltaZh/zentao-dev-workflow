# 禅道开发工作流 Skill 设计规格

日期：2026-08-10  
状态：工时原则与确认摘要已被 [2026-10-04 规格](superpowers/specs/2026-10-04-zentao-preview-guard-design.md) 替换。下文第 5.4、5.5 节只作历史记录，不要按其中的工时口径执行。  
目标位置：个人 Skill `~/.cursor/skills/zentao-dev-workflow/`

## 1. 背景与目标

在 Cursor 中，当用户要求「把某次改动创建需求 / 开发任务」时，Agent 读取本 Skill，通过禅道开放 REST API 自动：

- 仓库首次使用时绑定产品 / 项目（列表选择，写入 id）
- 开工：创建研发需求（Story）
- 收工：关联执行/迭代、创建或补全开发任务、填写偏高效率预计工时、推进状态

所有写操作必须先展示摘要并经用户确认后再调用接口。

## 2. 已确认决策

| 项 | 决策 |
|----|------|
| 创建对象 | 按当次说法灵活：提需求建需求，提任务建任务，都提则建一对（可拆成两步确认） |
| 凭证 | 个人配置文件 `~/.config/zentao/config.json`（非环境变量、不进仓库） |
| Skill 位置 | 个人 Skill `~/.cursor/skills/zentao-dev-workflow/` |
| 产品/项目绑定 | 每仓库首次使用时拉列表供选择；之后复用；以 id 为准 |
| 收工范围 | 关联迭代 + 建/补任务 + 偏高效率工时 + 推进状态；缺信息再问 |
| 确认门禁 | 每次写操作前先出摘要，用户确认后再调接口 |
| 实现形态 | Skill + 配置文件 + 轻量 Python CLI（方案 1） |

## 3. 配置

### 3.1 路径与权限

- 路径：`~/.config/zentao/config.json`
- 建议权限：`600`
- Skill 正文与任何仓库内文件不得存放密码

### 3.2 结构（示意）

```json
{
  "baseUrl": "https://zentao.example.com",
  "account": "your_account",
  "password": "your_password",
  "defaults": {
    "hourBias": "high_efficiency",
    "storyCategory": "feature",
    "confirmBeforeWrite": true
  },
  "statusMap": {
    "storyAfterCreate": "active",
    "taskAfterFinish": "done",
    "storyAfterFinishPartial": "developing",
    "storyAfterFinishAll": "developed"
  },
  "repos": {
    "/abs/path/to/repo": {
      "productId": 12,
      "productName": "某产品",
      "projectId": 34,
      "projectName": "某项目",
      "executionId": null,
      "executionName": null,
      "lastStoryId": null
    }
  }
}
```

说明：

- `statusMap` 存禅道内部状态值（如 `active` / `done`）；若与公司实例不一致，首次失败后由用户校准并写回配置
- `repos` 的 key 为仓库绝对路径（工作区 root）

## 4. 仓库绑定（首次）

1. 检测当前工作区路径是否已在 `repos` 中  
2. 若未绑定：
   1. `list-products` → 展示 `id + name` 列表，请用户选择（禁止仅靠手输名称模糊匹配）
   2. `list-projects --product <id>` → 展示项目列表供选择
   3. 可选：`list-executions --project <id>` → 选择默认执行/迭代；可跳过，收工时再选
   4. `bind-repo` 写入 id + 名称
3. 列表为空 / 403：说明原因；允许用户直接提供 id 兜底  
4. 当次口头指定其它产品/项目只影响当次；说「换绑 / 以后都用这个」才更新 `repos`

## 5. 工作流

### 5.1 触发语义

| 用户意图 | 流程 |
|----------|------|
| 创建需求 / 建研发需求 | 开工流 |
| 完善开发迭代和任务 / 收工 / 补任务工时 | 收工流 |
| 两者都提 | 先澄清或拆成两步确认；按话里主意图优先 |

### 5.2 开工流（建需求）

1. 确保已绑定（否则先绑定）  
2. 根据对话与改动起草需求摘要：标题、描述（背景+范围）、优先级、产品/项目  
3. 展示摘要，等待确认  
4. 调用 `create-story`  
5. 将 `storyId` 写入该仓库 `lastStoryId`，回复需求 ID 与链接  
6. 若配置允许，将需求状态推到 `statusMap.storyAfterCreate`（失败则报告，不阻断创建成功结果）

### 5.3 收工流（迭代 + 任务 + 工时 + 状态）

1. 定位需求：优先用户指定 ID → `lastStoryId` → 标题精确匹配；找不到则询问  
2. 确定执行/迭代：绑定值 / 用户指定 / 拉列表选择  
3. 结合 git diff / 会话改动起草 1～N 条开发任务与预计工时  
4. 展示整包摘要（需求、迭代、任务、工时、目标状态），等待确认  
5. 依次执行：关联执行（若支持）→ 创建任务并填预计工时 → 更新任务/需求状态  
6. 回传所有 ID/链接；部分失败时只重试失败步骤，不重复创建已成功对象

### 5.4 工时原则

- 按「熟悉代码库的高效开发者 + AI 辅助」估算，明显短于纯人工  
- 单任务常见 0.5～4h；整次改动通常约为纯人工口头量级的 50%～70%  
- 用户直接给定工时时，以用户为准  

### 5.5 确认摘要模板（写操作前）

```text
【禅道待确认】
类型：开工建需求 | 收工完善
仓库：...
产品：name (#id)
项目：name (#id)
执行/迭代：name (#id) | 无
需求：新建「标题」| 已有 #id
任务：
  - [ ] 标题A | 预计 1.0h | 指派 account
  - [ ] 标题B | 预计 0.5h | 指派 account
状态计划：任务→done；需求→developed/developing
请回复确认 / 修改意见
```

## 6. Skill 与脚本结构

```
~/.cursor/skills/zentao-dev-workflow/
├── SKILL.md
├── reference.md
├── docs/
│   └── 2026-08-10-zentao-dev-workflow-design.md
└── scripts/
    └── zentao.py
```

### 6.1 SKILL.md 要点

- `name`: `zentao-dev-workflow`
- `description`：第三人称，包含触发词（禅道、需求、开发任务、工时、迭代、收工等）
- **不**设置 `disable-model-invocation: true`（需在用户提到相关意图时自动选用）
- 正文：绑定 → 开工 → 收工 → 确认门禁 → 调用脚本命令表 → 失败处理
- 详细 API 字段放 `reference.md`

### 6.2 CLI 子命令

| 命令 | 作用 |
|------|------|
| `auth` | 读配置，获取/刷新 Token |
| `list-products` | GET 产品列表 |
| `list-projects --product <id>` | 获取与产品关联的项目列表 |
| `list-executions --project <id>` | 获取执行/迭代列表 |
| `bind-repo --cwd <path> --product <id> --project <id> [--execution <id>]` | 写入仓库绑定 |
| `create-story --payload <file>` | 创建需求 |
| `create-tasks --payload <file>` | 创建任务并填预计工时 |
| `update-status --type story\|task --id <id> --status <name>` | 更新状态 |
| `link-story-execution ...` | 需求关联执行（版本不支持则明确跳过并提示） |

实现约束：

- Python 3 + 标准库（`urllib` / `json` / `argparse`），避免额外依赖
- stdout 输出结构化 JSON（便于 Agent 解析）；人类可读错误走 stderr
- 密码不打印；Token 可短时缓存于 `~/.config/zentao/token-cache.json`（权限 600）

## 7. 禅道 API 边界（实现时以实例为准）

认证与通用：

- `POST {baseUrl}/api.php/v1/tokens`，body: `{account, password}`
- 后续请求 Header: `Token: <token>`，`Content-Type: application/json`

优先使用的 v1 能力（开源 16.5+ 常见）：

- `GET /api.php/v1/products` — 产品列表  
- `POST /api.php/v1/stories` — 创建需求（title, product, pri, category, spec, …）  
- 项目 / 执行 / 任务列表与创建：按官方路由与公司实例探测；任务多挂在 execution 下（如 `POST /api.php/v1/executions/{id}/tasks`）

实现阶段策略：

1. 先对用户实例做一次探测（哪些列表/创建接口可用）  
2. 将实际可用路径与必填字段固化进 `reference.md`  
3. 若仅应用密钥签名接口可用，再增加兼容模式（本规格默认 REST Token）

## 8. 失败处理

| 情况 | 行为 |
|------|------|
| 配置缺失 / 认证失败 | 停止并提示补全配置；401 时清 Token 重登一次 |
| 列表空 / 403 | 说明权限；允许 id 兜底 |
| 创建缺字段 | 展示禅道原始错误，补全后重试，不猜测 |
| 状态名不匹配 | 询问正确状态并写回 `statusMap` |
| 部分成功 | 报告已成功 ID，仅重试失败步骤 |

## 9. 非目标（本版本不做）

- 不做 Bug 转需求、测试单、发布  
- 不提供 GUI；选择通过对话列表完成（含新建产品/项目时的确认摘要）  
- 不实现完整 MCP Server（可后续演进）  
- 不把凭证写入环境变量或项目仓库  

### 9.1 已补充：新建产品 / 项目

- 绑定流程与独立意图均支持「新建产品 / 新建项目」
- 新建产品前先选项目集（`list-programs`）；新建项目必须关联至少一个产品 id
- 仍须用户确认摘要后再调用写接口

## 10. 验收标准

1. 新仓库首次触发时能列出产品并完成绑定，配置中出现正确 id  
2. 用户确认后能创建需求，并收到 id/链接；`lastStoryId` 已更新  
3. 收工确认后能创建任务、写入偏高效率预计工时，并尝试更新状态  
4. 未确认时不发生任何写接口调用  
5. 密码不会出现在命令行回显或 Skill 文件中  

## 11. 实现顺序（审阅通过后）

1. 补齐个人配置模板与 `zentao.py` 骨架（auth + list-products）  
2. 完成绑定相关命令  
3. 完成 create-story / create-tasks / update-status  
4. 编写 `SKILL.md` + `reference.md`  
5. 用用户真实禅道实例做一次冒烟（列表 → 绑定 → 建需求，任务视权限）  
