# -*- coding: utf-8 -*-
"""多渠道推送：Server酱、PushPlus、Bark、Telegram、企业微信、钉钉、飞书、SMTP 邮件。

用法：PUSH_CHANNEL 环境变量选择渠道，多个渠道用英文逗号分隔，例如：
    PUSH_CHANNEL=serverchan,telegram
各渠道所需 Secret 见 .env.example 与 README。
"""
from __future__ import annotations

import html as html_mod
import json
import logging
import re
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlsplit

import requests

from utils import get_env, md_to_html, md_to_telegram_html, split_text_by_bytes, tables_to_lines

logger = logging.getLogger("push")

HTTP_TIMEOUT = 30


class ChannelMisconfigured(Exception):
    """渠道缺少所需的环境变量，跳过而不视为失败。"""


def _require(key: str) -> str:
    value = get_env(key)
    if not value:
        raise ChannelMisconfigured(f"缺少环境变量 {key}")
    return value


def _check(resp: requests.Response, name: str) -> None:
    """校验 HTTP 状态与各平台业务码。"""
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}：{resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError:
        return
    if data.get("ok") is False:
        raise RuntimeError(f"返回失败：{json.dumps(data, ensure_ascii=False)[:200]}")
    code = data.get("code", data.get("errcode", data.get("StatusCode", 0)))
    if code not in (0, 200, "0", "200", True):
        raise RuntimeError(f"返回失败：{json.dumps(data, ensure_ascii=False)[:200]}")


# ---------------------------------------------------------------- Server酱
def channel_serverchan(title: str, md: str) -> None:
    key = _require("SERVERCHAN_SENDKEY")
    resp = requests.post(
        f"https://sctapi.ftqq.com/{key}.send",
        data={"title": title, "desp": md},
        timeout=HTTP_TIMEOUT,
    )
    _check(resp, "Server酱")


# ---------------------------------------------------------------- PushPlus
def channel_pushplus(title: str, md: str) -> None:
    token = _require("PUSHPLUS_TOKEN")
    resp = requests.post(
        "https://www.pushplus.plus/send",
        json={"token": token, "title": title, "content": md, "template": "markdown"},
        timeout=HTTP_TIMEOUT,
    )
    _check(resp, "PushPlus")


# ---------------------------------------------------------------- Bark
def channel_bark(title: str, md: str) -> None:
    """Bark 只推 1000 字摘要（Bark 对长文本与排版支持有限），完整内容见仓库。"""
    raw = _require("BARK_URL").strip().rstrip("/")
    parts = urlsplit(raw)
    segments = [s for s in parts.path.split("/") if s]
    if segments and segments[-1].lower() == "push":
        segments.pop()
    if not segments:
        raise ChannelMisconfigured("BARK_URL 需形如 https://api.day.app/<DeviceKey>")
    device_key = segments[-1]
    base = f"{parts.scheme}://{parts.netloc}"
    digest = md[:1000].rstrip()
    if len(md) > 1000:
        digest += "\n\n……（完整内容已存入仓库 stories/ 目录）"
    resp = requests.post(
        f"{base}/push",
        json={"device_key": device_key, "title": title, "body": digest,
              "group": "civil-fable-push"},
        timeout=HTTP_TIMEOUT,
    )
    _check(resp, "Bark")


# ---------------------------------------------------------------- Telegram
def channel_telegram(title: str, md: str) -> None:
    token = _require("TELEGRAM_BOT_TOKEN")
    chat_id = _require("TELEGRAM_CHAT_ID")
    html_text = md_to_telegram_html(md)
    parts = split_text_by_bytes(html_text, 3800)  # Telegram 单条上限 4096 字符
    for i, part in enumerate(parts, 1):
        text = f"（{i}/{len(parts)}）\n{part}" if len(parts) > 1 else part
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=HTTP_TIMEOUT,
        )
        _check(resp, "Telegram")


# ---------------------------------------------------------------- 企业微信机器人
def channel_wecom(title: str, md: str) -> None:
    webhook = _require("WECOM_WEBHOOK")
    content = tables_to_lines(md)
    parts = split_text_by_bytes(content, 3600)  # 企业微信 markdown 上限 4096 字节
    for part in parts:
        resp = requests.post(
            webhook,
            json={"msgtype": "markdown", "markdown": {"content": part}},
            timeout=HTTP_TIMEOUT,
        )
        _check(resp, "企业微信")


