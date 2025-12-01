import os
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKAGES = [
    "core",
    "data",
    "export",
    "fonts",
    "knowledge",
    "models",
    "ocr",
    "project",
    "resources",
    "translator",
    "ui",
]


def iter_python_files():
    for pkg in PACKAGES:
        pkg_path = ROOT / pkg
        if not pkg_path.exists():
            continue
        for root, _, files in os.walk(pkg_path):
            for name in files:
                if name.endswith(".py"):
                    yield Path(root) / name
    for name in ("main.py", "config.py", "i18n.py", "languages.py", "settings_manager.py"):
        path = ROOT / name
        if path.exists():
            yield path


def main() -> int:
    failed = []
    for path in iter_python_files():
        rel = path.relative_to(ROOT)
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as e:  # noqa: BLE001
            failed.append((rel, e))
    if failed:
        print("Py-compile failed for the following files:")
        for rel, e in failed:
            print(f" - {rel}: {e}")
        return 1
    print("All target modules compiled successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
