---
name: zentao-dev-workflow
description: 通过禅道 REST API 按固定顺序新建产品/项目、创建并评审需求、创建迭代、关联需求、创建并完成开发任务。在用户提到禅道、新建产品、新建项目、创建需求、评审需求、建迭代、开发任务、收工补任务/工时、绑定产品项目，或要求把某次改动同步到禅道时使用。也在工时偏短、写入前要预览、误改他人任务、窜到其他 git 仓库、补历史任务的实际开始/实际完成/由谁完成时使用。
---

# 禅道开发工作流

用个人配置调用本 Skill 自带 CLI，把 Cursor 中的改动同步为禅道需求/任务。  
**任何写操作之前，必须先出预览。** `requirePreview` 为 true 时，用户在当前对话确认后才调用写接口。

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

1. **人员一律当前登录用户**：需求/任务的负责人、指派给、开发（以及激活评审人 `reviewer`）默认都用配置里的 `account`。`policy.assignToSelf` 为 true 时，新建任务只能指派给该账号；用户当次要改派给别人，先说明需把该键改为 false，确认后再写。禁止先改派再改别人的任务。
2. **项目/执行状态由用户管**：用户在禅道 UI 里改的项目状态（如「已开始」）以用户为准；Agent **不要**主动改项目/迭代的 `status`（`wait`/`doing`/`closed` 等），除非用户当次要求。
3. **文案直白、禁止讨论代号**：需求标题/描述/验收、任务名称/描述里，**不要**写「方案 A/B」「策略 D」「硬门槛 A/B/C」「风控 B1」等仅在对话里出现的代号；要写成普通人能看懂的「是什么 + 为什么 + 怎么验收」。技术名词（Sidecar、Cookie）可保留，但必须有中文说明。

## 生效口径

写操作前先跑 `show-policy`。优先级：用户当次口头指令 > `policy` > 技能默认。不认识的 `hourMethod` 或 `titleStyle`（`titleStyleNeedsAsk=true`）先问用户，不要套默认算法。`defaults.hourBias` 和 `defaults.assignToSelf` 忽略。

工时按代码量（模块、大约文件数）和难度（新逻辑还是机械修改、是否跨模块、风险），用该任务类型的资深角色估算：`devel` 资深开发，`test` 资深测试，`design` 资深设计，其余类型用该类型的资深执行者。用户当次给出的数字优先。CLI 不改小时数。标题默认是动词开头的结果句，例如「实现订单按日期导出 Excel」。

三句说明写在预览里：任务只从本次锁定仓库的 git diff 和这次对话拆出；工时看代码量和难度；标题按当前 `titleStyle` / `titleStyleNote`。还不能预览时（仓库或产品未定），在对话里先说这三句，并且不调用写接口。

## 仓库锁定

1. 会话里有多个仓库时，先问用哪一个。锁定用户点名的业务仓库的 **git 根目录**。
2. `inspect-repo --cwd <git 根目录>` 的 `gitRoot` 和 `remote` 是预览里的仓库信息，不要手写。
3. 根目录和点名仓库不一致：只展示核对结果并停下，不列出将新建的任务，不调用写接口。
4. `remote` 为空：可以列出任务草稿，顶部标明无远程。用户确认这条路径之前不写。
5. `bind-repo`、`create-story`、`create-execution`、`create-tasks`、任务 `update-status` 的 `--cwd` 必须已经是这个 git 根目录。
6. 建任务、改任务还要求该根目录已绑定。绑定路径不是 git 根目录时，请用户重新绑定，不要改写配置。
7. git diff / status 只在这个根目录里跑。改动若在别的仓库，停下来问，不要跟着窜过去。

## 任务归属

- 可读别人的任务（`list-tasks`）用来去重。`allowReadOthersTasks=false` 时列表只有自己建的。
- 只能新建任务，或修改 `openedBy` 等于当前账号的任务（状态、标题、工时）。不认 `assignedTo`。
- 创建人解析不出：该条只读。禁止改派给自己再写。

## 预览

`previewSurface=canvas` 时，把 `$SKILL/templates/zentao-preview.canvas.tsx` 里的 `PREVIEW` 换成当次数据，覆盖写入当前会话的 `canvases/zentao-preview.canvas.tsx`。不写进业务 git 仓库，不写进别的项目。数据嵌在文件里。Canvas 上不放写入按钮，也不要为此新开对话。对话里只留该文件的绝对路径链接，以及「请回复确认或修改意见」。

空数组不要渲染对应区块。仓库不一致时只留警告。密码和 Token 不进 Canvas。

`previewSurface=text`，或 Canvas 写不出时，用下面的文本预览，并在写不出时标明「Canvas 不可用」。确认门槛不变。`requirePreview=false` 时仍出同一份预览，第一行写「配置已关闭确认，将直接写入」。用户改了内容就重出预览，再等一次确认。

文本预览字段：

