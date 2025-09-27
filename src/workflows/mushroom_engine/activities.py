import asyncio
import datetime as dt
import json
import math
import os
import re
from typing import Any

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field, ValidationError
from temporalio import activity

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
MODEL_NAME = os.getenv("REELS_MODEL_NAME", "gpt-4o")

if not YOUTUBE_API_KEY:
    raise OSError("YOUTUBE_API_KEY not set.")
if not OPENAI_API_KEY:
    raise OSError("OPENAI_API_KEY not set.")


class Idea(BaseModel):
    idea_id: str
    hook: str
    core_concept: str
    trend_leverage: str
    shot_list: list[str] = Field(min_items=1, max_items=10)
    on_screen_text: list[str]
    audio_suggestion: str
    caption: str
    hashtags: list[str] = Field(min_items=3, max_items=15)
    virality_rationale: str
    effort_level: str  # "low" | "medium" | "high"


@activity.defn(name="fetch_trending_dog_shorts")
async def fetch_trending_dog_shorts(
    query: str = "dog #shorts", order: str = "date", max_results: int = 25
) -> list[dict[str, Any]]:
    """Fetch recent dog-related shorts from YouTube."""

    def _call() -> list[dict[str, Any]]:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        req = youtube.search().list(
            part="snippet",
            maxResults=min(max_results, 50),
            q=query,
            type="video",
            order=order,
        )
        res = req.execute()
        items = []
        for item in res.get("items", []):
            sn = item.get("snippet", {})
            items.append(
                {
                    "platform": "youtube",
                    "title": sn.get("title"),
                    "channelTitle": sn.get("channelTitle"),
                    "videoId": item["id"]["videoId"],
                    "publishedAt": sn.get("publishedAt"),
                    "description": sn.get("description"),
                    "query_used": query,
                }
            )
        return items

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _call)
    except HttpError as e:
        raise RuntimeError(f"YouTube fetch failed: {e}") from e


@activity.defn(name="summarize_trends")
async def summarize_trends(trends: list[dict[str, Any]]) -> str:
    lines = []
    for i, t in enumerate(trends):
        published = (t.get("publishedAt") or "")[:19].replace("T", " ")
        title = (t.get("title") or "")[:120].replace("\n", " ")
        lines.append(f"{i + 1}. [{published}] {title} (vid:{t.get('videoId')})")
    return "\n".join(lines)


BASE_IDEA_PROMPT = """
You are a creative producer for short-form dog content. Using the trend list below,
return ONLY a JSON array of {idea_min}-{idea_max} objects—no commentary, no markdown fences.
Each object MUST include: idea_id, hook, core_concept, trend_leverage, shot_list, on_screen_text,
audio_suggestion, caption, hashtags (6–10 array), virality_rationale, effort_level.

DOG PROFILE:\n{dog_profile}\n\nTRENDS:\n{trend_block}
    """


def _estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


# Prefer the modern OpenAI client
try:
    from openai import OpenAI

    _OPENAI_CLIENT = OpenAI(api_key=OPENAI_API_KEY)

    def _chat_complete(prompt: str, max_tokens: int = 1800, temperature: float = 0.7) -> str:
        resp = _OPENAI_CLIENT.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
except Exception:  # fallback to legacy
    import openai as _openai

    _openai.api_key = OPENAI_API_KEY

    def _chat_complete(prompt: str, max_tokens: int = 1800, temperature: float = 0.7) -> str:
        resp = _openai.ChatCompletion.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp["choices"][0]["message"]["content"]


@activity.defn(name="generate_ideas")
async def generate_ideas(
    dog_profile: str,
    trend_block: str,
    idea_min: int,
    idea_max: int,
) -> str:
    if _estimate_tokens(trend_block) > 25000:
        trend_block = "\n".join(trend_block.splitlines()[:300])
    prompt = BASE_IDEA_PROMPT.format(
        idea_min=idea_min,
        idea_max=idea_max,
        dog_profile=dog_profile.strip(),
        trend_block=trend_block[:25000],
    )

    def _call() -> str:
        return _chat_complete(prompt)

    return await asyncio.get_running_loop().run_in_executor(None, _call)


def _extract_json_array(text: str) -> list:
    if not text:
        return []
    cleaned = re.sub(r"```(json)?", "", text, flags=re.IGNORECASE).strip()
    m = re.search(r"\[[\s\S]*\]", cleaned)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(0))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


@activity.defn(name="repair_json_if_needed")
async def repair_json_if_needed(
    raw_output: str, idea_min: int, idea_max: int
) -> list[dict[str, Any]]:
    ideas = _extract_json_array(raw_output)
    if ideas:
        return ideas

    reprompt = (
        f"The last output was invalid. Return ONLY a JSON array with {idea_min}-{idea_max} objects, "
        "each with keys: idea_id, hook, core_concept, trend_leverage, shot_list, on_screen_text, "
        "audio_suggestion, caption, hashtags (6–10 as array), virality_rationale, effort_level. "
        "No markdown fences, no commentary."
    )

    def _call() -> str:
        return _chat_complete(reprompt)

    repaired = await asyncio.get_running_loop().run_in_executor(None, _call)
    ideas = _extract_json_array(repaired)
    if not ideas:
        raise RuntimeError("Failed to repair JSON idea list.")
    return ideas


@activity.defn(name="normalize_and_validate")
async def normalize_and_validate(ideas_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for i, obj in enumerate(ideas_raw):
        if not isinstance(obj, dict):
            continue
        # normalize hashtags
        if isinstance(obj.get("hashtags"), str):
            tags = re.split(r"[ ,]+", obj["hashtags"].strip())
            obj["hashtags"] = [t for t in tags if t]
        obj.setdefault("shot_list", [])
        obj["_index"] = i
        obj["_generated_at"] = dt.datetime.utcnow().isoformat()
        try:
            _ = Idea(**{k: v for k, v in obj.items() if not k.startswith("_")})
        except ValidationError as ve:
            obj["_warnings"] = f"Validation issues: {ve.errors()}"
        clean.append(obj)
    return clean


@activity.defn(name="generate_scripts_and_rank")
async def generate_scripts_and_rank(
    ideas: list[dict[str, Any]],
    dog_profile: str,
    save: bool = False,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Wraps script_writer.generate_and_rank() to be Temporal-safe.
    Returns only JSON-serializable data.
    """

    def _call() -> dict[str, Any]:
        # Local import is OK in an activity (not in workflow!)
        from script_writer import generate_and_rank  # your module

        results, leaderboard = generate_and_rank(
            ideas=ideas,
            dog_profile=dog_profile,
            save=save,
            out_dir=out_dir or "data/scripts",
        )

        # Flatten ScriptResult dataclasses into plain dicts
        def _ser(res):
            return {
                "idea_ref": res.idea_ref,
                "idea_source_type": res.idea_source_type,
                "script_json": res.script_json,
                "raw_text": res.raw_text,
                "error": res.error,
                "model": res.model,
                "latency_s": res.latency_s,
                "attempts": res.attempts,
                "repaired": res.repaired,
                "score": res.score,
                "score_components": res.score_components,
                "warnings": res.warnings,
            }

        return {
            "results": {k: _ser(v) for k, v in results.items()},
            "leaderboard": leaderboard,
        }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call)
