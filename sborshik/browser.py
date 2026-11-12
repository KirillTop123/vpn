"""Один видимый браузер Chromium под управлением Playwright."""
from __future__ import annotations

import os

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

import config


class BrowserError(Exception):
    pass


class Browser:
    """Одно окно, одна вкладка. Профиль сохраняется между запусками,
    поэтому решённая капча и согласия с cookies не спрашиваются заново."""

    def __init__(self, settings: dict):
        self.settings = settings
        self._pw = None
        self._context = None
        self.page = None

    def start(self) -> None:
        self._pw = sync_playwright().start()
        profile = config.user_dir() / "browser-profile"
        headless = os.environ.get("SBORSHIK_HEADLESS") == "1"
        choice = self.settings.get("browser") or "auto"
        attempts = [choice] if choice != "auto" else ["chromium", "msedge", "chrome"]
        errors = []
        for name in attempts:
            options: dict = {"headless": headless, "locale": "ru-RU", "viewport": {"width": 1280, "height": 860}}
            if name != "chromium":
                options["channel"] = name
            elif os.environ.get("SBORSHIK_CHROMIUM"):
                options["executable_path"] = os.environ["SBORSHIK_CHROMIUM"]
            try:
                self._context = self._pw.chromium.launch_persistent_context(str(profile), **options)
                break
            except PlaywrightError as exc:
                errors.append(f"{name}: {str(exc).splitlines()[0]}")
        if self._context is None:
            self.stop()
            raise BrowserError(
                "Не удалось запустить браузер. Установите Google Chrome или Microsoft Edge "
                "либо выполните команду «playwright install chromium». Подробности: " + "; ".join(errors)
            )
        self._context.set_default_timeout(int(self.settings.get("page_timeout", 45)) * 1000)
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def stop(self) -> None:
        for closer in (getattr(self._context, "close", None), getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:  # браузер могли закрыть вручную
                pass
        self._context = self._pw = self.page = None
