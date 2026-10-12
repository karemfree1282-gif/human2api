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
      try { const matches = document.querySelectorAll(sel); return matches.length === 1 && matches[0] === el; } catch (_) { return false; }
    });
  };
  const emit = (msg) => { try { window.h2aBridge(msg).catch(() => {}); } catch (_) {} };
  const ignore = (node) => !node || node.closest?.('#h2a-recorder-control');
  const metadata = (el) => {
    const selectors = preferred(el);
    if (!selectors.length) return null;
    const label = el.getAttribute('aria-label') || '';
    const role = el.getAttribute('role') || (el.tagName === 'BUTTON' ? 'button' : '');
    return {selector: selectors[0], alternatives: selectors.slice(1, 6), ...(label ? {label:label.slice(0,150)} : {}), ...(role ? {role:role.slice(0,70)} : {})};
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
    active_tab = 0
    for event in events:
        action = event.get("action")
        if action == "switch_tab":
            index = event.get("index")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 20:
                steps.append({"action": "switch_tab", "index": index})
                active_tab = index
            continue
        if action not in {"click", "fill", "select", "check"}:
            continue
        selector = event.get("selector")
        if not isinstance(selector, str) or not selector:
            continue
        step = {"action": action, "selector": selector}
        frame = event.get("frame")
        if isinstance(frame, str) and frame:
            step["frame"] = frame[:2048]
        frames = event.get("frames")
        if isinstance(frames, list) and frames and all(isinstance(x, str) and x for x in frames):
            step["frames"] = frames
        for hint in ("label", "role"):
            if isinstance(event.get(hint), str) and 0 < len(event[hint]) < 150:
                step[hint] = event[hint]
        fallbacks = event.get("alternatives")
        if isinstance(fallbacks, list) and fallbacks:
            step["alternatives"] = [s for s in fallbacks[:5] if isinstance(s, str) and s]
        if action in {"fill", "select"}:
            field = str(event.get("field") or "field")
            # Reuse the same input when a field is edited twice.
            identity = json.dumps([active_tab, step.get("frames", [step.get("frame", "")]), selector, field])
            if identity not in fields:
                key = variable_name(field, set(inputs))
                fields[identity] = key
                input_type = str(event.get("inputType", "text"))
                special = bool(re.search(r"password|token|secret|api.?key|card|cvv|pin|otp|auth", field, re.I))
                secret = special or input_type in {"password", "tel"}
                inputs[key] = {"type": "string", "description": f"Value for {field[:90]}", "required": True, "secret": secret}
            step["value"] = "{{" + fields[identity] + "}}"
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
    recording_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = launch_browser(playwright, headless=headless, browser_path=browser_path)
        try:
            context = browser.new_context()
            page = context.new_page()
            tabs = [page]
            active_tab = 0
            def bridge(source: Any, payload: Any) -> None:
                nonlocal active_tab
                tab = source.get("page")
                frame = source.get("frame")
                if not isinstance(payload, dict) or tab is None or frame is None:
                    return
                if payload.get("action") == "stop":
                    done.set()
                    return
                if tab not in tabs:
                    tabs.append(tab)
                index = tabs.index(tab)
                if index != active_tab and len(events) < 248:
                    events.append({"action": "switch_tab", "index": index})
                    active_tab = index
                if frame != tab.main_frame:
                    try:
                        chain = []
                        current = frame
                        while current != tab.main_frame:
                            if len(chain) >= 10 or current.parent_frame is None:
                                raise WorkflowError("iframe depth exceeds supported bound")
                            iframe = current.frame_element()
                            selector = None
                            for attribute in ("id", "name"):
                                value = iframe.get_attribute(attribute)
                                if value and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
                                    proposed = "iframe[" + attribute + "=" + json.dumps(value) + "]"
                                    if current.parent_frame.locator(proposed).count() == 1:
                                        selector = proposed
                                        break
                            if selector is None:
                                raise WorkflowError("iframe requires a unique stable id or name")
                            chain.insert(0, selector)
                            current = current.parent_frame
                        payload["frame" if len(chain) == 1 else "frames"] = chain[0] if len(chain) == 1 else chain
                    except Exception:
                        recording_errors.append("An iframe action could not be addressed safely; no partial recording was saved")
                        done.set()
                        return
                if len(events) < 250:
                    events.append(payload)
                else:
                    recording_errors.append("Recording exceeded 250 actions; split it into smaller workflows")
                    done.set()
            context.expose_binding("h2aBridge", bridge)
            context.add_init_script(script=RECORDER_SCRIPT)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Recording: interact with the Chromium window and press Stop & save.")
            while not done.is_set() and any(not p.is_closed() for p in context.pages):
                try:
                    open_pages = [tab for tab in context.pages if not tab.is_closed()]
                    if open_pages:
                        open_pages[0].wait_for_timeout(200)
                except Exception:
                    break
        finally:
            browser.close()
    if recording_errors:
        raise WorkflowError(recording_errors[0])
    description = f"Browser task recorded from {urlsplit(url).hostname}"
    destination = Path(output_dir) / f"{name}.json"
    if destination.exists():
        raise WorkflowError(f"workflow already exists: {destination}; choose a new name")
    workflow = workflow_from_events(name, description, url, events)
    return save_workflow(destination, workflow)
