#!/usr/bin/env python3
"""扫码绑定微信 ClawBot 并发送文本通知。"""

import argparse
import base64
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests


# 状态文件与脚本放在同一目录，不依赖执行命令时所在的目录。
STATE_FILE = Path(__file__).resolve().with_name(".wechat_clawbot.json")
BASE_URL = "https://ilinkai.weixin.qq.com"
BASE_INFO = {"channel_version": "2.4.8", "bot_agent": "WeChatNotify/1.0"}


def trusted_url(url):
    """验证微信接口地址使用 HTTPS，并去掉末尾斜杠。"""
    # 凭据会随请求发送，因此只接受微信域名。
    host = urlsplit(url)
    if host.scheme != "https" or not (host.hostname == "weixin.qq.com" or (host.hostname or "").endswith(".weixin.qq.com")):
        raise ValueError("无法确认微信服务器地址，已停止")
    return url.rstrip("/")


def request(method, base_url, endpoint, *, params=None, body=None, token=None, timeout=40):
    """请求微信接口并返回 JSON；HTTP 或业务错误会抛出异常。

    提供 token 时，自动添加机器人鉴权信息和接口所需的基础信息。
    """
    headers = {
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 8),
    }
    if method == "POST":
        headers["AuthorizationType"] = "ilink_bot_token"
        headers["X-WECHAT-UIN"] = base64.b64encode(str(secrets.randbits(32)).encode()).decode()
    # 扫码前的请求没有机器人凭据；绑定后的请求才需要鉴权。
    if token:
        headers["Authorization"] = "Bearer " + token
        body = {**body, "base_info": BASE_INFO}
    response = requests.request(method, trusted_url(base_url) + endpoint, params=params,
                                json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    code = result.get("errcode") or result.get("ret") or 0
    if code:
        raise RuntimeError(f"微信接口返回错误 {code}；会话过期时请运行 refresh")
    return result


def save_state(state):
    """以仅所有者可读写的权限保存凭据和消息游标。"""
    # 系统支持时拒绝跟随符号链接，并确保已有文件的权限也为 600。
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(STATE_FILE, flags, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)


def show_qr(content):
    """在终端显示二维码，并输出可在微信中打开的备用链接。"""
    try:
        import cv2
        qr = cv2.QRCodeEncoder_create().encode(content)
        qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        if qr.shape[0] % 2:
            qr = cv2.copyMakeBorder(qr, 0, 1, 0, 0, cv2.BORDER_CONSTANT, value=255)
        # 将上下两行二维码像素合并为一行字符，减少终端显示高度。
        blocks = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}
        for y in range(0, qr.shape[0], 2):
            line = "".join(blocks[(top == 0, bottom == 0)] for top, bottom in zip(qr[y], qr[y + 1]))
            print("\033[30;47m" + line + "\033[0m")
        print("请用手机微信扫描上面的二维码。")
    except (ImportError, AttributeError):
        print("当前环境没有可用的 OpenCV 二维码编码器。")
    print("也可以在手机微信中打开以下临时链接：")
    print(content, flush=True)


def refresh():
    """读取绑定账号发来的消息，更新发送通知所需的会话凭据。"""
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    print("请现在向微信 ClawBot 发一条消息；正在等待，最多约两分钟……", flush=True)
    for _ in range(3):
        data = request("POST", state["base_url"], "/ilink/bot/getupdates",
                       body={"get_updates_buf": state.get("get_updates_buf", "")}, token=state["bot_token"])
        # 保存增量消息游标，供下一次获取消息时继续使用。
        state["get_updates_buf"] = data.get("get_updates_buf") or state.get("get_updates_buf", "")
        received_token = None
        # 仅采用扫码绑定的微信账号发来的会话凭据。
        for message in data.get("msgs", []):
            if message.get("from_user_id") == state["user_id"] and message.get("context_token"):
                received_token = message["context_token"]
        if received_token:
            state["context_token"] = received_token
        save_state(state)
        if received_token:
            print("会话已建立，可以发送通知。")
            return
    raise RuntimeError("未收到绑定账号的消息，请重新运行 refresh 并向 ClawBot 发一条消息")


