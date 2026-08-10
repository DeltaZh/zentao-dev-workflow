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
| 产品列表 | GET | `/api.php/v1/products` |
| 项目列表 | GET | `/api.php/v1/projects` |
| 执行列表 | GET | `/api.php/v1/projects/{id}/executions` |
| 创建需求 | POST | `/api.php/v1/stories` |
| 创建任务 | POST | `/api.php/v1/executions/{id}/tasks` |
| 更新需求 | PUT | `/api.php/v1/stories/{id}` |
| 更新任务 | PUT | `/api.php/v1/tasks/{id}` |

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

`status` 常见值：`draft` | `active` | `closed` | `changed`  
`stage` 常见值：`wait` | `planned` | `projected` | `developing` | `developed` | `testing` | `tested` | `verified` | `released` | `closed`

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
| `storyAfterCreate` | 建需求后 | `active` |
| `taskAfterFinish` | 收工任务 | `done` |
| `storyAfterFinishPartial` | 仍有未完成工作 | 需求 `stage=developing` |
| `storyAfterFinishAll` | 本需求开发完成 | 需求 `stage=developed` |

若公司实例枚举不同，以接口报错为准，校准后写回配置。

## 链接（启发式）

- 需求：`{baseUrl}/story-view-{id}.html`
- 任务：`{baseUrl}/task-view-{id}.html`

若公司开启 PATH_INFO 或伪静态不同，以实际跳转为准。
