---
name: zentao-dev-workflow
description: 通过禅道 REST API 按固定顺序新建产品/项目、创建并评审需求、创建迭代、关联需求、创建并完成开发任务。在用户提到禅道、新建产品、新建项目、创建需求、评审需求、建迭代、开发任务、收工补任务/工时、绑定产品项目，或要求把某次改动同步到禅道时使用。
---

# 禅道开发工作流

用个人配置调用本 Skill 自带 CLI，把 Cursor 中的改动同步为禅道需求/任务。  
**任何写操作（创建、改状态、关联）之前，必须先给出摘要并得到用户确认。**

## 强制顺序（硬门槛，禁止打乱）

禅道需求生命周期必须按下面顺序推进。**打乱顺序或评审后改需求正文，状态会变成「需求变更 / changed」，必须重新评审后才能继续。**

```text
1. 建需求 (create-story)
2. 评审需求 → 激活 (review-story；失败则用户在 UI 评审通过)
3. 建迭代/执行 (create-execution) 或选用已有迭代
4. 关联需求到迭代 (link-story-execution)
5. 建任务 (create-tasks)
6. 完成任务 (update-status task → done)
```

### 顺序红线

- **未评审/未激活**（`draft` / `reviewing` / `changed` 等）时：禁止建任务；禁止把需求当已激活去推进开发阶段。
- **评审通过（`active`）之后**：禁止再改需求标题/描述/验收（`title`/`spec`/`verify`）；若必须改，走变更并重新评审，不要静默 `PUT` 正文。
- **关联与建任务**只能发生在需求已 `active` 之后。先 `get-story` 确认 `readyForExecution=true`。
- 若发现 `status=changed`：先告知用户「需重新评审」，执行 `review-story`（或请用户 UI 评审），确认再次 `active` 后再继续。

## 路径

- Skill 根目录：本文件所在目录（下称 `$SKILL`）
- CLI：`python3 "$SKILL/scripts/zentao.py"`
- 配置：`~/.config/zentao/config.json`（模板见 `$SKILL/config.example.json`）
- 字段与 API 细节：[reference.md](reference.md)

## 站立约定（默认，用户未特别说明时）

1. **人员一律当前登录用户**：需求/任务的负责人、指派给、开发（以及激活评审人 `reviewer`）默认都用配置里的 `account`（即 CLI 当前登录账号）。**禁止**擅自指派给他人；仅当用户当次明确指定别人时才改。
2. **项目/执行状态由用户管**：用户在禅道 UI 里改的项目状态（如「已开始」）以用户为准；Agent **不要**主动改项目/迭代的 `status`（`wait`/`doing`/`closed` 等），除非用户当次要求。
3. **文案直白、禁止讨论代号**：需求标题/描述/验收、任务名称/描述里，**不要**写「方案 A/B」「策略 D」「硬门槛 A/B/C」「风控 B1」等仅在对话里出现的代号；要写成普通人能看懂的「是什么 + 为什么 + 怎么验收」。技术名词（Sidecar、Cookie）可保留，但必须有中文说明。

## 前置检查

1. 若配置不存在：指导用户复制 `config.example.json` → `~/.config/zentao/config.json`，填 `baseUrl` / `account` / `password`，权限建议 `chmod 600`
2. 运行 `python3 "$SKILL/scripts/zentao.py" auth` 验证登录
3. `python3 "$SKILL/scripts/zentao.py" show-repo --cwd "<workspace>"` 检查是否已绑定

## 仓库绑定（首次）

未绑定则**拉列表请用户选择 id**；列表中提供「新建」选项。禁止只靠手输名称模糊匹配。

