#!/usr/bin/env python3
"""将受支持的 Codex Hook 事件转成微信提醒。"""

import json
import os
import sys
from pathlib import Path

from wechat_clawbot import send


def project_path(cwd):
    """将主目录下的工作路径缩写为以 ~ 开头的形式。"""
    if not cwd:
        return "未知项目"
    try:
        return str(Path("~") / Path(cwd).relative_to(Path.home()))
    except ValueError:
        return cwd


def session_title(session_id):
    """根据会话 ID 从 Codex 本地索引读取最近的任务名称。"""
    if not session_id:
        return "未知任务"
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    title = None
    try:
        with (codex_home / "session_index.jsonl").open(encoding="utf-8") as index:
            for line in index:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict) and item.get("id") == session_id:
                    name = item.get("thread_name")
                    if isinstance(name, str) and name.strip():
                        title = name.strip()
    except (OSError, UnicodeError):
        pass
    return title or "未知任务"


def main():
    """读取 Hook 事件、发送提醒，并返回不影响原流程的结果。"""
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print("{}")
        return

    messages = {
        "Stop": "Codex 本轮回复已结束。",
        "PermissionRequest": "Codex 正在请求操作权限，请查看并处理。",
    }
    name = event.get("hook_event_name")
    message = messages.get(name)
    # Stop 事件可能提供本轮回复，取最后一个非空行加入提醒。
    if name == "Stop":
        reply = event.get("last_assistant_message")
        if isinstance(reply, str) and reply.strip():
            message = "回复末行：" + reply.strip().splitlines()[-1].strip() + "\n\n" + message
    # 只对匹配到的提问工具发提醒；具体界面是否触发此事件需实测。
    if name == "PreToolUse" and event.get("tool_name", "").endswith(
        ("request_user_input", "request_user_input_async")
    ):
        message = "Codex 请求补充信息，请查看对话。"

    if message:
        try:
            # 使用事件中的工作目录和会话 ID，避免混淆其他对话。
            project = project_path(event.get("cwd"))
            title = session_title(event.get("session_id"))
            # 微信可能将 Markdown 中的单个换行折叠为空格，用空行分隔段落。
            send(f"{project} · {title}\n\n{message}")
        except Exception:
            # 不输出异常内容，避免意外暴露凭据或请求详情。
            print(
                json.dumps(
                    {"systemMessage": "微信通知发送失败，请检查网络和会话凭据。"},
                    ensure_ascii=False,
                )
            )
            return

    # 不返回批准、拒绝或阻止对话的决策。
    print("{}")


if __name__ == "__main__":
    main()