```text
【禅道预览】
仓库：<git 根目录>
远程：<origin，没有则写无远程>
绑定：产品 名称 (#id) / 项目 名称 (#id)
需求：#id 「标题」 status=...
迭代：#id 「名称」 | 新建「名称」
说明：任务从本次锁定仓库的 diff 和这次对话拆出；工时按代码量和难度，由该类型资深角色估算；标题为动词开头的结果句
将新建：
  1. 实现订单按日期导出 Excel | devel | 资深开发 | 代码量 | 难度 | 6h | 指派账号 | 完成后标记完成或保持未完成
将修改（仅自己建的）：
  - #任务id 原标题 | 改什么 | 原工时 → 新工时
只读、不改：
  - #任务id 标题 | 创建人
请回复确认 / 修改意见
```

## 前置检查

1. 若配置不存在：指导用户复制 `config.example.json` → `~/.config/zentao/config.json`，填 `baseUrl` / `account` / `password`，权限建议 `chmod 600`
2. 运行 `python3 "$SKILL/scripts/zentao.py" auth` 验证登录
3. `python3 "$SKILL/scripts/zentao.py" show-policy` 读取口径
4. `python3 "$SKILL/scripts/zentao.py" inspect-repo --cwd "<git 根目录>"` 核对仓库。不要用子目录，也不要默认进程当前目录

## 仓库绑定（首次）

未绑定则**拉列表请用户选择 id**；列表中提供「新建」选项。禁止只靠手输名称模糊匹配。

1. `list-products` → 展示 `id + name`，请用户选产品，或选「新建产品」  
2. 若新建产品：先 `list-programs` 选项目集 → 确认摘要 → `create-product` → 用返回的 `productId`  
3. `list-projects --product <id>` → 选项目，或选「新建项目」  
4. 若新建项目：确认摘要（名称/代号/关联产品/起止日期）→ `create-project` → 用返回的 `projectId`  
5. 可选：`list-executions --project <id>` → 选默认迭代；可跳过，收工时再建/再选  
6. `bind-repo --cwd "<git 根目录>" --product <id> --project <id> [--execution <id>]`  
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
python3 "$SKILL/scripts/zentao.py" create-story --payload /tmp/zentao-story.json --cwd "<git 根目录>"
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
4. 先 `list-tasks --execution <id>` 读已有任务用来去重。只根据本次锁定仓库的 git diff 和这次对话拆 1～N 条新任务。`type` 默认 `devel`。指派只能是当前账号，除非 `assignToSelf` 已关闭且用户确认
5. **工时**：按代码量和难度，用该任务类型的资深角色估算。预览里写明代入的代码量、难度、角色和小时数。用户当次给出的数字优先。不要把工时压到低于这份估算
6. 按「预览」出 Canvas 或文本，等待确认（`requirePreview=false` 时仍要出预览）
7. **严格按序**执行，`--cwd` 使用 `inspect-repo` 返回的 git 根目录：

```bash
# 若需新建迭代
python3 "$SKILL/scripts/zentao.py" create-execution --payload /tmp/zentao-execution.json --cwd "<git 根目录>"

# 关联（需求必须已 active）
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>

# 建任务
python3 "$SKILL/scripts/zentao.py" create-tasks --payload /tmp/zentao-tasks.json --cwd "<git 根目录>"

# 完成自己的任务。补历史日期不要用这条：它按「现在往前推工时」写实际时间
python3 "$SKILL/scripts/zentao.py" update-status --type task --id <id> --status done --cwd "<git 根目录>"
```

8. 需求阶段如需标记研发完毕，仅更新 `stage`（保持 `status=active`），**禁止**再改 `title`/`spec`/`verify`：

```bash
python3 "$SKILL/scripts/zentao.py" update-status --type story --id <id> --status active --stage developed
```

任务 payload 形状见 [reference.md](reference.md)。部分失败时报告已成功 ID，只重试失败项；**不要**为了重试而去改已评审需求的正文。

## 补历史任务（实际开始 / 实际完成 / 工时）

补已经做过的任务时，预计日期和实际日期是两套字段。只写 `estStarted` / `deadline`，界面按「实际开始」筛选会少掉这些任务。标完成前先读禅道二次开发手册里的「完成任务」「启动任务」，不要靠试正式任务摸接口。

每条要补的任务必须同时有：

| 字段 | 写什么 |
|---|---|
| `estStarted` | 预计开始，保持已有日期，不要按工时改短 |
| `deadline` | 预计结束，保持已有日期 |
| `realStarted` | 实际开始 = 预计开始当天 `09:00:00`，日期与预计开始同一天 |
| `finishedDate` | 按消耗工时从实际开始往后推，不必等于预计结束 |
| `finishedBy` | 由谁完成 = 当前账号。完成接口用当前账号调用，服务端把完成人写成调用者 |
| `consumed` | 消耗必须大于 0 |

工时：1 个工作日 = 8 小时，从 09:00 起算，周日休息，周六算工作日。实际完成从实际开始按消耗往后推：当天 09:00 起算 8 小时到 17:00，超过 8 小时顺延到下一工作日 09:00 继续。不必卡在预计结束那天，晚几个小时或再延后一段都可以。新建或消耗仍为 0 时，用预计起止之间的工作日数 × 8。已有消耗不要重算，也不要为了让实际完成等于预计结束去改日期。