1. `list-products` → 展示 `id + name`，请用户选产品，或选「新建产品」  
2. 若新建产品：先 `list-programs` 选项目集 → 确认摘要 → `create-product` → 用返回的 `productId`  
3. `list-projects --product <id>` → 选项目，或选「新建项目」  
4. 若新建项目：确认摘要（名称/代号/关联产品/起止日期）→ `create-project` → 用返回的 `projectId`  
5. 可选：`list-executions --project <id>` → 选默认迭代；可跳过，收工时再建/再选  
6. `bind-repo --cwd "<workspace>" --product <id> --project <id> [--execution <id>]`  
7. 当次换产品不改绑定；用户说「换绑 / 以后都用这个」才重新 bind

## 新建产品 / 项目（可独立触发）

用户明确说「新建产品 / 新建项目」时，不必等到绑定时再做；同样**先确认摘要再写接口**。

### 新建产品

1. `list-programs` → 请用户选择所属项目集（`program`）  
2. 起草：`name`（必填）、`code`（可建议英文/拼音代号）、`program`、`type` 默认 `normal`、`acl` 默认 `open`  
3. 确认后写入 payload 并执行：

```bash
python3 "$SKILL/scripts/zentao.py" create-product --payload /tmp/zentao-product.json
```

4. 回报 `productId` / `url`；若处于绑定流程，继续选或新建项目

### 新建项目

1. 确认要关联的产品 id（已有或刚创建）  
2. 起草：`name`、`code`、`products: [<productId>]`、`begin`/`end`（默认今天～+90 天）、`model` 默认 `scrum`  
3. 确认后执行：

```bash
python3 "$SKILL/scripts/zentao.py" create-project --payload /tmp/zentao-project.json
```

4. 回报 `projectId` / `url`；若处于绑定流程，继续 `bind-repo`

## 意图路由

| 用户说法 | 流程 |
|----------|------|
| 新建产品 / 创建产品 | 新建产品流 |
| 新建项目 / 创建项目 | 新建项目流 |
| 创建需求 / 建研发需求 | **仅步骤 1～2**（建需求 + 评审），不要顺手建任务 |
| 完善迭代和任务 / 收工 / 补工时 | **步骤 3～6**（建迭代→关联→建任务→完成）；开工前必须已评审激活 |
| 一次做完 / 同步到禅道 | 按 1→6 全链路，每大步可合并确认，但**执行顺序不得跳步** |

## 开工流（建需求 + 评审）

1. 确保已绑定  
2. 根据对话与改动起草需求（标题、spec、验收、优先级、category 默认 `feature`；`reviewer`/`assignedTo` 默认本人）  
3. 展示【禅道待确认】摘要，等待确认  
4. 创建需求：

```bash
python3 "$SKILL/scripts/zentao.py" create-story --payload /tmp/zentao-story.json --cwd "<workspace>"
```

5. 立刻评审/激活（仍需先确认，除非用户已说「创建并评审」）：

```bash
python3 "$SKILL/scripts/zentao.py" review-story --id <storyId>
python3 "$SKILL/scripts/zentao.py" get-story --id <storyId>
```

6. 若 `readyForExecution` 不为 true：停下来，请用户在禅道 UI 评审通过后再继续；**不要**跳过直接建迭代/任务  
7. 把 `storyId` / `url` / 当前 `status` 告诉用户  

> 开工流到「已激活」为止。迭代与任务留给收工流，或用户明确要求全链路时再继续。

## 收工流（建迭代 → 关联 → 建任务 → 完成）

1. 定位需求：用户指定 ID → 绑定里的 `lastStoryId` → 再询问  
2. **先** `get-story`：必须 `status=active`。若是 `changed`/未评审，先走评审，禁止继续  
3. 确定执行：绑定值 / 用户指定 / `list-executions` 选择；没有则 **create-execution**（不要在未激活需求上建任务）  
4. 结合 git diff / 会话拆 1～N 条开发任务；`type` 默认 `devel`；`assignedTo` 默认配置 `account`  
5. **工时**：按熟悉代码库 + AI 辅助的偏高效率估算（明显短于纯人工；单任务常见 0.5～4h；用户给定工时时以用户为准）  
6. 展示整包摘要（迭代、关联、任务、工时、完成状态），等待确认  
7. **严格按序**执行：

