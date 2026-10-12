"""Default PySide6/QML entry point with lazy Pygame compatibility exports."""

from __future__ import annotations

_PYGAME_COMPAT_EXPORTS = {
    "create_deployment",
    "handle_deployment_event",
    "handle_runtime_key",
    "pygame",
}


def __getattr__(name: str):
    if name not in _PYGAME_COMPAT_EXPORTS:
        raise AttributeError(name)
    import pygame_main

    value = getattr(pygame_main, name)
    globals()[name] = value
    return value


def main() -> int:
    import sys
    try:
        from ui.qt_app import run
        return run()
    except Exception:
        if "--smoke-test" not in sys.argv:
            raise
        # Windowed executables have no console. Make startup failures available
        # to release checks without waiting for a hidden traceback dialog.
        import json
        import traceback
        from pathlib import Path
        if "--smoke-report" in sys.argv:
            index = sys.argv.index("--smoke-report")
            if index + 1 < len(sys.argv):
                report_path = Path(sys.argv[index + 1])
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps({
                    "ok": False, "frozen": bool(getattr(sys, "frozen", False)),
                    "checks": [], "error": traceback.format_exc(),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
