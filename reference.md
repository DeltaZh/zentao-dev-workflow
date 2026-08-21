# 禅道 API 与字段参考

Skill 主流程见 [SKILL.md](SKILL.md)。本文件供实现细节查阅。

## 配置

- 路径：`~/.config/zentao/config.json`（可用环境变量 `ZENTAO_CONFIG` 覆盖）
- Token 缓存：`~/.config/zentao/token-cache.json`（`ZENTAO_TOKEN_CACHE` 可覆盖）
- 模板：仓库内 `config.example.json`

## REST 约定

- Base：`{baseUrl}/api.php/v1`
- 认证：`POST /tokens` → Header `Token`
- 文档入口：[配置使用与常见问题](https://www.zentao.net/book/api/1397.html)

## 常用接口

| 用途 | 方法 | 路径 |
|------|------|------|
| 获取 Token | POST | `/api.php/v1/tokens` |
| 项目集列表 | GET | `/api.php/v1/programs` |
| 产品列表 | GET | `/api.php/v1/products` |
| 创建产品 | POST | `/api.php/v1/products` |
| 项目列表 | GET | `/api.php/v1/projects` |
| 创建项目 | POST | `/api.php/v1/projects` |
| 执行列表 | GET | `/api.php/v1/projects/{id}/executions` |
| 创建执行 | POST | `/api.php/v1/projects/{id}/executions` |
| 创建需求 | POST | `/api.php/v1/stories` |
| 获取需求 | GET | `/api.php/v1/stories/{id}` |
| 激活需求 | PUT/POST | `/api.php/v1|v2/stories/{id}/activate`（实例差异大） |
| 关联需求到执行 | POST | `/api.php/v1/executions/{id}/stories` 等（多路径尝试） |
| 创建任务 | POST | `/api.php/v1/executions/{id}/tasks` |
| 更新需求 | PUT | `/api.php/v1/stories/{id}` |
| 更新任务 | PUT | `/api.php/v1/tasks/{id}` |

## 强制生命周期顺序

1. 建需求 → 2. 评审激活 → 3. 建迭代 → 4. 关联需求 → 5. 建任务 → 6. 完成任务  

评审后若再改需求正文，状态常变为 `changed`，必须重新评审。`review-story` 在部分禅道版本可能失败，需 UI 人工评审后用 `get-story` 确认 `status=active`。

## 创建执行 payload 示例

```json
{
  "project": 34,
  "name": "迭代-导出功能",
  "code": "sprintExport",
  "begin": "2026-08-10",
  "end": "2026-08-24",
  "PM": "your_account",
  "teamMembers": ["your_account"]
}
```

未传 `begin`/`end` 时默认今天～+14 天。

## 创建产品 payload 示例

```json
{
  "name": "我的新产品",
  "code": "myProduct",
  "program": 6,
  "type": "normal",
  "acl": "open",
  "desc": "可选描述"
}
```

`program` 为所属项目集 id（先 `list-programs`）。未传 `code` 时 CLI 会尝试从名称生成。

## 创建项目 payload 示例

```json
{
  "name": "我的新项目",
  "code": "myProject",
  "products": [12],
  "begin": "2026-08-10",
  "end": "2026-11-08",
  "model": "scrum",
  "parent": 0
}
```

`products` 必填且非空。未传 `begin`/`end` 时默认今天～+90 天；`model` 默认 `scrum`。

## 创建需求 payload 示例

```json
{
  "title": "支持导出报表",
  "product": 12,
  "pri": 2,
  "category": "feature",
  "spec": "背景与范围…",
  "verify": "验收标准…",
  "source": "dev",
  "estimate": 2
}
```

`category` 常见值：`feature` | `interface` | `performance` | `safe` | `experience` | `improve` | `other`

`status` 常见值：`draft` | `active` | `closed` | `changed` | `reviewing`  
`stage` 常见值：`wait` | `planned` | `projected` | `developing` | `developed` | `testing` | `tested` | `verified` | `released` | `closed`

创建需求时 CLI 默认补 `assignedTo` / `reviewer` 为配置账号。创建后务必先评审激活，再关联迭代与建任务。

## 创建任务 payload 示例

```json
{
  "executionId": 56,
  "assignedTo": "your_account",
  "tasks": [
    {
      "name": "实现导出接口",
      "type": "devel",
      "story": 1012,
      "estimate": 1.5,
      "pri": 2,
      "estStarted": "2026-08-10",
      "deadline": "2026-08-10"
    }
  ]
}
```

`type` 常见值：`design` | `devel` | `request` | `test` | `study` | `discuss` | `ui` | `affair` | `misc`  
任务 `status`：`wait` | `doing` | `done` | `closed` | `cancel`

未传 `estStarted` / `deadline` 时，CLI 按今天与预计工时自动补日期。

## 状态映射（配置 statusMap）

| 键 | 含义 | 默认建议 |
|----|------|----------|
| `storyAfterCreate` | 建需求后目标（通常需评审才能真正达到） | `active` |
| `taskAfterFinish` | 收工任务 | `done` |
| `storyAfterFinishPartial` | 仍有未完成工作 | 需求 `stage=developing`（保持 status=active） |
| `storyAfterFinishAll` | 本需求开发完成 | 需求 `stage=developed`（保持 status=active） |

若公司实例枚举不同，以接口报错为准，校准后写回配置。

## 链接（启发式）

- 产品：`{baseUrl}/product-view-{id}.html`
- 项目：`{baseUrl}/project-view-{id}.html`
- 需求：`{baseUrl}/story-view-{id}.html`
- 任务：`{baseUrl}/task-view-{id}.html`

若公司开启 PATH_INFO 或伪静态不同，以实际跳转为准。
