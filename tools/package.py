"""Builds the release archive dist/Oblachko-v<version>.zip for end users.

    cd extension && npm run build && cd ..
    python tools/package.py [--tag v0.2.0]

Layout (everything under one Oblachko/ folder, which server/update.py expects):
    start.bat, VERSION, ИНСТРУКЦИЯ.txt
    server/   code, lock file, config example, updater (no models, caches or venv)
    extension/  the built extension, loaded in Chrome as an unpacked extension
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_FILES = ["pyproject.toml", "uv.lock", "config.example.toml", "update.py"]
SERVER_DIRS = ["app", "scripts"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="git tag being released; must match VERSION")
    args = parser.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if args.tag and args.tag.lstrip("v") != version:
        sys.exit(f"tag {args.tag} does not match VERSION {version}")
    ext = ROOT / "extension" / "dist"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != version:
        sys.exit(f"extension/dist is version {manifest['version']}, VERSION is {version}: run npm run build")

    out = ROOT / "dist" / f"Oblachko-v{version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:

        def add(path: Path, name: str) -> None:
            zf.write(path, f"Oblachko/{name}")

        add(ROOT / "VERSION", "VERSION")
        add(ROOT / "start.bat", "start.bat")
        add(ROOT / "tools" / "release-readme.txt", "ИНСТРУКЦИЯ.txt")
        for name in SERVER_FILES:
            add(ROOT / "server" / name, f"server/{name}")
        for name in SERVER_DIRS:
            for path in sorted((ROOT / "server" / name).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    add(path, path.relative_to(ROOT).as_posix())
        for path in sorted(ext.rglob("*")):
            if path.is_file():
                add(path, f"extension/{path.relative_to(ext).as_posix()}")

    print(f"{out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
