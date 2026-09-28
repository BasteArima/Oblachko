"""uv run python -m app"""

import json
import logging
import socket
import sys
import urllib.request

import uvicorn

from .config import load_settings


def disable_quick_edit() -> None:
    """A click into the console window starts text selection (QuickEdit mode, on by default),
    and while it lasts every write to the console blocks: the server stops answering until
    Enter or Esc is pressed, with the window still open. Turn it off for this console."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(stdin, ctypes.byref(mode)):  # fails when not attached to a console
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        kernel32.SetConsoleMode(stdin, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)


def port_taken_message(host: str, port: int) -> str | None:
    """Checked before loading the models: a second start.bat window would otherwise load
    everything and only then fail with a bind error."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex((host, port)) != 0:
            return None
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=5) as resp:
            if json.load(resp).get("ok"):
                return f"Сервер Oblachko уже запущен на {host}:{port} (в другом окне). Второй не нужен: пользуйтесь тем."
    except Exception:  # noqa: BLE001 - whatever answers there, it isn't Oblachko
        pass
    return f"Порт {port} занят другой программой. Закройте её или поменяйте port в server\\config.toml (и адрес сервера в попапе расширения)."


if __name__ == "__main__":
    disable_quick_edit()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Every LLM call and Hugging Face check would otherwise be an INFO line
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings()
    taken = port_taken_message(settings.host, settings.port)
    if taken:
        print(taken)
        sys.exit(1)
    # No line per HTTP request: the worker logs one line per translated page instead
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="info", access_log=False)
