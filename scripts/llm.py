# -*- coding: utf-8 -*-
"""OpenAI 兼容接口封装：渲染提示词模板、调用对话接口、校验输出结构。"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from utils import get_env, retry

logger = logging.getLogger("llm")

SYSTEM_PROMPT = (
    "你是一位精通公共管理、公共政策、行政法、政治学与经济学的资深寓言作家，"
    "同时熟悉中国公务员考试的命题习惯。写作克制、具体、有画面感，"
    "擅长把艰深概念藏进故事、直到结尾才揭晓。"
    "严格按用户要求的 Markdown 结构输出：不要任何开场白、结束语、解释或代码围栏。"
)


class LLMError(RuntimeError):
    """LLM 生成失败（网络/接口/内容不完整）。"""


class LLMFatalError(RuntimeError):
    """不可重试的失败（如鉴权错误、模型不存在）。"""


class LLMClient:
    """读取 LLM_API_KEY 等环境变量（settings.yaml 作兜底）并生成故事。"""

    REQUIRED_SECTIONS = (
        "## 寓言故事", "## 原来讲的是", "## 概念解释",
        "## 隐喻对应表", "## 公务员考试视角", "## 思考题",
    )

    def __init__(self, settings: dict | None = None):
        cfg = (settings or {}).get("llm", {}) if isinstance(settings, dict) else {}
        self.api_key = get_env("LLM_API_KEY")
        self.base_url = (
            get_env("LLM_BASE_URL") or cfg.get("base_url") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = get_env("LLM_MODEL") or cfg.get("model") or "deepseek-chat"
        try:
            self.temperature = float(get_env("LLM_TEMPERATURE") or cfg.get("temperature", 0.8))
        except (TypeError, ValueError):
            self.temperature = 0.8
        try:
            self.max_tokens = int(get_env("LLM_MAX_TOKENS") or cfg.get("max_tokens", 8000))
            self.timeout = int(get_env("LLM_TIMEOUT") or cfg.get("timeout", 300))
            self.max_retries = int(get_env("LLM_MAX_RETRIES") or cfg.get("max_retries", 3))
        except (TypeError, ValueError):
            self.max_tokens, self.timeout, self.max_retries = 8000, 300, 3

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def render_prompt(self, template_path: Path, concept: dict) -> str:
        """把 {{字段}} 占位符替换为概念资料。"""
        template = Path(template_path).read_text(encoding="utf-8")
        values: dict[str, str] = {}
        for key, value in concept.items():
            if isinstance(value, list):
                values[key] = "\n".join(f"- {item}" for item in value)
            else:
                values[key] = str(value)
        for key, value in values.items():
            template = template.replace("{{" + key + "}}", value)
        return template

    @retry(times=3, delay=3.0, backoff=2.0, exceptions=(requests.RequestException, LLMError))
    def _chat(self, messages: list[dict]) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if resp.status_code in (401, 403, 404):
            raise LLMFatalError(f"HTTP {resp.status_code}（Key 无效或模型不存在）：{resp.text[:300]}")
        if resp.status_code >= 400:
            raise LLMError(f"HTTP {resp.status_code}：{resp.text[:300]}")
        content = resp.json()["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise LLMError("模型返回空内容")
        return content.strip()

    def generate_story(self, concept: dict, template_path: Path) -> str:
        """生成完整文章；不达标时带上纠错信息重试，最终失败抛 LLMError。"""
        prompt = self.render_prompt(template_path, concept)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        last_text = ""
        for attempt in range(1, self.max_retries + 1):
            text = self._chat(messages)
            cleaned = self._clean(text)
            ok, reason = self._validate(cleaned)
            if ok:
                logger.info("故事生成成功（第 %s 次尝试，全文 %s 字）", attempt, len(cleaned))
                return cleaned
            logger.warning("第 %s 次生成不合格（%s），带纠错信息重试", attempt, reason)
            last_text = cleaned
            # 纠错式重试：回传上一次输出与具体缺失项，让模型针对性修正，
            # 避免同温下一次次重复同样的格式错误
            messages = messages[:2] + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": (
                    f"你上一次的输出不合规：{reason}。请重新输出完整文章，"
                    "严格包含以下六个二级章节，顺序固定、不得增删："
                    "## 寓言故事、## 原来讲的是……、## 概念解释、## 隐喻对应表、"
                    "## 公务员考试视角、## 思考题；其中「原来讲的是」章节下的第一行为"
                    "**概念：xxx**。不要输出任何解释、开场白或代码围栏。"
                )},
            ]
        raise LLMError(
            f"连续 {self.max_retries} 次生成的内容不达标。最后一次输出开头：{last_text[:200]}"
        )

    @staticmethod
    def _clean(text: str) -> str:
        """去掉代码围栏与正文前的寒暄，从一级标题开始截取。"""
        text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", text.strip(), flags=re.I)
        match = re.search(r"^#\s+.+", text, flags=re.M)
        if match and match.start() > 0:
            text = text[match.start():]
        return text.strip()

    # 寓言故事要求 700-1000 字，这里对上下限都做宽松校验：
    # 低于 550 或高于 1400 判为不合格并重试，1000-1400 之间接受但告警
    STORY_MIN, STORY_SOFT_MAX, STORY_HARD_MAX = 550, 1000, 1400

    @classmethod
    def _validate(cls, text: str) -> tuple[bool, str]:
        for section in cls.REQUIRED_SECTIONS:
            if section not in text:
                return False, f"缺少章节：{section}"
        story = re.search(r"## 寓言故事(.*?)(?=\n## )", text, flags=re.S)
        if not story:
            return False, "找不到寓言故事部分"
        length = len(story.group(1).strip())
        if length < cls.STORY_MIN:
            return False, f"故事仅 {length} 字（要求 700-1000 字）"
        if length > cls.STORY_HARD_MAX:
            return False, f"故事 {length} 字，超出 1000 字上限太多"
        if length > cls.STORY_SOFT_MAX:
            logger.warning("故事 %s 字，略超 1000 字上限，予以接受", length)
        return True, "ok"
