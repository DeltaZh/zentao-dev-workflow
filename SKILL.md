---
name: zentao-dev-workflow
description: 通过禅道 REST API 为当前改动创建研发需求与开发任务、关联执行/迭代、填写偏高效率预计工时并更新状态。在用户提到禅道、创建需求、开发任务、收工补任务/工时、绑定产品项目，或要求把某次改动同步到禅道时使用。
---

# 禅道开发工作流

用个人配置调用本 Skill 自带 CLI，把 Cursor 中的改动同步为禅道需求/任务。  
**任何写操作（创建、改状态、关联）之前，必须先给出摘要并得到用户确认。**

## 路径

- Skill 根目录：本文件所在目录（下称 `$SKILL`）
- CLI：`python3 "$SKILL/scripts/zentao.py"`
- 配置：`~/.config/zentao/config.json`（模板见 `$SKILL/config.example.json`）
- 字段与 API 细节：[reference.md](reference.md)

## 前置检查

1. 若配置不存在：指导用户复制 `config.example.json` → `~/.config/zentao/config.json`，填 `baseUrl` / `account` / `password`，权限建议 `chmod 600`
2. 运行 `python3 "$SKILL/scripts/zentao.py" auth` 验证登录
3. `python3 "$SKILL/scripts/zentao.py" show-repo --cwd "<workspace>"` 检查是否已绑定

## 仓库绑定（首次）

未绑定则**拉列表请用户选择 id**，禁止只靠手输名称模糊匹配。

1. `list-products` → 展示 `id + name`，请用户选产品  
2. `list-projects --product <id>` → 展示项目列表请用户选（若有 warning 说明无法按产品过滤，请用户按名称核对）  
3. 可选：`list-executions --project <id>` → 选默认迭代；可跳过，收工时再选  
4. `bind-repo --cwd "<workspace>" --product <id> --project <id> [--execution <id>]`  
5. 当次换产品不改绑定；用户说「换绑 / 以后都用这个」才重新 bind

## 意图路由

| 用户说法 | 流程 |
|----------|------|
| 创建需求 / 建研发需求 | 开工流 |
| 完善迭代和任务 / 收工 / 补工时 | 收工流 |
| 两者都提 | 拆成两步确认，或先澄清主意图 |

## 开工流（建需求）

1. 确保已绑定  
2. 根据对话与改动起草需求（标题、spec、验收、优先级、category，默认 `feature`）  
3. 展示【禅道待确认】摘要，等待确认  
4. 将 payload 写入临时 JSON，执行：

```bash
python3 "$SKILL/scripts/zentao.py" create-story --payload /tmp/zentao-story.json --cwd "<workspace>"
```

5. 把返回的 `storyId` / `url` 告诉用户（CLI 会更新该仓库 `lastStoryId`）  
6. 若配置 `statusMap.storyAfterCreate` 存在，再确认后 `update-status --type story --id <id> --status <status>`

## 收工流（迭代 + 任务 + 工时 + 状态）

1. 定位需求：用户指定 ID → 绑定里的 `lastStoryId` → 再询问  
2. 确定执行：绑定值 / 用户指定 / `list-executions` 选择  
3. 结合 git diff / 会话拆 1～N 条开发任务；`type` 默认 `devel`；`assignedTo` 默认配置账号  
4. **工时**：按熟悉代码库 + AI 辅助的偏高效率估算（明显短于纯人工；单任务常见 0.5～4h；用户给定工时时以用户为准）  
5. 展示整包摘要，等待确认  
6. 依次执行（每步用 CLI；关联失败见命令输出 `skipped` 时可说明并继续）：

```bash
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>
python3 "$SKILL/scripts/zentao.py" create-tasks --payload /tmp/zentao-tasks.json
python3 "$SKILL/scripts/zentao.py" update-status --type task --id <id> --status done
python3 "$SKILL/scripts/zentao.py" update-status --type story --id <id> --status active --stage developed
```

任务 payload 形状见 [reference.md](reference.md)。部分失败时报告已成功 ID，只重试失败项。

## 确认摘要模板

```text
【禅道待确认】
类型：开工建需求 | 收工完善
仓库：...
产品：name (#id)
项目：name (#id)
执行/迭代：name (#id) | 无
需求：新建「标题」| 已有 #id
任务：
  - 标题A | 预计 1.0h | devel
  - 标题B | 预计 0.5h | devel
状态计划：...
请回复确认 / 修改意见
```

## CLI 速查

```bash
python3 "$SKILL/scripts/zentao.py" auth
python3 "$SKILL/scripts/zentao.py" list-products
python3 "$SKILL/scripts/zentao.py" list-projects --product <id>
python3 "$SKILL/scripts/zentao.py" list-executions --project <id>
python3 "$SKILL/scripts/zentao.py" show-repo --cwd "<path>"
python3 "$SKILL/scripts/zentao.py" bind-repo --cwd "<path>" --product <id> --project <id> [--execution <id>]
python3 "$SKILL/scripts/zentao.py" create-story --payload <file> [--cwd "<path>"]
python3 "$SKILL/scripts/zentao.py" create-tasks --payload <file>
python3 "$SKILL/scripts/zentao.py" update-status --type story|task --id <id> --status <name> [--stage <stage>]
python3 "$SKILL/scripts/zentao.py" link-story-execution --story <id> --execution <id>
```

stdout 为 JSON；错误在 stderr，非零退出。

## 失败处理

- 缺配置 / 认证失败：停，指导补配置；勿把密码写进仓库或 Skill  
- 列表空 / 403：说明权限，允许用户直接给 id 兜底  
- 状态名不匹配：展示原始错误，请用户给正确值并建议写回 `statusMap`  
- 关联执行接口不可用：告知需 UI 手动关联，不阻断建任务  

## 非目标

不自动建产品/项目；不处理 Bug/测试单/发布；不把凭证写入环境变量或项目仓库。
