from __future__ import annotations

import json
import logging
import os
from typing import Any

from core_utils import FileUtils

logger = logging.getLogger(__name__)


def generate_llm_summary(
    text: str,
    *,
    file_type: str,
    enabled: bool,
    openai_client_class: Any,
    model: str,
    timeout_seconds: int,
) -> tuple[str | None, list[str]]:
    note = None
    if not enabled:
        return None, []
    if openai_client_class is None:
        return "OpenAI SDK is unavailable. Install the optional dependency to enable AI summaries.", []

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "OPENAI_API_KEY is not configured, so AI summaries are disabled.", []

    max_chars = int(os.getenv("LLM_TRUNCATE_CHARS") or FileUtils.DEFAULT_LLM_TRUNCATE_CHARS)
    truncated, was_truncated = FileUtils.truncate_text(text, max_chars)
    if was_truncated:
        note = f"Input was truncated to {max_chars} characters before sending it to the AI service."

    try:
        client = openai_client_class()
        system = (
            "You are a file organization assistant. Return STRICT JSON only with keys: "
            '{"summary": "...", "tags": ["..."]}. No markdown.'
        )
        user = (
            f"file_type={file_type}\n"
            "Please summarize the content in Traditional Chinese and suggest 3-10 tags.\n\n"
            f"{truncated}"
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            timeout=timeout_seconds,
        )
        content = (response.choices[0].message.content or "").strip()
        result = json.loads(content)
        summary = str(result.get("summary", "")).strip() or "AI returned an empty summary."
        tags = result.get("tags", []) or []
        if not isinstance(tags, list):
            tags = []
        normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()][:10]
        if note and note not in summary:
            summary = f"{summary} {note}"
        return summary, normalized_tags
    except Exception:
        logger.error("LLM summary generation failed", exc_info=True)
        message = "AI summary generation failed. Please review the logs for details."
        if note:
            message = f"{message} {note}"
        return message, []
