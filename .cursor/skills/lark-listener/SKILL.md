---
name: lark-listener
description: |
  飞书 ↔ Cursor：Python 收消息写 md，Agent 运行 lark_reply.py 发送回复。
  运行 start_lark_agent.ps1。当用户说「飞书监听」「处理飞书待办」时使用。
keywords: 飞书, Lark, 飞书监听, 处理飞书待办, Feishu bot
---

# 飞书 ↔ Cursor

**流程**：Python 收飞书 → 写入 `agent-tasks/lark-pending.md`；无头 Agent 自动处理 → 运行 `lark_reply.py` 发送回复。

## 快速开始

1. 配置 `lark-config.json`
2. `pip install lark-oapi requests -q`
3. 运行 `.\start_lark_agent.ps1`（默认开启 `--agent-on-new`，收到消息自动启动无头 Agent）

若不想自动启动 Agent，去掉 `--agent-on-new` 参数即可。

## 处理飞书待办（Agent 必须执行）

1. 读取 `agent-tasks/lark-pending.md`
2. 找每个不含 `**[已回复]**` 的块，提取 `message_id` 和用户消息
3. 对每条：处理 → 运行：
   ```bash
   python .cursor/skills/lark-listener/scripts/lark_reply.py om_xxx "回复内容" --mark-done --workspace 项目根路径
   ```

## 文件

| 文件 | 说明 |
|------|------|
| `lark_agent.py` | 飞书监听，写 lark-pending.md |
| `lark_reply.py` | 按 message_id 回复，--mark-done 自动标记已回复 |
