"""
飞书（Lark）长连接监听：收到消息后写入 agent-tasks/lark-pending.md，可选立即回复或触发命令。

用法:
  python lark_listener.py --workspace D:\kuaikuAi\autowork
  python lark_listener.py --workspace D:\kuaikuAi\autowork --ack --on-new "cursor D:\kuaikuAi\autowork agent-tasks/lark-pending.md"

配置：从 lark-config.json 读取 app_id、app_secret、domain（不填或 feishu 为飞书中国，lark 为国际版）。
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# 长连接与事件处理依赖 lark-oapi
try:
    import lark_oapi as lark
except ImportError:
    print("请先安装: pip install lark-oapi", file=sys.stderr)
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


def _domain_url(domain_key):
    if domain_key in ("lark", "larksuite"):
        return "https://open.larksuite.com"
    return "https://open.feishu.cn"


def run_ws_listener(app_id: str, app_secret: str, workspace_dir: str, ack: bool = False, on_new_cmd: str = "", domain_key: str = "feishu"):
    workspace = os.path.abspath(workspace_dir)
    task_dir = os.path.join(workspace, "agent-tasks")
    os.makedirs(task_dir, exist_ok=True)
    pending_path = os.path.join(task_dir, LARK_PENDING_FILENAME)
    domain = _domain_url(domain_key)

    def _noop(_data):
        # 已读回执等事件无需处理，仅避免 "processor not found" 报错
        pass

    def _get(obj, key, default=""):
        """从 dict 或对象取属性，兼容 lark_oapi 传入的事件对象"""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def handle_im_message(data):
        try:
            # lark_oapi: data.event 为 P2ImMessageReceiveV1Data，data.event.message 为 EventMessage（含 message_id/chat_id/content）
            event = _get(data, "event")
            if event is None:
                event = getattr(data, "event", None)
            if event is None:
                return
            msg = _get(event, "message")  # EventMessage
            if msg is None:
                msg = getattr(event, "message", None)
            if msg is None:
                return
            message_id = _get(msg, "message_id", "") or ""
            chat_id = _get(msg, "chat_id", "") or ""
            msg_type = _get(msg, "message_type", "") or ""
            text = NON_TEXT_PLACEHOLDER
            if message_id and msg_type == "text":
                raw = _get(msg, "content") or "{}"
                try:
                    content = json.loads(raw) if isinstance(raw, str) else raw
                    text = (_get(content, "text") or "").strip() if isinstance(content, dict) else str(raw)[:200]
                except Exception:
                    text = str(raw)[:200] if raw else NON_TEXT_PLACEHOLDER
            elif message_id:
                text = str(_get(msg, "content", ""))[:200] or NON_TEXT_PLACEHOLDER
            if not message_id:
                return
            block = f"""
---
message_id: {message_id}
chat_id: {chat_id}
**[{_ts()}]** 飞书消息（请执行并回复此 message_id）：
{text}

"""
            with open(pending_path, "a", encoding="utf-8") as f:
                f.write(block)
            print(f"[{_ts()}] 收到消息 message_id={message_id} chat_id={chat_id} text={text[:50]}...")
            print(f"INFO: 已写入 pending: {pending_path}")

            if ack:
                try:
                    reply_script = os.path.join(os.path.dirname(__file__), "lark_reply.py")
                    if os.path.isfile(reply_script):
                        subprocess.run(
                            [sys.executable, reply_script, message_id, "已收到，正在处理。"],
                            cwd=workspace,
                            timeout=5,
                            capture_output=True,
                        )
                        print("INFO: 回复成功", message_id)
                except Exception as e:
                    print("WARN: ack 回复失败:", e, file=sys.stderr)

            if on_new_cmd:
                try:
                    subprocess.Popen(
                        on_new_cmd,
                        shell=True,
                        cwd=workspace,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    print("WARN: on-new 执行失败:", e, file=sys.stderr)
        except Exception as e:
            print(f"ERROR: handle_im_message: {e}", file=sys.stderr)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle_im_message)
        .register_p2_im_message_message_read_v1(_noop)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_noop)  # 用户打开与机器人的单聊时触发，忽略即可
        .build()
    )

    while True:
        try:
            client = lark.ws.Client(
                app_id,
                app_secret,
                event_handler=event_handler,
                domain=domain,
            )
            client.start()
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"[{_ts()}] 连接失败: {e}，30s 后重试...", file=sys.stderr)
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="飞书长连接监听，写入 lark-pending.md")
    parser.add_argument("--workspace", default=os.getcwd(), help="项目根目录")
    parser.add_argument("--app-id", default="", help="App ID（优先配置文件）")
    parser.add_argument("--app-secret", default="", help="App Secret（优先配置文件）")
    parser.add_argument("--ack", action="store_true", help="写入 pending 后立即回复「已收到，正在处理」")
    parser.add_argument("--on-new", default="", help="有新待办时执行的命令")
    parser.add_argument("--log-dir", default="", help="日志目录（可选）")
    args = parser.parse_args()

    cfg = _load_config(args.workspace)
    app_id = args.app_id or os.environ.get("APP_ID") or cfg.get("app_id", "")
    app_secret = args.app_secret or os.environ.get("APP_SECRET") or cfg.get("app_secret", "")
    domain_key = (cfg.get("domain") or "feishu").lower()

    if not app_id or not app_secret:
        print("请配置 app_id 与 app_secret（lark-config.json 或环境变量 APP_ID/APP_SECRET）", file=sys.stderr)
        sys.exit(1)

    print(f"[{_ts()}] 启动监听 app_id={app_id[:12]}... domain={_domain_url(domain_key)}")
    run_ws_listener(app_id, app_secret, args.workspace, ack=args.ack, on_new_cmd=args.on_new or "", domain_key=domain_key)


if __name__ == "__main__":
    main()
