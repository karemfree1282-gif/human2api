"""Opt-in selector recovery. Suggestions are never persisted automatically.

Local semantic matching uses aria roles/labels. Optional remote AI recovery sends
sanitized *element metadata* (no field values/passwords/cookies) only with
explicit user consent, configured endpoint and token. Always verify uniqueness.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .models import WorkflowError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _unique_visible(candidate: Any) -> bool:
    try:
        return candidate.count() == 1 and candidate.first.is_visible()
    except Exception:
        return False


def semantic_locator(page: Any, step: dict[str, Any]) -> Any | None:
    role, label, hint = (step.get(x) for x in ("role", "label", "textHint"))
    candidates = []
    if role and label:
        candidates.append(page.get_by_role(role, name=label, exact=True))
    if label:
        candidates.append(page.get_by_label(label, exact=True))
    if hint and step["action"] in {"click", "wait", "assert_text", "extract_text", "hover"}:
        candidates.append(page.get_by_text(hint, exact=True))
    for candidate in candidates:
        if _unique_visible(candidate):
            return candidate.first
    return None


def _sanitize_elements(page: Any) -> list[dict[str, str]]:
    # Do not capture input values, page text, password fields, or entire HTML.
    # Limit to interactive element metadata; aria labels can themselves include
    # identifiers, which is why remote use always requires explicit consent.
    return page.locator("button, a, input, select, textarea, [role]").evaluate_all("""els =>
      els.filter(el => el.type !== 'password' && el.type !== 'hidden')
        .slice(0, 70).map(el => ({
        tag: el.tagName.toLowerCase(),
        id: (el.id || '').slice(0, 80),
        name: (el.getAttribute('name') || '').slice(0, 80),
        role: (el.getAttribute('role') || '').slice(0, 50),
        label: (el.getAttribute('aria-label') || '').slice(0, 80),
        testid: (el.getAttribute('data-testid') || '').slice(0, 80)
      }))""")


def _ai_endpoint() -> str:
    endpoint = os.environ.get("H2A_AI_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise WorkflowError("AI endpoint requires HTTPS or local loopback HTTP")
    if parsed.username or parsed.password or not parsed.hostname or parsed.fragment:
        raise WorkflowError("AI endpoint URL is invalid")
    return endpoint


def ai_selector(page: Any, step: dict[str, Any]) -> tuple[Any, str] | None:
    """Use OpenAI-compatible chat completions to suggest *only* a CSS selector.

    Never execute the model's code. Never automatically change workflow files.
    The API key is optional for an explicitly configured loopback provider.
    """
    endpoint = _ai_endpoint()
    key = os.environ.get("H2A_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"} and not key:
        raise WorkflowError("AI selector recovery requires H2A_AI_API_KEY")
    try:
        elements = _sanitize_elements(page)
        body = {
            "model": os.environ.get("H2A_AI_MODEL", "gpt-4.1-mini"),
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "Suggest one CSS selector for a browser element. Return a JSON object with just a selector string. Never provide code or a command. Prefer ID, data-testid, name. If uncertain respond with {\"selector\":\"\"}."},
                {"role": "user", "content": json.dumps({"action": step["action"], "oldSelector": step.get("selector", ""), "role": step.get("role", ""), "label": step.get("label", ""), "candidates": elements}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        data = json.dumps(body).encode("utf-8")
        if len(data) > 25_000:
            raise WorkflowError("AI selector metadata exceeds safe size")
        response = build_opener(_NoRedirect()).open(Request(endpoint, data=data, headers=headers, method="POST"), timeout=15)
        with response:
            if response.status != 200 or int(response.headers.get("Content-Length", "0")) > 100_000:
                return None
            payload = response.read(100_001)
        if len(payload) > 100_000:
            return None
        answer = json.loads(json.loads(payload)["choices"][0]["message"]["content"])
        selector = answer.get("selector", "")
        if not isinstance(selector, str) or not 0 < len(selector) < 200:
            return None
        loc = page.locator(selector)
        if _unique_visible(loc):
            return loc.first, selector
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    return None


def recover(page: Any, step: dict[str, Any], *, ai: bool = False) -> tuple[Any, str] | None:
    loc = semantic_locator(page, step)
    if loc is not None:
        return loc, "semantic"
    if ai:
        result = ai_selector(page, step)
        if result is not None:
            return result
    return None
