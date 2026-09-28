"""uv run python -m app"""

import logging
import sys

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


if __name__ == "__main__":
    disable_quick_edit()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Every LLM call and Hugging Face check would otherwise be an INFO line
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings()
    # No line per HTTP request: the worker logs one line per translated page instead
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="info", access_log=False)
