"""
飞书监听：Python 收飞书消息并写入 lark-pending.md。
可选：收到新消息后启动无头 Agent 自动处理。

用法:
  python lark_agent.py --workspace D:\kuaikuAi\autowork
  python lark_agent.py --workspace D:\kuaikuAi\autowork --agent-on-new   # 收到消息后自动启动无头 Agent
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

try:
    import lark_oapi as lark
    import requests
except ImportError:
    print("请先安装: pip install lark-oapi requests", file=sys.stderr)
    sys.exit(1)

LARK_PENDING_FILENAME = "lark-pending.md"
CONFIG_FILENAME = "lark-config.json"
NON_TEXT_PLACEHOLDER = "(非文本消息)"


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_config(workspace_dir):
    for d in (workspace_dir, os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        path = os.path.join(d, CONFIG_FILENAME)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {}


def _domain_host(domain_key):
    return "https://open.larksuite.com" if domain_key in ("lark", "larksuite") else "https://open.feishu.cn"


def send_reply(message_id: str, content: str, app_id: str, app_secret: str, domain_key: str, workspace: str) -> bool:
    host = _domain_host(domain_key)
    url = f"{host}/open-apis/auth/v3/tenant_access_token/internal"
    r = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    r.raise_for_status()
    token = r.json()["tenant_access_token"]
    reply_url = f"{host}/open-apis/im/v1/messages/{message_id}/reply"
    body = {"content": json.dumps({"text": content}, ensure_ascii=False), "msg_type": "text"}
    r = requests.post(reply_url, json=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=10)
    r.raise_for_status()
    return r.json().get("code") == 0


def _spawn_headless_agent(workspace: str):
    """启动无头 Cursor Agent 处理飞书待办"""
    local = os.environ.get("LOCALAPPDATA", "")
    agent_path = os.path.join(local, "cursor-agent", "agent.cmd") if local else ""
    if not (agent_path and os.path.isfile(agent_path)):
        agent_path = "agent"
    prompt = (
        "Read agent-tasks/lark-pending.md. For each block WITHOUT **[已回复]**, extract message_id and user text (after 用户消息：). "
        "For each: 1) Generate reply. 2) Write reply to agent-tasks/reply-temp.txt (UTF-8). 3) Run: python .cursor/skills/lark-listener/scripts/lark_reply.py <message_id> --file agent-tasks/reply-temp.txt --mark-done --workspace . "
        "Use --file to avoid Windows cmd encoding issues. Process all pending."
    )

    if sys.platform == "win32":
        ps_cmd = f"& {repr(agent_path)} -p {repr(prompt)} --workspace {repr(workspace)} --trust -f"
        cmd_str = f'powershell -NoProfile -Command "{ps_cmd}"'
    else:
        cmd_str = f'{agent_path} -p {repr(prompt)} --workspace {repr(workspace)} --trust -f'

    try:
        subprocess.Popen(
            cmd_str,
            shell=True,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
        print(f"[{_ts()}] 已启动无头 Agent")
    except Exception as e:
        print(f"[{_ts()}] 启动 Agent 失败: {e}", file=sys.stderr)


def run_listener(app_id: str, app_secret: str, workspace_dir: str, ack: bool, domain_key: str, agent_on_new: bool = False):
    import time
    workspace = os.path.abspath(workspace_dir)
    task_dir = os.path.join(workspace, "agent-tasks")
    os.makedirs(task_dir, exist_ok=True)
    pending_path = os.path.join(task_dir, LARK_PENDING_FILENAME)
    domain = _domain_host(domain_key)
    last_agent_spawn = 0
    AGENT_SPAWN_COOLDOWN = 15

    if not os.path.isfile(pending_path):
        with open(pending_path, "w", encoding="utf-8") as f:
            f.write("# 飞书待办\n\nAgent 读取本文件，对每条无 **[已回复]** 的块：处理 user_text → 运行 lark_reply.py message_id \"回复\" --mark-done --workspace 项目根\n\n")

    def _noop(_d):
        pass

    def _get(obj, key, default=""):
        if obj is None:
            return default
        return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)

    def handle_im_message(data):
        try:
            event = _get(data, "event") or getattr(data, "event", None)
            if not event:
                return
            msg = _get(event, "message") or getattr(event, "message", None)
            if not msg:
                return
            message_id = (_get(msg, "message_id") or "").strip()
            chat_id = _get(msg, "chat_id", "")
            msg_type = _get(msg, "message_type", "")
            text = NON_TEXT_PLACEHOLDER
            if message_id and msg_type == "text":
                raw = _get(msg, "content") or "{}"
                try:
                    c = json.loads(raw) if isinstance(raw, str) else raw
                    text = (_get(c, "text") or "").strip() if isinstance(c, dict) else str(raw)[:200]
                except Exception:
                    text = str(raw)[:200] if raw else NON_TEXT_PLACEHOLDER
            elif message_id:
                text = str(_get(msg, "content", ""))[:200] or NON_TEXT_PLACEHOLDER
            if not message_id:
                return

            # 去重：同一 message_id 已存在则跳过（飞书可能重推事件）
            try:
                with open(pending_path, "r", encoding="utf-8") as f:
                    if f"message_id: {message_id}" in f.read():
                        print(f"[{_ts()}] 跳过重复 message_id={message_id}")
                        return
            except Exception:
                pass

            block = f"""