只改 `openedBy` 等于当前账号的任务。别人创建的，即使指派给自己、或标题像自己的工作，也只读。创建人解析不出就跳过。禁止先改派再写。条数对不上时，先按创建人拆开，不要把别人的差额当成自己漏补。

写入：

- 已是 `done`、只缺实际时间：直接 `POST /api.php/v1/tasks/{id}/finish`。不要 `start`，不要取消、关闭或重建。
- 请求体带 `assignedTo`（当前账号）、`realStarted`、`finishedDate`。消耗已经有了就传 `currentConsumed: 0`。`currentConsumed` 是本次追加，再传一遍总工时会翻倍。
- `consumed` 只能增不能减。接口报「总计消耗必须大于之前消耗」时停，不要换一条正式任务继续试。
- 时间用无时区本地时间 `YYYY-MM-DD HH:MM:SS`，不要带 `Z`。带 `Z` 会再减 8 小时，日期会掉到前一天，按实际开始筛选就会少一条。
- CLI 的 `update-status` 用「当前时间往前推工时」生成实际起止，补历史日期时不要用它。

对账按项目执行拉任务，状态要含 `closed`，默认列表没有已关闭迭代。不要用 `GET /api.php/v1/tasks` 做全量统计，它的 `page` / `limit` 不可靠。补完后分别数：预计开始落在区间里的条数、实际开始落在同一区间里的条数，只计当前账号创建的。

## 确认摘要模板

产品/项目新建等尚无任务表时，仍用这段文本，并遵守「预览」的确认规则。收工任务预览用上一节的 Canvas 或文本，不要两份一起贴。

```text
【禅道待确认】
类型：新建产品 | 新建项目 | 开工(建需求+评审) | 收工(迭代→关联→任务→完成) | 全链路
当前顺序步骤：1建需求 / 2评审 / 3建迭代 / 4关联 / 5建任务 / 6完成
仓库：<git 根目录>
远程：<origin>
产品：name (#id)
项目：name (#id)
需求：新建「标题」| 已有 #id | status=...
执行/迭代：新建「…」| 已有 #id | 无
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
python3 "$SKILL/scripts/zentao.py" show-policy
python3 "$SKILL/scripts/zentao.py" inspect-repo --cwd "<git 根目录>"
python3 "$SKILL/scripts/zentao.py" list-tasks --execution <id>
python3 "$SKILL/scripts/zentao.py" show-repo --cwd "<path>"
python3 "$SKILL/scripts/zentao.py" bind-repo --cwd "<git 根目录>" --product <id> --project <id> [--execution <id>]
python3 "$SKILL/scripts/zentao.py" create-product --payload <file>
python3 "$SKILL/scripts/zentao.py" create-project --payload <file>
python3 "$SKILL/scripts/zentao.py" create-story --payload <file> --cwd "<git 根目录>"
python3 "$SKILL/scripts/zentao.py" get-story --id <id>
python3 "$SKILL/scripts/zentao.py" review-story --id <id> [--assigned-to <account>] [--comment <text>]
python3 "$SKILL/scripts/zentao.py" create-execution --payload <file> --cwd "<git 根目录>"
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>
python3 "$SKILL/scripts/zentao.py" create-tasks --payload <file> --cwd "<git 根目录>"
python3 "$SKILL/scripts/zentao.py" update-status --type story|task --id <id> --status <name> [--stage <stage>] [--name <标题>] [--estimate <小时>] [--cwd "<git 根目录>"]
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
- `--cwd` 不是 git 根目录：使用 stderr 里的 `gitRoot` 问用户，不要改到另一个仓库
- 仓库未绑定，或绑定路径不是 git 根目录：先绑定或请用户重新绑定，不要自动改配置
- `openedBy` 不是当前账号，或创建人解析不出：跳过该任务，不要改派后再写
- 任务实际开始/完成时间不要用 PUT `/tasks/{id}`，该接口会静默丢掉 `realStarted`、`finishedDate`、`finishedBy`。未开始的任务用 `POST /tasks/{id}/start` 写实际开始；完成一律用 `POST /tasks/{id}/finish` 写实际开始和实际完成。已经 `done` 的只调 finish，不要再 start。补历史任务的日期规则见上一节，不要用 `update-status` 的「现在往前推工时」
- 迭代的 `days` / `status` 可以 PUT。`realBegan` / `realEnd` 会被静默忽略，不要当成写成功。关闭时 `closedDate` 由服务器时钟填写，可能和本机差一天
- 响应不是 JSON（常见是登录页 HTML 且 HTTP 200）或 502：清 token 再取，按 `authBackoffSeconds` 退避重试，次数见 `authRetries`。批量写任务之间停 `writeIntervalSeconds`（默认 0.35 秒）
- 批量建任务部分失败：只报告已成功的 id，只重试失败项；内容有变化则重新预览

## 非目标

不处理 Bug/测试单/发布；不在未确认时静默创建（`requirePreview=false` 时仍要输出预览）；不在评审后擅自改需求正文；不把凭证写入环境变量、项目仓库或 Canvas。
