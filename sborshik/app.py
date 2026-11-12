"""«Сборщик баз»: запуск локального сервера и окна приложения."""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

import config


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Не удалось найти свободный порт.")


def wait_ready(url: str, timeout: float = 20) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/", timeout=1)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def say(text: str) -> None:
    if sys.stdout:  # в .exe без консоли stdout отсутствует
        print(text, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=config.APP_NAME)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-window", action="store_true", help="только сервер, без окна (открыть в браузере вручную)")
    args = parser.parse_args()

    log = config.setup_logging()
    import api  # импорт после настройки журнала

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, daemon=True, name="server")
    thread.start()
    if not wait_ready(url):
        log.error("сервер не запустился")
        sys.exit("Не удалось запустить приложение. Подробности в журнале: " + str(config.user_dir() / "sborshik.log"))
    log.info("приложение запущено: %s", url)

    def shutdown() -> None:
        api.collector.stop()
        api.collector.join(15)
        server.should_exit = True

    if args.no_window:
        say(f"{config.APP_NAME}: откройте {url}")
        try:
            thread.join()
        except KeyboardInterrupt:
            shutdown()
        return
    try:
        import webview
    except ImportError:
        webview = None
    if webview is None:
        say(f"Модуль pywebview не установлен — открываю в обычном браузере: {url}")
        webbrowser.open(url)
        try:
            thread.join()
        except KeyboardInterrupt:
            shutdown()
        return
    webview.create_window(config.APP_NAME, url, width=1360, height=820, min_size=(1100, 660), background_color="#14161a")
    webview.start()
    shutdown()


if __name__ == "__main__":
    main()
