# zentao-dev-workflow

Cursor Agent Skill：把当前改动同步到禅道（ZenTao）——支持新建产品/项目、创建研发需求与开发任务、关联执行/迭代、填写偏高效率预计工时并更新状态。

写操作默认**先展示摘要，经你确认后再调用接口**，避免误建。

## 功能一览

| 能力 | 说明 |
|------|------|
| 仓库绑定 | 首次使用时拉取产品/项目列表供选择，写入本机配置 |
| 新建产品 | 先选项目集，再创建产品 |
| 新建项目 | 关联已有产品后创建项目 |
| 开工建需求 | 根据对话/改动起草需求并创建 |
| 收工补任务 | 关联迭代、拆任务、填预计工时、推进状态 |
| 确认门禁 | 创建/改状态前必须用户确认 |

## 环境要求

- [Cursor](https://cursor.com/)（Agent 模式）
- Python 3（仅标准库，无需 `pip install`）
- 可访问的禅道实例，且账号具备 REST 开放接口权限（开源版约 16.5+ 常见）
- macOS / Linux（脚本按 POSIX 路径编写）

## 安装

### 方式 A：个人全局 Skill（推荐）

对所有本地项目可用：

```bash
git clone https://github.com/DeltaZh/zentao-dev-workflow.git ~/.cursor/skills/zentao-dev-workflow
```

若目录已存在，改为进入后 `git pull`。

### 方式 B：放进某个业务仓库

仅该仓库协作者可用：

```bash
mkdir -p .cursor/skills
git clone https://github.com/DeltaZh/zentao-dev-workflow.git .cursor/skills/zentao-dev-workflow
```

然后把 `.cursor/skills/zentao-dev-workflow` 按需提交到业务仓库，或使用 submodule。

> 安装完成后如 Cursor 未立即识别，可重开 Agent 对话或重启 Cursor。

## 配置（每人私有，勿提交）

凭证与仓库绑定**只存在本机**，路径：

```text
~/.config/zentao/config.json
```

### 1. 从模板创建

```bash
mkdir -p ~/.config/zentao
cp ~/.cursor/skills/zentao-dev-workflow/config.example.json ~/.config/zentao/config.json
chmod 600 ~/.config/zentao/config.json
```

### 2. 编辑必填项

用编辑器打开 `~/.config/zentao/config.json`，填写：

| 字段 | 含义 |
|------|------|
| `baseUrl` | 你们公司的禅道根地址（不要带无关路径） |
| `account` | 你的禅道账号 |
| `password` | 你的禅道密码 |

可选：`defaults`、`statusMap`（状态名以你们实例为准）、`repos`（由 Skill 自动维护，一般不必手改）。

### 3. 验证登录

```bash
python3 ~/.cursor/skills/zentao-dev-workflow/scripts/zentao.py auth
python3 ~/.cursor/skills/zentao-dev-workflow/scripts/zentao.py list-products
```

成功会输出 JSON（含产品列表）。失败时根据 stderr 检查地址、账号密码或接口权限。

### 配置示例（占位符，非真实环境）

仓库内 `config.example.json` 仅为结构示意：

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
  "repos": {}
}
```

**禁止**把真实 `baseUrl`、账号、密码写进本仓库的任何文件或提交。

## 在 Cursor 里怎么用

在 Agent 对话中直接说意图即可，例如：

- 「用禅道 Skill，给当前仓库绑定产品/项目」
- 「新建一个禅道产品 / 项目」
- 「为这次改动创建一个禅道需求」
- 「功能做完了，完善开发迭代、任务和工时」

典型流程：

1. **首次绑定**：Agent 列出产品 → 你选择（或新建）→ 再列项目 → 选择（或新建）→ 写入本机 `repos`
2. **开工**：Agent 起草需求摘要 → 你确认 → 调用接口创建 → 返回需求 ID/链接
3. **收工**：Agent 起草任务拆分与偏高效率工时 → 你确认 → 创建任务并尝试更新状态

### 工时原则

按「熟悉代码库 + AI 辅助」估算，通常明显短于纯人工；你若直接给出工时，以你的为准。

## CLI 速查

Skill 根目录下（或使用绝对路径）：

```bash
python3 scripts/zentao.py auth
python3 scripts/zentao.py list-programs
python3 scripts/zentao.py list-products
python3 scripts/zentao.py list-projects --product <id>
python3 scripts/zentao.py list-executions --project <id>
python3 scripts/zentao.py show-repo --cwd "<workspace>"
python3 scripts/zentao.py bind-repo --cwd "<workspace>" --product <id> --project <id> [--execution <id>]
python3 scripts/zentao.py create-product --payload <file.json>
python3 scripts/zentao.py create-project --payload <file.json>
python3 scripts/zentao.py create-story --payload <file.json> [--cwd "<workspace>"]
python3 scripts/zentao.py create-tasks --payload <file.json>
python3 scripts/zentao.py update-status --type story|task --id <id> --status <name> [--stage <stage>]
python3 scripts/zentao.py link-story-execution --story <id> --execution <id>
```

- 成功：stdout 输出 JSON  
- 失败：stderr 说明原因，进程非零退出  
- 可用环境变量 `ZENTAO_CONFIG` 覆盖配置文件路径  

Payload 字段说明见 [reference.md](reference.md)。

## 目录结构

```text
zentao-dev-workflow/
├── SKILL.md                 # Agent 主说明（触发条件与流程）
├── reference.md             # API 字段与状态参考
├── config.example.json      # 配置模板（仅占位符）
├── scripts/zentao.py        # REST CLI
├── README.md
└── docs/                    # 设计与实现计划
```

## 安全须知

1. **真实配置只放** `~/.config/zentao/config.json`，权限建议 `600`
2. **不要**把公司禅道地址、账号、密码、Token 写进 README、Issue、PR、截图或本仓库文件
3. 仓库 `.gitignore` 已忽略常见本地泄漏文件；推送前可用下面命令自检
4. Token 缓存默认在 `~/.config/zentao/token-cache.json`，同样不要提交
5. 若曾误提交密钥：立刻轮换密码，并清理 git 历史后再推送

### 推送前自检（推荐）

在仓库根目录执行（把可疑关键词换成你环境里的真实片段做反查）：

```bash
# 工作区：不应出现真实禅道域名/密码
rg -n -i 'password|token|chandao|zentao\.' --glob '!.git/**' .

