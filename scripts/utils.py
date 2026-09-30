# -*- coding: utf-8 -*-
"""通用工具：日志、北京时间、YAML 读取、文本变换与按字节切分、重试装饰器。"""
from __future__ import annotations

import functools
import html as html_mod
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def now_beijing() -> datetime:
    """当前北京时间（Asia/Shanghai，无夏令时）。"""
    return datetime.now(BEIJING_TZ)


def setup_logging(log_file: str | None = None, level: int = logging.INFO) -> None:
    """控制台 + 可选文件双通道日志。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def get_env(key: str, default: str | None = None) -> str | None:
    """读取环境变量，容忍首尾空白与成对引号。"""
    value = os.environ.get(key)
    if value is None:
        return default
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value or default


def read_yaml(path: Path) -> dict:
    """读取 YAML 文件；文件不存在时返回空字典。"""
    if not Path(path).exists():
        return {}
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def sanitize_filename(name: str) -> str:
    """去掉文件名中的非法字符与空白。"""
    return re.sub(r'[\\/:*?"<>|\r\n\t ]+', "", name).strip(".")


def md_to_html(md_text: str) -> str:
    """Markdown 转 HTML（支持表格、代码块），用于邮件等富文本渠道。"""
    import markdown

    return markdown.markdown(md_text, extensions=["tables", "fenced_code"])


def tables_to_lines(md_text: str) -> str:
    """把 Markdown 表格降级为普通文本行。

    企业微信/钉钉/飞书/Telegram 的消息 Markdown 均不支持表格，
    推送前统一转换，避免整段丢失。
    """
    lines = md_text.splitlines()
    separator = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|") and i + 1 < len(lines) and separator.match(lines[i + 1]):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            out.append("**" + " ｜ ".join(header) + "**")
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("· " + " ｜ ".join(cells))
                i += 1
            out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def md_to_telegram_html(md_text: str) -> str:
    """Markdown 转 Telegram HTML 子集（b/i/code，每行标签自闭合，便于安全分段）。"""
    text = tables_to_lines(md_text)
    html = md_to_html(text)
    html = re.sub(r"<(h[1-6])[^>]*>(.*?)</\1>", r"<b>\2</b>", html, flags=re.S)
    html = re.sub(r"<(strong|b)>(.*?)</\1>", r"<b>\2</b>", html, flags=re.S)
    html = re.sub(r"<(em|i)>(.*?)</\1>", r"<i>\2</i>", html, flags=re.S)
    html = re.sub(r"<li[^>]*>", "• ", html)
    html = re.sub(r"</(p|div|ul|ol|li|table|thead|tbody|tr|blockquote|h[1-6]|pre)>", "\n", html)
    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = html_mod.unescape(html)
    html = re.sub(r"[ \t]+\n", "\n", html)
    html = re.sub(r"\n{3,}", "\n\n", html).strip()
    # 只转义文本部分，保留我们自己插入的 <b>/<i> 标签
    parts = re.split(r"(<[^>]+>)", html)
    for idx in range(0, len(parts), 2):
        parts[idx] = (
            parts[idx].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
    return "".join(parts)


def _split_by_chars_with_byte_limit(text: str, max_bytes: int, encoding: str = "utf-8") -> list[str]:
    """逐字符累加，保证每段编码后不超过 max_bytes（不切断多字节字符）。"""
    parts: list[str] = []
    current: list[str] = []
    current_bytes = 0
    for ch in text:
        ch_bytes = len(ch.encode(encoding))
        if current and current_bytes + ch_bytes > max_bytes:
            parts.append("".join(current))
            current, current_bytes = [], 0
        current.append(ch)
        current_bytes += ch_bytes
    if current:
        parts.append("".join(current))
    return parts


def split_text_by_bytes(text: str, max_bytes: int) -> list[str]:
    """按字节数切分长文本：优先在空行（段落）处断开，单段超长时逐字符硬切。

    用于各推送渠道的消息长度上限（如企业微信 4096 字节、Telegram 4096 字符）。
    """
    if max_bytes < 64:
        raise ValueError("max_bytes 过小，无法安全切分")
    paragraphs = text.split("\n\n")
    parts: list[str] = []
    buf = ""
    for para in paragraphs:
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate.encode("utf-8")) <= max_bytes:
            buf = candidate
            continue
        if buf:
            parts.append(buf)
            buf = ""
        while len(para.encode("utf-8")) > max_bytes:
            head = _split_by_chars_with_byte_limit(para, max_bytes)[0]
            parts.append(head)
            para = para[len(head):]
        buf = para
    if buf:
        parts.append(buf)
    return [p for p in parts if p.strip()]


def retry(times: int = 3, delay: float = 2.0, backoff: float = 2.0,
          exceptions: tuple[type[Exception], ...] = (Exception,)):
    """指数退避重试装饰器；最后一次仍失败则抛出原异常。"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            wait = delay
            last_exc: Exception | None = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last_exc = exc
                    if attempt == times:
                        break
                    logging.getLogger(func.__module__).warning(
                        "%s 第 %s/%s 次失败：%s，%.1f 秒后重试",
                        func.__name__, attempt, times, exc, wait,
                    )
                    time.sleep(wait)
                    wait *= backoff
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