# ---------------------------------------------------------------- 钉钉机器人
def channel_dingtalk(title: str, md: str) -> None:
    """钉钉自定义机器人请配置"自定义关键词"（推荐关键词：寓言），加签方式暂不支持。"""
    webhook = _require("DINGTALK_WEBHOOK")
    content = tables_to_lines(md)
    parts = split_text_by_bytes(content, 18000)  # 钉钉 markdown 上限约 2 万字节
    for part in parts:
        resp = requests.post(
            webhook,
            json={"msgtype": "markdown", "markdown": {"title": title, "text": part}},
            timeout=HTTP_TIMEOUT,
        )
        _check(resp, "钉钉")


# ---------------------------------------------------------------- 飞书机器人
def channel_feishu(title: str, md: str) -> None:
    webhook = _require("FEISHU_WEBHOOK")
    content = tables_to_lines(md)
    content = re.sub(r"^#{1,6}\s*(.+)$", r"**\1**", content, flags=re.M)  # lark_md 不渲染 # 标题
    parts = split_text_by_bytes(content, 20000)
    for part in parts:
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {"template": "blue",
                           "title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": part}],
            },
        }
        resp = requests.post(webhook, json=payload, timeout=HTTP_TIMEOUT)
        _check(resp, "飞书")


# ---------------------------------------------------------------- SMTP 邮件
def _email_html(title: str, html_body: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{html_mod.escape(title)}</title></head>"
        '<body style="margin:0;padding:24px;background:#f5f5f5;'
        'font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;">'
        '<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;'
        'padding:32px;line-height:1.8;color:#222;">'
        f"{html_body}"
        "</div></body></html>"
    )


def channel_smtp(title: str, md: str) -> None:
    host = _require("SMTP_HOST")
    user = _require("SMTP_USER")
    password = _require("SMTP_PASS")
    mail_to = _require("MAIL_TO")
    try:
        port = int(get_env("SMTP_PORT") or 465)
    except ValueError:
        port = 465

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = user
    msg["To"] = mail_to
    msg.attach(MIMEText(md, "plain", "utf-8"))
    msg.attach(MIMEText(_email_html(title, md_to_html(md)), "html", "utf-8"))

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    try:
        server.login(user, password)
        recipients = [addr.strip() for addr in mail_to.split(",") if addr.strip()]
        server.sendmail(user, recipients, msg.as_string())
    finally:
        server.quit()


# ---------------------------------------------------------------- 调度
CHANNELS = {
    "serverchan": ("Server酱", channel_serverchan),
    "pushplus": ("PushPlus", channel_pushplus),
    "bark": ("Bark", channel_bark),
    "telegram": ("Telegram", channel_telegram),
    "wecom": ("企业微信机器人", channel_wecom),
    "dingtalk": ("钉钉机器人", channel_dingtalk),
    "feishu": ("飞书机器人", channel_feishu),
    "mail": ("SMTP邮件", channel_smtp),
}
ALIASES = {
    "serverjiang": "serverchan",
    "ftqq": "serverchan",
    "email": "mail",
    "smtp": "mail",
    "wechat-work": "wecom",
    "qywx": "wecom",
}


def send_all(channels: str, title: str, md: str) -> dict[str, str]:
    """向所有已配置渠道推送。返回 {渠道: 状态}；状态为 ok / skipped / failed / 未知渠道。"""
    results: dict[str, str] = {}
    if not channels or not channels.strip():
        logger.warning("未配置 PUSH_CHANNEL，跳过推送（故事仍会保存并提交到仓库）")
        return results
    for raw in channels.split(","):
        name = raw.strip().lower()
        if not name:
            continue
        name = ALIASES.get(name, name)
        if name not in CHANNELS:
            results[raw.strip()] = f"未知渠道：{raw.strip()}"
            logger.error("未知推送渠道：%s（可选：%s）", raw.strip(), "、".join(CHANNELS))
            continue
        label, func = CHANNELS[name]
        try:
            func(title, md)
            results[label] = "ok"
            logger.info("推送成功：%s", label)
        except ChannelMisconfigured as exc:
            results[label] = f"skipped：{exc}"
            logger.warning("跳过 %s：%s", label, exc)
        except Exception as exc:  # noqa: BLE001 渠道间彼此独立，单渠道失败不中断
            results[label] = f"failed：{exc}"
            logger.error("推送失败 %s：%s", label, exc)
    return results
