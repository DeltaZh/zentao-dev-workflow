# zentao-dev-workflow

Cursor 个人 Skill：把某次改动同步到禅道（研发需求 / 开发任务 / 迭代 / 工时 / 状态）。

## 快速开始

1. 复制配置模板：

```bash
mkdir -p ~/.config/zentao
cp config.example.json ~/.config/zentao/config.json
chmod 600 ~/.config/zentao/config.json
# 编辑填写 baseUrl / account / password
```

2. 验证登录：

```bash
python3 scripts/zentao.py auth
python3 scripts/zentao.py list-products
```

3. 在 Cursor 对话中说明要「创建禅道需求」或「收工完善任务」，Agent 会按 Skill 流程先确认再调用 CLI。

## 文档

- 设计规格：`docs/2026-08-10-zentao-dev-workflow-design.md`
- 实现计划：`docs/superpowers/plans/2026-08-10-zentao-dev-workflow.md`
- Agent 说明：`SKILL.md`
- API 字段：`reference.md`

## 许可与安全

请勿将真实 `config.json` 或密码提交到 Git。仓库仅包含 `config.example.json`。
