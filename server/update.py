"""Self-update from GitHub releases, run by start.bat before the server starts.

Standard library only: it runs before `uv sync`, so it can't rely on the project's packages.
Replaces the program files (server code, extension, start.bat) with the latest release and keeps
the user's data: config.toml, downloaded models, caches and the glossary.
A git checkout is never touched: developers update with git.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "BasteArima/Oblachko"
ROOT = Path(__file__).resolve().parent.parent
# Program files inside the release archive; everything else under server/ is user data
REPLACE_DIRS = ["extension", "server/app", "server/scripts"]
REPLACE_FILES = ["VERSION", "ИНСТРУКЦИЯ.txt", "server/pyproject.toml", "server/uv.lock", "server/config.example.toml", "server/update.py"]


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().lstrip("v").split("."))


def latest_release() -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "oblachko-updater"},
    )
    with urllib.request.urlopen(request, timeout=15) as resp:
        return json.load(resp)


def install(src: Path) -> None:
    for rel in REPLACE_DIRS:
        if (src / rel).is_dir():
            shutil.rmtree(ROOT / rel, ignore_errors=True)
            shutil.copytree(src / rel, ROOT / rel)
    for rel in REPLACE_FILES:
        if (src / rel).is_file():
            shutil.copy2(src / rel, ROOT / rel)
    # start.bat is running right now: cmd reads it as it goes, so it swaps itself in on the next line it runs
    if (src / "start.bat").is_file():
        shutil.copy2(src / "start.bat", ROOT / "start.bat.new")


def main() -> None:
    if (ROOT / ".git").exists():
        print("Oblachko: git-репозиторий, автообновление пропущено.")
        return
    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    try:
        release = latest_release()
    except urllib.error.HTTPError as exc:
        reason = "релизов ещё нет" if exc.code == 404 else f"GitHub ответил {exc.code}"
        print(f"Oblachko {current}: обновлений нет ({reason}).")
        return
    except Exception as exc:  # noqa: BLE001 - offline or GitHub down: just run what we have
        print(f"Oblachko {current}: не удалось проверить обновления ({exc}).")
        return

    latest = release["tag_name"].lstrip("v")
    if version_tuple(latest) <= version_tuple(current):
        print(f"Oblachko {current}: установлена последняя версия.")
        return
    asset = next((a for a in release.get("assets", []) if a["name"].endswith(".zip")), None)
    if asset is None:
        print(f"Вышла версия {latest}, но в релизе нет архива.")
        return

    print(f"Обновляю Oblachko {current} -> {latest}...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset["name"]
        with urllib.request.urlopen(asset["browser_download_url"], timeout=120) as resp, open(archive, "wb") as out:
            shutil.copyfileobj(resp, out)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tmp)
        install(Path(tmp) / "Oblachko")
    print(f"Готово: Oblachko {latest}. Расширение в Chrome перезагрузится само.")
    notes = (release.get("body") or "").strip()
    if notes:
        print("\nЧто нового:\n" + notes + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a failed update must never stop the server from starting
        print(f"Обновление не удалось: {exc}", file=sys.stderr)
