"""Privacy-conscious browser recording with deterministic selector fallbacks.

Captured form values are discarded immediately and replaced by typed variables.
This is a guided browser workflow recorder, not a desktop/screen recorder.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import NAME_RE, WorkflowError, save_workflow
from .runner import launch_browser

# No imported scripts, remote telemetry, or third-party analytics.
RECORDER_SCRIPT = r"""
(() => {
  if (window.__h2aLoaded) return;
  window.__h2aLoaded = true;
  const CSSQ = (s) => CSS.escape(String(s));
  const quote = (s) => JSON.stringify(String(s));
  const preferred = (el) => {
    if (!(el instanceof Element)) return [];
    const list = [];
    if (el.hasAttribute('data-testid')) list.push(`[data-testid=${quote(el.getAttribute('data-testid'))}]`);
    if (el.id) list.push(`#${CSSQ(el.id)}`);
    if (el.getAttribute('name')) list.push(`${el.tagName.toLowerCase()}[name=${quote(el.getAttribute('name'))}]`);
    if (el.getAttribute('aria-label')) list.push(`${el.tagName.toLowerCase()}[aria-label=${quote(el.getAttribute('aria-label'))}]`);
    const route = [];
    for (let node = el; node && node.nodeType === 1 && route.length < 9; node = node.parentElement) {
      if (node.id) { route.unshift(`#${CSSQ(node.id)}`); break; }
      let tag = node.tagName.toLowerCase();
      let sibling = node;
      let nth = 1;
      while ((sibling = sibling.previousElementSibling)) {
        if (sibling.tagName === node.tagName) nth++;
      }
      route.unshift(`${tag}:nth-of-type(${nth})`);
    }
    if (route.length) list.push(route.join(' > '));
    return [...new Set(list)].filter((sel) => {
      try { return document.querySelector(sel) === el; } catch (_) { return false; }
    });
  };
  const emit = (msg) => { try { window.h2aBridge(msg).catch(() => {}); } catch (_) {} };
  const ignore = (node) => !node || node.closest?.('#h2a-recorder-control');
  const metadata = (el) => {
    const selectors = preferred(el);
    if (!selectors.length) return null;
    return {selector: selectors[0], alternatives: selectors.slice(1, 6)};
  };
  document.addEventListener('change', (ev) => {
    const el = ev.target;
    if (ignore(el)) return;
    const target = metadata(el);
    if (!target) return;
    if (el instanceof HTMLSelectElement) {
      emit({action: 'select', ...target, field: el.name || el.id || 'selected_option'});
    } else if (el instanceof HTMLInputElement && ['checkbox', 'radio'].includes(el.type)) {
      if (el.type === 'radio') {
        if (el.checked) emit({action: 'check', checked: true, ...target});
      } else emit({action: 'check', checked: el.checked, ...target});
    } else if ((el instanceof HTMLInputElement && !['file','hidden','submit','button','reset','image'].includes(el.type)) || el instanceof HTMLTextAreaElement) {
      emit({action: 'fill', ...target, field: el.name || el.id || el.getAttribute('aria-label') || 'input', inputType: el.type || 'text'});
    }
  }, true);
  document.addEventListener('click', (ev) => {
    if (!ev.isTrusted) return; // Ignore app-generated synthetic clicks and downloads.
    const el = ev.target?.closest?.('button, a, input[type="submit"], input[type="button"], [role="button"]');
    if (!el || ignore(el)) return;
    const target = metadata(el);
    if (target) emit({action: 'click', ...target});
  }, true);
  function toolbar() {
    if (!document.body || document.getElementById('h2a-recorder-control')) return;
    const control = document.createElement('div');
    control.id = 'h2a-recorder-control';
    control.style.cssText = 'all:initial!important;position:fixed!important;z-index:2147483647!important;bottom:18px!important;right:18px!important;display:flex!important;align-items:center!important;gap:12px!important;background:#10182e!important;color:white!important;padding:12px 16px!important;border:1px solid #536184!important;border-radius:16px!important;box-shadow:0 12px 40px #0007!important;font:600 13px system-ui!important';
    const label = document.createElement('span');
    label.textContent = '● Human2API recording';
    label.style.cssText = 'color:#9ef3c7!important;font:600 13px system-ui!important';
    const stop = document.createElement('button');
    stop.textContent = 'Stop & save';
    stop.style.cssText = 'all:initial!important;cursor:pointer!important;background:#66f0ba!important;border-radius:9px!important;color:#08111f!important;padding:8px 12px!important;font:700 12px system-ui!important';
    stop.addEventListener('click', (event) => { event.stopPropagation(); emit({action: 'stop'}); });
    control.append(label, stop);
    document.body.appendChild(control);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', toolbar, {once:true});
  else toolbar();
})();
"""


def variable_name(name: str, used: set[str]) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:45]
    if not normalized or not normalized[0].isalpha():
        normalized = "field_" + (normalized or "value")
    candidate = normalized
    suffix = 2
    while candidate in used:
        candidate = (normalized[:50] + f"_{suffix}")
        suffix += 1
    return candidate


def workflow_from_events(name: str, description: str, start_url: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    if not NAME_RE.fullmatch(name):
        raise WorkflowError("invalid workflow name")
    # Never persist URLs' query strings or fragments, which may contain API keys.
    parts = urlsplit(start_url)
    scrubbed_url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    inputs: dict[str, Any] = {}
    fields: dict[str, str] = {}
    steps: list[dict[str, Any]] = []
    for event in events:
        action = event.get("action")
        if action not in {"click", "fill", "select", "check"}:
            continue
        selector = event.get("selector")
        if not isinstance(selector, str) or not selector:
            continue
        step = {"action": action, "selector": selector}
        fallbacks = event.get("alternatives")
        if isinstance(fallbacks, list) and fallbacks:
            step["alternatives"] = [s for s in fallbacks[:5] if isinstance(s, str) and s]
        if action in {"fill", "select"}:
            field = str(event.get("field") or "field")
            # Reuse the same input when a field is edited twice.
            if field not in fields:
                key = variable_name(field, set(inputs))
                fields[field] = key
                input_type = str(event.get("inputType", "text"))
                special = bool(re.search(r"password|token|secret|api.?key|card|cvv|pin|otp|auth", field, re.I))
                secret = special or input_type in {"password", "tel"}
                inputs[key] = {"type": "string", "description": f"Value for {field[:90]}", "required": True, "secret": secret}
            step["value"] = "{{" + fields[field] + "}}"
            # Neither recorded values nor browser text are ever transferred.
        elif action == "check":
            step["checked"] = bool(event.get("checked"))
        steps.append(step)
    if not steps:
        raise WorkflowError("no browser actions were recorded")
    from urllib.parse import urlparse
    return {
        "schemaVersion": 1,
        "name": name,
        "description": description,
        "startUrl": scrubbed_url,
        "permissions": "write",
        "allowedHosts": [urlparse(scrubbed_url).hostname],
        "inputs": inputs,
        "steps": steps,
    }


def record(url: str, *, name: str, output_dir: str | Path = "workflows", browser_path: str | None = None, headless: bool = False) -> Path:
    """Record the top-level tab until Stop & save is clicked or the tab closes."""
    from playwright.sync_api import sync_playwright
    from threading import Event

    destination = Path(output_dir) / f"{name}.json"
    if destination.exists():
        raise WorkflowError(f"workflow already exists: {destination}; choose a new name")
    done = Event()
    events: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = launch_browser(playwright, headless=headless, browser_path=browser_path)
        try:
            context = browser.new_context()
            page = context.new_page()
            def bridge(source: Any, payload: Any) -> None:
                if source.get("page") != page or source.get("frame") != page.main_frame:
                    return
                if not isinstance(payload, dict):
                    return
                if payload.get("action") == "stop":
                    done.set()
                    return
                if len(events) < 250:
                    events.append(payload)
            context.expose_binding("h2aBridge", bridge)
            context.add_init_script(script=RECORDER_SCRIPT)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Recording: interact with the Chromium window and press Stop & save.")
            while not done.is_set() and not page.is_closed():
                try:
                    page.wait_for_timeout(200)
                except Exception:
                    break
        finally:
            browser.close()
    description = f"Browser task recorded from {urlsplit(url).hostname}"
    destination = Path(output_dir) / f"{name}.json"
    if destination.exists():
        raise WorkflowError(f"workflow already exists: {destination}; choose a new name")
    workflow = workflow_from_events(name, description, url, events)
    return save_workflow(destination, workflow)
