#!/usr/bin/env python3
"""用 QQ 邮箱给自己发送文本通知。"""

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def send(text):
    address = os.environ.get("QQ_EMAIL", "").strip()
    authorization = os.environ.get("QQ_MAIL_AUTH_CODE", "").strip()
    if not address or not authorization:
        raise ValueError("请先设置 QQ_EMAIL 和 QQ_MAIL_AUTH_CODE 环境变量")

    message = EmailMessage()
    message["Subject"] = "任务通知"
    message["From"] = address
    message["To"] = address
    message.set_content(text, charset="utf-8", cte="base64")

    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=20, context=ssl.create_default_context()) as smtp:
        smtp.login(address, authorization)
        smtp.send_message(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", help="通知内容")
    args = parser.parse_args()
    if not args.text.strip():
        parser.error("通知内容不能为空")
    try:
        send(args.text)
    except smtplib.SMTPAuthenticationError:
        print("邮箱验证失败，请检查 SMTP 服务和授权码。", file=sys.stderr)
        return 1
    except (smtplib.SMTPException, OSError) as error:
        print(f"邮件发送失败：{type(error).__name__}，请检查网络连接。", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"邮件发送失败：{error}", file=sys.stderr)
        return 1
    print("邮件服务器已接受，请检查 QQ 邮箱收件箱。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