```bash
# 若需新建迭代
python3 "$SKILL/scripts/zentao.py" create-execution --payload /tmp/zentao-execution.json --cwd "<workspace>"

# 关联（需求必须已 active）
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>

# 建任务
python3 "$SKILL/scripts/zentao.py" create-tasks --payload /tmp/zentao-tasks.json

# 完成任务（不要改需求正文）
python3 "$SKILL/scripts/zentao.py" update-status --type task --id <id> --status done
```

8. 需求阶段如需标记研发完毕，仅更新 `stage`（保持 `status=active`），**禁止**再改 `title`/`spec`/`verify`：

```bash
python3 "$SKILL/scripts/zentao.py" update-status --type story --id <id> --status active --stage developed
```

任务 payload 形状见 [reference.md](reference.md)。部分失败时报告已成功 ID，只重试失败项；**不要**为了重试而去改已评审需求的正文。

## 确认摘要模板

```text
【禅道待确认】
类型：新建产品 | 新建项目 | 开工(建需求+评审) | 收工(迭代→关联→任务→完成) | 全链路
当前顺序步骤：1建需求 / 2评审 / 3建迭代 / 4关联 / 5建任务 / 6完成
仓库：...
产品：name (#id)
项目：name (#id)
需求：新建「标题」| 已有 #id | status=...
执行/迭代：新建「…」| 已有 #id | 无
任务：
  - 标题A | 预计 1.0h | devel
状态计划：需求保持 active；任务→done；阶段→developed（如需要）
风险：若顺序错或改需求正文 → 会变成 changed，需重新评审
请回复确认 / 修改意见
```

## CLI 速查

```bash
python3 "$SKILL/scripts/zentao.py" auth
python3 "$SKILL/scripts/zentao.py" list-programs
python3 "$SKILL/scripts/zentao.py" list-products
python3 "$SKILL/scripts/zentao.py" list-projects --product <id>
python3 "$SKILL/scripts/zentao.py" list-executions --project <id>
python3 "$SKILL/scripts/zentao.py" show-repo --cwd "<path>"
python3 "$SKILL/scripts/zentao.py" bind-repo --cwd "<path>" --product <id> --project <id> [--execution <id>]
python3 "$SKILL/scripts/zentao.py" create-product --payload <file>
python3 "$SKILL/scripts/zentao.py" create-project --payload <file>
python3 "$SKILL/scripts/zentao.py" create-story --payload <file> [--cwd "<path>"]
python3 "$SKILL/scripts/zentao.py" get-story --id <id>
python3 "$SKILL/scripts/zentao.py" review-story --id <id> [--assigned-to <account>] [--comment <text>]
python3 "$SKILL/scripts/zentao.py" create-execution --payload <file> [--cwd "<path>"]
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>
python3 "$SKILL/scripts/zentao.py" create-tasks --payload <file>
python3 "$SKILL/scripts/zentao.py" update-status --type story|task --id <id> --status <name> [--stage <stage>]
```

stdout 为 JSON；错误在 stderr，非零退出。

## 失败处理

- 缺配置 / 认证失败：停，指导补配置；勿把密码写进仓库或 Skill  
- 列表空 / 403：说明权限，允许用户直接给 id 兜底  
- 新建产品缺项目集 / 新建项目缺关联产品：先补列表选择，再创建  
- `review-story` 失败：明确告知需 UI 人工评审；**阻塞**后续建迭代/任务直到 `get-story` 显示 active  
- `status=changed`：停止后续写操作，先重新评审  
- 状态名不匹配：展示原始错误，请用户给正确值并建议写回 `statusMap`  
- 关联执行接口不可用：告知需 UI 手动关联；仅在需求已 active 时可继续建任务（若实例允许）  

## 非目标

不处理 Bug/测试单/发布；不在未确认时静默创建；不在评审后擅自改需求正文；不把凭证写入环境变量或项目仓库。
