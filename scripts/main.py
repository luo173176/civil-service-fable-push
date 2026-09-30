# -*- coding: utf-8 -*-
"""程序入口：选概念 -> 生成故事（LLM 或预生成库）-> 保存 -> 推送 -> 记录状态。

用法：
    python scripts/main.py                     # 完整流程
    python scripts/main.py --dry-run           # 生成并保存，但不推送、不写状态
    python scripts/main.py --concept arrow-impossibility   # 指定概念
    python scripts/main.py --list-concepts     # 列出概念库
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
except ImportError:  # 允许在未安装 dotenv 时仅依赖真实环境变量运行
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False

from concepts import (find_concept, load_concepts, load_state,  # noqa: E402
                      pick_concept, record_history, save_state)
from llm import LLMClient, LLMError, LLMFatalError  # noqa: E402
from push import send_all  # noqa: E402
from utils import get_env, now_beijing, read_yaml, sanitize_filename, setup_logging  # noqa: E402

logger = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="公务员寓言每日推送")
    parser.add_argument("--dry-run", action="store_true",
                        help="生成并保存故事，但不推送、不写入状态文件")
    parser.add_argument("--concept", metavar="ID", default=None,
                        help="指定概念 id（默认随机选取未使用的概念）")
    parser.add_argument("--list-concepts", action="store_true",
                        help="列出概念库后退出")
    return parser.parse_args()


def extract_title(story: str) -> str | None:
    match = re.match(r"\s*#\s+(.+)", story)
    return match.group(1).strip() if match else None


def _pregen_concept_name(text: str, file: Path) -> str:
    match = re.search(r"\*\*概念[：:]\s*(.+?)\*\*", text)
    return match.group(1).strip() if match else file.stem


def pick_pregenerated(pregen_dir: Path, state: dict, concepts: list[dict],
                      want_name: str | None = None) -> tuple[str, dict] | None:
    """无 LLM Key 时，从 stories/pregenerated/ 按文件名顺序取一篇未推送过的故事。

    want_name 非空时（--concept 指定），只在该概念对应的文件中选取。
    """
    files = sorted(pregen_dir.glob("*.md"))
    used = set(state.get("pregen_used", []))
    remaining = [f for f in files if f.name not in used]
    if want_name is not None:
        remaining = [f for f in remaining
                     if _pregen_concept_name(f.read_text(encoding="utf-8"), f) == want_name]
    if not remaining:
        return None
    file = remaining[0]
    text = file.read_text(encoding="utf-8")
    name = _pregen_concept_name(text, file)
    concept = next((c for c in concepts if c["name"] == name), None)
    if concept is None:
        concept = {"id": f"pregen:{file.stem}", "name": name,
                   "discipline": "预生成", "difficulty": "-"}
    state.setdefault("pregen_used", []).append(file.name)
    if concept.get("id") and concept["id"] not in state.get("used_ids", []):
        state.setdefault("used_ids", []).append(concept["id"])
        state["last_used_id"] = concept["id"]
    logger.info("预生成库取用：%s（概念：%s）", file.name, name)
    return text, concept


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    args = parse_args()
    load_dotenv(ROOT / ".env")
    load_dotenv()
    setup_logging(str(ROOT / "logs" / "run.log"))
    settings = read_yaml(ROOT / "config" / "settings.yaml")

    try:
        concepts = load_concepts(ROOT / "config" / "concepts.yaml")
    except (OSError, ValueError) as exc:
        logger.error("概念库加载失败：%s", exc)
        return 1

    if args.list_concepts:
        for c in concepts:
            print(f"{c['id']:32s} {c['name']:12s} {c['discipline']} / {c['difficulty']}")
        return 0

    state_path = ROOT / "state" / "used_concepts.json"
    state = load_state(state_path)

    # 1. 决定生成方式并选概念
    client = LLMClient(settings)
    if client.available:
        source = "llm"
        if args.concept:
            concept = find_concept(concepts, args.concept)
            if concept is None:
                logger.error("未找到概念 id：%s（用 --list-concepts 查看）", args.concept)
                return 1
        else:
            concept = pick_concept(concepts, state)
        logger.info("本次概念：%s（%s / 难度：%s）",
                    concept["name"], concept["discipline"], concept["difficulty"])
        try:
            story = client.generate_story(concept, ROOT / "prompts" / "story_prompt.md")
        except (LLMError, LLMFatalError) as exc:
            logger.error("LLM 生成失败：%s", exc)
            return 1
    else:
        source = "pregenerated"
        want_name = None
        if args.concept:
            want = find_concept(concepts, args.concept)
            if want is None:
                logger.error("未找到概念 id：%s（用 --list-concepts 查看）", args.concept)
                return 1
            want_name = want["name"]
        picked = pick_pregenerated(ROOT / "stories" / "pregenerated", state, concepts, want_name)
        if picked is None:
            hint = f"预生成库中没有概念「{want_name}」的故事" if want_name \
                else "stories/pregenerated/ 预生成库为空或已全部推送"
            logger.error("未配置 LLM_API_KEY，且%s。可先复制 examples/ 下的故事到该目录。", hint)
            return 1
        story, concept = picked

    # 2. 保存
    story_title = extract_title(story) or f"今日寓言：{concept['name']}"
    stamp = now_beijing().strftime("%Y-%m-%d-%H")
    out_path = ROOT / "stories" / f"{stamp}-{sanitize_filename(concept['name'])}.md"
    try:
        out_path.write_text(story.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        logger.error("故事保存失败：%s", exc)
        return 1
    logger.info("故事已保存：%s", out_path.relative_to(ROOT))

    if args.dry_run:
        logger.info("[dry-run] 跳过推送与状态写入")
        return 0

    # 3. 推送
    channels_cfg = settings.get("push", {}) if isinstance(settings, dict) else {}
    channels = get_env("PUSH_CHANNEL")
    if not channels and isinstance(channels_cfg, dict):
        raw = channels_cfg.get("channels") or ""
        channels = ",".join(raw) if isinstance(raw, list) else str(raw)
    results = send_all(channels or "", story_title, story)
    all_failed = bool(results) and all(
        not v.startswith(("ok", "skipped")) for v in results.values()
    )
    if all_failed:
        logger.error("所有已配置渠道均推送失败：%s", results)

    # 4. 记录状态（由 GitHub Actions 随后自动 commit 回仓库）
    record_history(state, concept, source, out_path.name)
    try:
        save_state(state_path, state)
    except OSError as exc:
        logger.error("状态写入失败：%s", exc)
        return 1

    return 2 if all_failed else 0


if __name__ == "__main__":
    sys.exit(main())