def login():
    """扫码取得机器人凭据，再获取用于发送通知的会话凭据。"""
    qr = request("POST", BASE_URL, "/ilink/bot/get_bot_qrcode",
                 params={"bot_type": "3"}, body={"local_token_list": []})
    show_qr(qr["qrcode_img_content"])
    print("等待扫码确认……", flush=True)
    base_url = BASE_URL
    verify_code = None
    last_status = None
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        params = {"qrcode": qr["qrcode"]}
        if verify_code:
            params["verify_code"] = verify_code
        try:
            result = request("GET", base_url, "/ilink/bot/get_qrcode_status", params=params)
        except requests.Timeout:
            # 状态查询为长轮询，单次超时后继续等待，直至整体等待结束。
            print("查询扫码状态超时，正在重试……", flush=True)
            continue
        status = result.get("status", "wait")
        if status != last_status:
            if status == "scaned":
                print("已检测到微信扫码，请在手机上继续确认。", flush=True)
            elif status == "scaned_but_redirect":
                print("已检测到扫码，正在切换微信连接服务器……", flush=True)
            elif status == "wait" and last_status in ("scaned", "scaned_but_redirect"):
                print("微信尚未返回授权结果，请查看手机。", flush=True)
            last_status = status
        if status == "confirmed":
            state = {"base_url": trusted_url(result.get("baseurl") or base_url),
                     "bot_token": result["bot_token"], "user_id": result["ilink_user_id"],
                     "get_updates_buf": ""}
            if not state["bot_token"] or not state["user_id"]:
                raise RuntimeError("微信未返回完整的绑定信息")
            # 先保存机器人凭据；获取会话失败时可单独运行 refresh。
            save_state(state)
            print("扫码绑定成功。", flush=True)
            refresh()
            return
        # 微信可能要求在另一个服务器上继续查询扫码状态。
        if status == "scaned_but_redirect":
            redirect_host = result.get("redirect_host")
            if redirect_host:
                base_url = trusted_url("https://" + redirect_host)
        elif status == "need_verifycode":
            verify_code = input("请输入微信显示的验证码：").strip()
        elif status in ("expired", "verify_code_blocked", "binded_redirect"):
            raise RuntimeError(f"二维码状态为 {status}，请检查微信绑定状态后重新 login")
        time.sleep(1)
    raise RuntimeError("等待扫码超时，请重新运行 login")


def send(text):
    """使用已保存的机器人和会话凭据发送文本通知。"""
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not all(state.get(key) for key in ("bot_token", "user_id", "context_token")):
        raise ValueError("凭据不完整，请按照笔记完成绑定并获取会话信息")
    request(
        "POST", state["base_url"], "/ilink/bot/sendmessage", token=state["bot_token"], timeout=15,
        body={"msg": {
            "from_user_id": "",
            "to_user_id": state["user_id"],
            # 为每次发送生成唯一的客户端消息标识。
            "client_id": "wechat-notify-" + str(uuid.uuid4()),
            "message_type": 2,
            "message_state": 2,
            "context_token": state["context_token"],
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }},
    )


def main():
    """解析命令行参数，执行登录、刷新会话或发送通知。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="扫码绑定并建立会话")
    commands.add_parser("refresh", help="更新会话信息")
    send_parser = commands.add_parser("send", help="发送文本通知")
    send_parser.add_argument("text", help="通知内容")
    argv = sys.argv[1:]
    # 兼容直接传入消息文本的用法。
    if argv and argv[0] not in ("login", "refresh", "send", "-h", "--help"):
        argv = ["send", *argv]
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            login()
        elif args.command == "refresh":
            refresh()
        elif args.text.strip():
            send(args.text)
            print("微信接口已接受请求，请以手机收到的消息为准。")
        else:
            parser.error("通知内容不能为空")
    except FileNotFoundError:
        print("找不到凭据文件，请先运行 login。", file=sys.stderr)
        return 1
    except requests.RequestException as error:
        print(f"微信网络请求失败：{type(error).__name__}，请检查网络和代理。", file=sys.stderr)
        return 1
    except (KeyError, ValueError, RuntimeError) as error:
        print(f"操作失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
