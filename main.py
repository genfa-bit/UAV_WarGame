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
    from ui.qt_app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