# 确认示例配置仍是占位符
python3 -c "import json;d=json.load(open('config.example.json'));assert d['baseUrl'].endswith('example.com');assert d['password']=='your_password'"
```

## 常见问题

**Q: `缺少配置文件`**  
按上文复制 `config.example.json` 到 `~/.config/zentao/config.json` 并填写。

**Q: 401 / 认证失败**  
检查 `baseUrl`、账号密码；确认实例已开启 REST（`/api.php/v1/tokens`）。

**Q: 列表为空或 403**  
账号缺少产品/项目查看权限，请管理员开通。

**Q: 创建产品提示缺 program**  
先 `list-programs` 选择所属项目集 id。

**Q: 状态更新失败**  
公司实例状态枚举可能不同；以接口报错为准，校准后写入配置 `statusMap`。

**Q: 关联执行失败（skipped）**  
部分版本无统一关联接口；可在禅道 UI 手动关联需求与执行，不影响建任务。

## 文档

- [设计规格](docs/2026-08-10-zentao-dev-workflow-design.md)
- [实现计划](docs/superpowers/plans/2026-08-10-zentao-dev-workflow.md)
- [Agent 流程（SKILL.md）](SKILL.md)
- [API 参考（reference.md）](reference.md)
- 官方 REST 入门：[配置使用与常见问题](https://www.zentao.net/book/api/1397.html)

## 许可证

未另行声明时，仅供团队内部使用与改进。对外开源前请自行补充 LICENSE，并再次确认无任何公司内网地址与账号信息。
