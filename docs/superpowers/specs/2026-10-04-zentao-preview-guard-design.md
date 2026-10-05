# 禅道预览、工时与仓库边界

日期：2026-10-04  
状态：已确认  
范围：个人 Skill `zentao-dev-workflow`

本规格替换 2026-08-10 设计里的工时原则和确认摘要。需求生命周期顺序不变：建需求 → 评审激活 → 建迭代 → 关联需求 → 建任务 → 完成任务。评审后仍禁止改需求标题、描述、验收。

## 1. 要解决的问题

| 问题 | 规格里的对应 |
|---|---|
| 不知道任务从哪来、工时怎么算、标题怎么写 | 预览里写明这三句；还不能预览时先在对话里说明 |
| 工时普遍偏短 | 按代码量和难度，以对应角色的资深工程师估算；取消 AI 提速折扣 |
| 会改到别人创建的任务 | 可读别人的任务；只能新建，或修改 `openedBy` 为当前账号的任务 |
| 写入前不放心 | 用 Canvas 预览，对话里确认后才调用写接口 |
| 会窜到其他 git 仓库 | 先锁定本次会话点名的仓库；预览展示 git 根目录和远程；不一致就停 |

## 2. 优先级与可调整层

三层，从高到低：

1. **当次口头指令**：这次说的工时、标题、仓库、任务 ID，压过配置和默认。
2. **本机配置** `~/.config/zentao/config.json` 的 `policy`：口径不合适时改这里。Agent 指出对应的键和改法，不在对话里偷偷换规则。用户要求长期生效时，才写回该文件。
3. **技能默认**：`policy` 缺哪项，用下表。

| 键 | 默认 | 作用 |
|---|---|---|
| `hourMethod` | `senior_by_volume_and_difficulty` | 按代码量 + 难度，用该任务类型的资深角色估工时 |
| `titleStyle` | `verb_result` | 动词开头的结果句 |
| `allowReadOthersTasks` | `true` | 可读别人的任务，避免重复建 |
| `allowModifyOthersTasks` | `false` | 禁止改别人建的任务 |
| `requirePreview` | `true` | 写操作前必须先预览；为 `true` 时还要等用户确认 |
| `previewSurface` | `canvas` | `canvas` 或 `text` |
| `repoLock` | `session_git_root` | 锁定本次会话点名的仓库，并核对 git 根目录与远程 |
| `assignToSelf` | `true` | 新建任务只指派给当前账号 |
| `titleStyleNote` | 空 | `titleStyle` 不是 `verb_result` 时，用这段文字作为标题写法；为空则先问用户 |

`assignToSelf` 从 `defaults` 挪到 `policy`。`defaults` 里若仍有该键，忽略。`defaults.hourBias` 不再作为估算依据，配置里残留也忽略。`config.example.json` 给出完整 `policy`，不再写 `high_efficiency`。

`hourMethod`、`titleStyle` 出现上表以外的值时，先问用户口径，不把默认算法套上去假装认识。

二次开发入口：

- 调口径：本机 `policy`，模板在 `config.example.json`
- 调预览文案：只改 `SKILL.md` 里的说明句，说明句读 `policy`，不把规则再抄一份
- 调预览版面：只改 `templates/zentao-preview.canvas.tsx`
- 调拦截：只改 `scripts/zentao.py` 的 `load_policy`、`assert_git_root`、`assert_task_owner`、`assert_assign_self`

## 3. 使用说明

下面三句写在预览里，口径跟着当前生效的 `policy`。还不能预览时（尚未选定仓库或产品），在对话里先说这三句，并且不调用写接口。一旦可以预览，这三句只出现在预览里，对话里不另贴一份：