---
message_id: {message_id}
chat_id: {chat_id}
**[{_ts()}]** 用户消息：
{text}

---
"""
            with open(pending_path, "a", encoding="utf-8") as f:
                f.write(block)
            print(f"[{_ts()}] 收到消息 message_id={message_id} text={text[:40]}...")

            if ack:
                try:
                    send_reply(message_id, "已收到，正在处理。", app_id, app_secret, domain_key, workspace)
                except Exception as e:
                    print(f"[{_ts()}] ack 失败: {e}", file=sys.stderr)

            if agent_on_new:
                nonlocal last_agent_spawn
                now = time.time()
                if now - last_agent_spawn >= AGENT_SPAWN_COOLDOWN:
                    _spawn_headless_agent(workspace)
                    last_agent_spawn = now
                else:
                    print(f"[{_ts()}] 冷却中，跳过启动 Agent（{int(AGENT_SPAWN_COOLDOWN - (now - last_agent_spawn))}s 后可再启动）")
        except Exception as e:
            print(f"[{_ts()}] handle_im_message: {e}", file=sys.stderr)

    ev = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_im_message)
        .register_p2_im_message_message_read_v1(_noop)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_noop)
        .build()
    )

    while True:
        try:
            client = lark.ws.Client(app_id, app_secret, event_handler=ev, domain=domain)
            client.start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[{_ts()}] 连接失败: {e}，30s 后重试...", file=sys.stderr)
            import time
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="Lark listener: receive -> write lark-pending.md")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--app-id", default="")
    parser.add_argument("--app-secret", default="")
    parser.add_argument("--ack", action="store_true", help="Reply 'received' on new message")
    parser.add_argument("--agent-on-new", action="store_true", help="Start headless Agent when new message arrives")
    args = parser.parse_args()

    cfg = _load_config(args.workspace)
    app_id = args.app_id or os.environ.get("APP_ID") or cfg.get("app_id", "")
    app_secret = args.app_secret or os.environ.get("APP_SECRET") or cfg.get("app_secret", "")
    domain_key = (cfg.get("domain") or "feishu").lower()

    if not app_id or not app_secret:
        print("请配置 app_id、app_secret（lark-config.json）", file=sys.stderr)
        sys.exit(1)

    print(f"[{_ts()}] 飞书监听启动，workspace={args.workspace}" + (" [无头Agent已开启]" if args.agent_on_new else ""))
    run_listener(app_id, app_secret, args.workspace, args.ack, domain_key, agent_on_new=args.agent_on_new)


if __name__ == "__main__":
    main()
