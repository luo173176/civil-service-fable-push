# -*- coding: utf-8 -*-
"""概念库加载、校验、随机选取与状态（used_concepts.json）读写。"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import yaml

from utils import now_beijing

logger = logging.getLogger("concepts")

REQUIRED_FIELDS = (
    "id", "name", "discipline", "difficulty", "one_liner",
    "key_points", "exam_relevance", "misconception", "metaphor_hint",
)


def load_concepts(path: Path) -> list[dict]:
    """加载并校验 config/concepts.yaml。"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    concepts = data.get("concepts")
    if not concepts or not isinstance(concepts, list):
        raise ValueError(f"{path} 中未找到 concepts 列表")

    problems: list[str] = []
    seen: set[str] = set()
    for item in concepts:
        missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
        if missing:
            problems.append(f"概念 {item.get('id', '?')} 缺少字段：{missing}")
        if item.get("id") in seen:
            problems.append(f"重复的概念 id：{item.get('id')}")
        seen.add(item.get("id"))
    if problems:
        raise ValueError("概念库校验失败：\n" + "\n".join(problems))

    logger.info("概念库加载完成，共 %s 个概念", len(concepts))
    return concepts


def load_state(path: Path) -> dict:
    """读取 used_concepts.json；缺失或损坏时返回初始结构。"""
    if Path(path).exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("状态文件不可读（%s），已重置：%s", exc, path)
            state = {}
    else:
        state = {}
    state.setdefault("used_ids", [])
    state.setdefault("last_used_id", None)
    state.setdefault("pregen_used", [])
    state.setdefault("history", [])
    return state


def save_state(path: Path, state: dict) -> None:
    """原子写入状态文件（先写临时文件再替换）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
    logger.info("状态已写入：%s", path)


def pick_concept(concepts: list[dict], state: dict) -> dict:
    """随机选取一个未使用的概念；全部用尽则清空记录重新循环，并避开上一次的概念。

    只修改传入的 state 字典（used_ids / last_used_id），是否落盘由调用方决定。
    """
    used = set(state.get("used_ids", []))
    last = state.get("last_used_id")
    pool = [c for c in concepts if c["id"] not in used and c["id"] != last]
    if not pool:
        logger.info("概念库已完整使用一轮，重新开始循环")
        state["used_ids"] = []
        pool = [c for c in concepts if c["id"] != last] or list(concepts)
    concept = random.choice(pool)
    state.setdefault("used_ids", []).append(concept["id"])
    state["last_used_id"] = concept["id"]
    return concept


def find_concept(concepts: list[dict], concept_id: str) -> dict | None:
    return next((c for c in concepts if c["id"] == concept_id), None)


def record_history(state: dict, concept: dict, source: str, file_name: str) -> None:
    """在 state 中追加一次推送历史（最多保留 500 条）。"""
    state.setdefault("history", []).append({
        "time": now_beijing().isoformat(timespec="seconds"),
        "concept_id": concept.get("id"),
        "concept_name": concept.get("name"),
        "source": source,
        "file": file_name,
    })
    state["history"] = state["history"][-500:]