- **任务从哪来**：只根据本次锁定仓库的 git diff 和这次对话拆新任务。可以先读迭代里已有任务用来去重。不从别人的任务里挑一条来改。
- **工时怎么算**：看代码量和难度，按这条任务类型的资深角色估（开发、测试、设计等）。预览里逐条写出代码量、难度、角色和小时数。用户当次给的数字优先。不按 AI 提速压到 0.5～4 小时。
- **标题怎么写**：`titleStyle=verb_result` 时，动词开头，写清做完是什么，例如「实现订单按日期导出 Excel」。不写对话里的方案代号。其他取值使用 `titleStyleNote`。

## 4. 预览

每次创建、修改、关联、完成之前先出预览。

- `requirePreview=true`：出预览后停住，用户在**当前对话**回复确认后才调用写接口。
- `requirePreview=false`：仍出同一份预览，第一行标明「配置已关闭确认，将直接写入」。
- 用户改了预览内容：按修改后的内容重出预览，再等一次确认。
- 会话里有多个仓库：先问用哪一个，再出预览。
- 仓库根目录和本次点名的仓库不一致：只展示仓库核对结果并停下，不列出将新建的任务，不调用写接口。
- 没有 `origin`：可以列出任务草稿，顶部标明无远程。用户确认这条路径之前不写。

预览必须含这些内容；某一类没有数据时，Canvas 不渲染空块：

- git 根目录、`origin`、产品、项目、需求（id、标题、status）、迭代
- 三句使用说明
- 将新建：标题、类型与角色、代码量、难度、预计小时、指派账号、完成后是否标记完成
- 将修改：仅 `openedBy` 为当前账号的任务；任务 id、原标题、改什么、原工时到新工时
- 只读：别人的任务（id、标题、创建人），默认折起来
- 预计总工时、新建条数、将修改条数
- 确认前不会写入

Canvas 预览时，对话里只留文件链接和「请回复确认或修改意见」。文本预览时，对话里就是这一份，不再复制第二份。

### 4.1 Canvas

`previewSurface=canvas` 时，主界面是 Canvas，放在对话旁边。

- 文件固定为当前会话工作区对应的 `canvases/zentao-preview.canvas.tsx`，每次覆盖。
- 不写入业务 git 仓库，不写入其他项目的 Canvas 目录。
- 数据嵌在文件里，不发网络请求。
- Canvas 不能调用禅道接口，上面不放写入按钮，也不要为此新开对话。
- 颜色用宿主主题。版面用 `cursor/canvas` 的 `H1`、`Stat`、`Table`、`Callout`、`CollapsibleSection`。仓库不一致时顶部用警告。
- 技能内的版面源文件是 `templates/zentao-preview.canvas.tsx`。Agent 填入当次数据后，写到会话 Canvas 路径。

`previewSurface=text`，或当前环境写不出 Canvas 时，退回文本预览，字段与上面相同。写不出 Canvas 时要标明「Canvas 不可用」。确认门槛不因退回文本而取消。

密码和 Token 不进入 Canvas，也不进入仓库。

## 5. 工时与标题

工时输入是这次改动的代码量（涉及模块、大约文件数，不堆行数）和难度（新逻辑还是机械修改、是否跨模块、风险和未知点）。角色跟着任务类型：`devel` 按资深开发，`test` 按资深测试，`design` 按资深设计，其余类型用该类型的资深执行者。

CLI 不改写小时数，也不设最低工时。用户当次给出的数字优先，预览里仍保留代码量和难度，方便对照。

标题按生效的 `titleStyle` 生成。默认是动词开头的结果句。

## 6. 任务归属

- 新建任务的 `assignedTo` 在 `assignToSelf=true` 时固定为配置里的 `account`。payload 写成别人则拒绝。
- 修改指：改状态、工时或标题。只允许 `openedBy` 等于当前账号。
- `allowModifyOthersTasks=false` 时，不改别人任务的状态、工时、标题、指派，也不把别人的任务标记完成。禁止先改派给自己再写。
- `allowReadOthersTasks=false` 时，`list-tasks` 只返回自己建的任务。
- `openedBy` 可能是账号字符串，或带 `account` 的对象。两种都要识别。解析不出时，该条只读，不修改。

