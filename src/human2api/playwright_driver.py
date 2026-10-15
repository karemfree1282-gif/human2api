"""Small Selenium-compatible surface backed by locally installed Playwright.

This keeps the existing workflow runner working when ChromeDriver/Selenium is not
available. Only methods used by Human2API are implemented; no remote browser or
provider API is involved.
"""

from __future__ import annotations

import pathlib
import re
import os
import shutil
from typing import Any, Optional


class PlaywrightElement:
    def __init__(self, handle: Any):
        self.handle = handle

    def get_attribute(self, name: str) -> Optional[str]:
        # WebDriver's get_attribute('value') reads the live DOM property, not
        # only the initial HTML attribute (which is often absent after typing).
        if name == "value":
            value = self.handle.evaluate("element => element.value ?? null")
            return str(value) if value is not None else None
        return self.handle.get_attribute(name)

    @property
    def text(self) -> str:
        return self.handle.inner_text()

    @property
    def tag_name(self) -> str:
        return self.handle.evaluate("element => element.tagName.toLowerCase()")

    def is_displayed(self) -> bool:
        return self.handle.is_visible()

    def is_enabled(self) -> bool:
        return self.handle.is_enabled()

    def click(self) -> None:
        self.handle.click(timeout=10000)

    def clear(self) -> None:
        self.handle.fill("")

    def send_keys(self, value: str) -> None:
        if self.get_attribute("type") == "file":
            self.handle.set_input_files(str(pathlib.Path(value).resolve()))
        else:
            # Match Selenium clear()+send_keys(), without appending old input.
            self.handle.fill(value)

    def select_by_value(self, value: str) -> None:
        try:
            self.handle.select_option(value=value)
        except Exception:
            self.handle.select_option(label=value)


class _Switcher:
    def __init__(self, driver: "PlaywrightDriver") -> None:
        self.driver = driver

    def default_content(self) -> None:
        self.driver._frame = self.driver._page.main_frame

    def frame(self, element: PlaywrightElement) -> None:
        new_frame = element.handle.content_frame()
        if new_frame is None:
            raise RuntimeError("The selected element does not contain an iframe")
        self.driver._frame = new_frame

    def window(self, handle: str) -> None:
        matching = next((p for p in self.driver._context.pages if str(id(p)) == str(handle)), None)
        if matching is None:
            raise RuntimeError("Unknown or closed browser tab")
        self.driver._page = matching
        self.default_content()

    def new_window(self, kind: str = "tab") -> None:
        self.driver._page = self.driver._context.new_page()
        self.default_content()


class PlaywrightDriver:
    """Adapter for the runner's existing WebDriver-shaped calls."""

    def __init__(self, downloads_dir: pathlib.Path, headless: bool = True) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Browser automation requires Playwright or Selenium. Install: "
                'python -m pip install -e ".[browser]"'
            ) from exc

        self._playwright = sync_playwright().start()
        self._browser = None
        try:
            executable = next(
                (p for p in (shutil.which("chromium"), shutil.which("chromium-browser"),
                             shutil.which("google-chrome")) if p),
                None,
            )
            browser_args = ["--disable-dev-shm-usage"]
            # Do not turn off Chromium's OS sandbox for ordinary users.
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                browser_args.append("--no-sandbox")
            opts: dict[str, Any] = {"headless": headless, "args": browser_args}
            if executable:
                opts["executable_path"] = executable
            try:
                self._browser = self._playwright.chromium.launch(**opts)
            except Exception as exc:
                raise RuntimeError(
                    "Chromium failed to launch. Install Chromium with "
                    '`python -m playwright install chromium` and retry. '
                    f"Details: {exc}"
                ) from exc
            self._context = self._browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
            self._page = self._context.new_page()
            self._frame = self._page.main_frame
            self.switch_to = _Switcher(self)
            self._download_dir = pathlib.Path(downloads_dir)
            self._context.on("page", lambda page: page.on("download", self._handle_download))
            self._page.on("download", self._handle_download)
        except BaseException:
            self.quit()
            raise

    def _handle_download(self, download: Any) -> None:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        name = pathlib.Path(download.suggested_filename).name
        # Browsers must never write to arbitrary folders based on a webpage.
        if name and name not in (".", ".."):
            download.save_as(self._download_dir / name)

    @property
    def current_url(self) -> str:
        return self._page.url

    @property
    def title(self) -> str:
        return self._page.title()

    @property
    def window_handles(self) -> list[str]:
        return [str(id(p)) for p in self._context.pages if not p.is_closed()]

    @property
    def current_window_handle(self) -> str:
        return str(id(self._page))

    def get(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
        self._frame = self._page.main_frame

    def set_page_load_timeout(self, seconds: float) -> None:
        self._page.set_default_navigation_timeout(seconds * 1000)

    def find_elements(self, by: str, value: str) -> list[PlaywrightElement]:
        if by in ("tag name", "tag_name"):
            by = "css selector"
        if by in ("xpath", "XPATH"):
            value = f"xpath={value}"
        elif by not in ("css selector", "css_selector"):
            raise ValueError(f"Unsupported element locator: {by}")
        return [PlaywrightElement(h) for h in self._frame.query_selector_all(value)]

    def find_element(self, by: str, value: str) -> PlaywrightElement:
        els = self.find_elements(by, value)
        if not els:
            raise LookupError(f"Element not found: {by}={value}")
        return els[0]

    def find_by_role(self, role: str, name: str = "") -> list[PlaywrightElement]:
        if name:
            locator = self._frame.get_by_role(role, name=re.compile(re.escape(name), re.IGNORECASE))
        else:
            locator = self._frame.get_by_role(role)
        return [PlaywrightElement(h) for h in locator.element_handles()]

    def execute_script(self, script: str, *args: Any) -> Any:
        wrapped_args = [arg.handle if isinstance(arg, PlaywrightElement) else arg for arg in args]
        # Playwright requires a callable expression; expose WebDriver's arguments.
        expr = "args => { const arguments = args; " + script + "\n}"
        return self._frame.evaluate(expr, wrapped_args)

    def execute_cdp_cmd(self, command: str, parameters: dict[str, Any]) -> Any:
        if command == "Target.closeTarget":
            self._page.close()
            return {"success": True}
        raise NotImplementedError(command)

    def quit(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            self._playwright.stop()
