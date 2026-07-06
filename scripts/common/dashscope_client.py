"""Shared DashScope/Qwen-Max client helpers.

Keep API response parsing and retry behavior in one place so translation
entrypoints can focus on their input/output schemas.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable


SleepPolicy = float | int | Callable[[int], float]


def sanitize_error(error: Exception | str, env_names: tuple[str, ...] = ("DASHSCOPE_API_KEY",)) -> str:
    text = str(error)
    for env_name in env_names:
        secret = os.getenv(env_name)
        if secret:
            text = text.replace(secret, f"[REDACTED_{env_name}]")
    return text


def extract_choice_text(response: Any) -> str:
    if isinstance(response, dict):
        output = response.get("output") or {}
        choices = output.get("choices") if isinstance(output, dict) else None
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content.strip()
        text = output.get("text") if isinstance(output, dict) else None
        if isinstance(text, str):
            return text.strip()

    output = getattr(response, "output", None)
    if isinstance(output, dict):
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return content.strip()

    raise RuntimeError("Cannot extract text from DashScope response")


def _sleep_seconds(policy: SleepPolicy, attempt: int) -> float:
    if callable(policy):
        return max(0.0, float(policy(attempt)))
    return max(0.0, float(policy))


def call_dashscope_generation(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_attempts: int,
    sleep_seconds: SleepPolicy = 0.0,
    retry_log_prefix: str = "[RETRY]",
    failure_message: str = "DashScope generation failed after retries",
) -> tuple[str, int]:
    try:
        from dashscope import Generation
    except Exception as exc:
        raise RuntimeError("dashscope is required on the server for Qwen-Max translation") from exc

    attempts = max(1, max_attempts)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            try:
                response = Generation.call(
                    model=model,
                    messages=messages,
                    result_format="message",
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            except TypeError:
                response = Generation.call(
                    model=model,
                    messages=messages,
                    result_format="message",
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            text = extract_choice_text(response)
            if text:
                return text, attempt - 1
            raise RuntimeError("empty model response")
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            print(f"{retry_log_prefix} attempt={attempt}/{attempts} error={sanitize_error(exc)}", flush=True)
            delay = _sleep_seconds(sleep_seconds, attempt)
            if delay > 0:
                time.sleep(delay)

    safe_error = sanitize_error(last_error or RuntimeError("unknown error"))
    raise RuntimeError(f"{failure_message}: {safe_error}")