「自己的任务」只认 `openedBy`，不认 `assignedTo`。

## 7. 仓库边界

Agent 先锁定本次会话里用户点名的那个业务仓库。点名的路径若在某个 git 仓库内，锁定值取该仓库的 git 根目录。

然后调用 `inspect-repo --cwd <git 根目录>`。预览里的根目录和远程以这条命令的输出为准，不手写。

- `--cwd` 必须已经是 git 根目录。传入子目录时命令失败，并返回真实根目录和远程。Agent 用返回的根目录问用户，不自行改到另一个仓库。
- 没有 `origin` 时，预览标明无远程。用户确认路径之前不写。
- 建任务、改任务时，这个根目录必须等于 `repos` 里该仓库的绑定路径。未绑定则拒绝，先走绑定。绑定前同样要预览。
- 绑定路径一律保存为 git 根目录。旧配置若绑在子目录上，`inspect-repo` 报告「绑定路径不是 git 根目录」，请用户重新绑定，不自动改写配置。

## 8. CLI

新增：

| 命令 | 作用 |
|---|---|
| `show-policy` | 打印合并默认值之后的 `policy`，并标出哪些键来自默认值 |
| `inspect-repo --cwd` | 返回 git 根目录、`origin`、当前分支、是否已绑定、绑定路径是否就是该根目录 |
| `list-tasks --execution` | 返回任务 id、标题、`openedBy`、指派、工时、状态 |

以下写操作必须带 `--cwd`：`bind-repo`、`create-story`、`create-execution`、`create-tasks`、任务的 `update-status`。

任务的 `update-status` 增加可选 `--name`、`--estimate`，用来修改自己的标题和工时。需求的 `update-status` 仍只接受 `status` 和 `stage`，不接受标题、描述、验收、工时。

改任务前先读取该任务，再进入 `assert_task_owner`。新建任务进入指派校验，不走 `openedBy` 校验。

`requirePreview` 由 Agent 执行。脚本不伪造「用户已确认」。

校验只放在 `load_policy`、`assert_git_root`、`assert_task_owner`、`assert_assign_self`。

## 9. 失败行为

脚本失败时说明原因，以及可以改的配置键。不自动换仓库，不改派，不改到别人的任务上重试。

| 情况 | 结果 |
|---|---|
| `--cwd` 不是 git 根目录 | 非零退出，返回真实根目录和远程 |
| 仓库未绑定 | 建任务、改任务拒绝 |
| 没有 `origin` | 预览标明无远程，确认路径前不写 |
| `openedBy` 不是当前账号 | 拒绝，返回任务 id 和创建人 |
| 创建人字段解析不出 | 该条只读 |
| Canvas 写不出 | 文本预览，并标明 Canvas 不可用 |
| `policy` 缺字段 | 用第 2 节的默认补上，`show-policy` 标出来源 |
| 批量建任务部分失败 | 报告已成功的 id，只重试失败项；内容有变化则重新预览 |

沿用现有失败处理：缺配置、认证失败、评审未激活、`status=changed` 时停止后续写操作。

## 10. 验收

- 单元测试覆盖 `load_policy`、`assert_git_root`、`assert_task_owner`、`assert_assign_self`，不访问真实禅道。
- 别人的任务、子目录路径、未绑定仓库，对应写命令非零退出。
- 预览能单独看懂仓库、工时依据，以及将要新建或修改的任务。
- `SKILL.md`、`README.md`、`reference.md` 不再指示「按 AI 提速估算」或「单任务常见 0.5～4 小时」。README 只保留怎么进入流程，不重复工时算法。

## 11. 改动文件

- `SKILL.md`
- `README.md`
- `reference.md`
- `config.example.json`
- `scripts/zentao.py`
- 新增 `templates/zentao-preview.canvas.tsx`
- 新增 `scripts/test_guards.py`

不处理 Bug、测试单、发布。不在未确认时静默创建（`requirePreview=false` 除外，且预览仍要输出）。不把凭证写入环境变量或项目仓库。
