"""
按 message_id 回复飞书消息，供 Agent 在处理完 lark-pending 后调用。

用法:
  python lark_reply.py <message_id> <回复内容>
  python lark_reply.py <message_id> --file reply.txt
  python lark_reply.py <message_id> "回复" --mark-done --workspace D:\\proj
  echo 回复内容 | python lark_reply.py <message_id> -

配置：从 lark-config.json 或环境变量 APP_ID、APP_SECRET 读取。
"""

import argparse
import json
import os
import re
import sys

try:
    import requests
except ImportError:
    print("请先安装: pip install requests", file=sys.stderr)
    sys.exit(1)

CONFIG_FILENAME = "lark-config.json"
MARK_REPLIED = "**[已回复]**"


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
    if domain_key in ("lark", "larksuite"):
        return "https://open.larksuite.com"
    return "https://open.feishu.cn"


def get_tenant_access_token(app_id: str, app_secret: str, domain_host: str) -> str:
    url = f"{domain_host}/open-apis/auth/v3/tenant_access_token/internal"
    r = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data.get("msg", "获取 tenant_access_token 失败"))
    return data["tenant_access_token"]


def reply(message_id: str, content_text: str, app_id: str, app_secret: str, domain_key: str = "feishu", workspace: str = None) -> bool:
    workspace = workspace or os.getcwd()
    host = _domain_host(domain_key)
    token = get_tenant_access_token(app_id, app_secret, host)
    url = f"{host}/open-apis/im/v1/messages/{message_id}/reply"
    body = {
        "content": json.dumps({"text": content_text}, ensure_ascii=False),
        "msg_type": "text",
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(url, json=body, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data.get("msg", "回复失败"))
    return True


def mark_replied_in_pending(workspace: str, message_id: str):
    """在 lark-pending.md 中标记该 message_id 已回复"""
    path = os.path.join(workspace, "agent-tasks", "lark-pending.md")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if f"message_id: {message_id}" not in content or MARK_REPLIED in content:
        return
    parts = re.split(r"(\n---+\n)", content)
    for i in range(0, len(parts), 2):
        block = parts[i]
        if f"message_id: {message_id}" not in block or MARK_REPLIED in block:
            continue
        parts[i] = block.rstrip() + f"\n{MARK_REPLIED}\n"
        break
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def main():
    parser = argparse.ArgumentParser(description="按 message_id 回复飞书消息")
    parser.add_argument("message_id", help="要回复的消息 ID（om_ 开头）")
    parser.add_argument("content", nargs="?", default="", help="回复正文；若为 - 则从 stdin 读取")
    parser.add_argument("--file", "-f", default="", help="从文件读取回复内容")
    parser.add_argument("--workspace", default=os.getcwd(), help="项目根目录")
    parser.add_argument("--mark-done", action="store_true", help="发送后在 lark-pending.md 标记已回复")
    parser.add_argument("--app-id", default="", help="覆盖配置的 App ID")
    parser.add_argument("--app-secret", default="", help="覆盖配置的 App Secret")
    args = parser.parse_args()

    cfg = _load_config(args.workspace)
    app_id = args.app_id or os.environ.get("APP_ID") or cfg.get("app_id", "")
    app_secret = args.app_secret or os.environ.get("APP_SECRET") or cfg.get("app_secret", "")
    domain_key = (cfg.get("domain") or "feishu").lower()

    if not app_id or not app_secret:
        print("请配置 app_id 与 app_secret（lark-config.json 或环境变量）", file=sys.stderr)
        sys.exit(1)

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            content_text = f.read().strip()
    elif args.content == "-":
        content_text = sys.stdin.read().strip()
    else:
        content_text = (args.content or "").strip()

    if not content_text:
        print("回复内容为空", file=sys.stderr)
        sys.exit(1)

    # 幂等：若该 message_id 的块已有 已回复 则跳过
    pending_path = os.path.join(args.workspace, "agent-tasks", "lark-pending.md")
    if os.path.isfile(pending_path):
        with open(pending_path, "r", encoding="utf-8") as f:
            raw = f.read()
        idx = raw.find(f"message_id: {args.message_id}")
        if idx >= 0:
            next_sep = raw.find("\n---", idx + 10)
            block = raw[idx : next_sep if next_sep >= 0 else len(raw)]
            if "**[已回复]**" in block:
                print("INFO: 该消息已回复，跳过", args.message_id)
                sys.exit(0)

    try:
        reply(
            args.message_id,
            content_text,
            app_id,
            app_secret,
            domain_key=domain_key,
            workspace=args.workspace,
        )
        if args.mark_done:
            mark_replied_in_pending(args.workspace, args.message_id)
        print("INFO: 回复成功", args.message_id)
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
