"""Run the existing FunPay Vertex engine as a child process for the desktop UI.

The desktop process communicates with this process through prefixed JSON lines
on stdout. All Vertex network polling and background threads stay isolated
from the Qt event loop.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

PROTOCOL_PREFIX = "FPV_DESKTOP:"


def emit(payload: dict[str, Any]) -> None:
    """Write one machine-readable status message for the parent process."""
    print(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


def _prepare_working_tree(root: Path) -> None:
    os.chdir(root)
    for folder in (
        "configs",
        "logs",
        "storage",
        "storage/cache",
        "storage/plugins",
        "storage/products",
        "plugins",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)

    for file_name in ("configs/auto_response.cfg", "configs/auto_delivery.cfg"):
        path = root / file_name
        path.touch(exist_ok=True)


def _register_desktop_events(vertex: Any) -> None:
    """Forward a small set of engine events to the desktop activity feed."""
    module = ModuleType("desktop_event_bridge")
    bindings = {
        "BIND_TO_NEW_ORDER": "Новый заказ",
        "BIND_TO_NEW_MESSAGE": "Новое сообщение",
        "BIND_TO_LAST_CHAT_MESSAGE_CHANGED": "Обновилось сообщение в чате",
        "BIND_TO_ORDER_STATUS_CHANGED": "Изменился статус заказа",
        "BIND_TO_POST_DELIVERY": "Выполнена автовыдача",
        "BIND_TO_POST_LOTS_RAISE": "Лоты подняты",
    }

    for binding_name, title in bindings.items():
        def handler(_vertex: Any, *event_data: Any, event_title: str = title) -> None:
            # Vertex hook families do not all use the same callback signature:
            # event hooks pass (vertex, event), while lots-raise hooks pass
            # (vertex, category, message). We intentionally expose no payload.
            first = event_data[0] if event_data else None
            emit({
                "type": "activity",
                "title": event_title,
                "event": type(first).__name__ if first is not None else "VertexHook",
            })

        setattr(module, binding_name, [handler])

    vertex.add_handlers_from_plugin(module)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    _prepare_working_tree(root)

    config_path = root / "configs" / "_main.cfg"
    if not config_path.is_file():
        emit({
            "type": "setup_required",
            "message": "Не найден configs/_main.cfg. Сначала запусти Start.bat и заверши первичную настройку Vertex.",
        })
        return 2

    try:
        from Utils.logger import configure_logging
        import Utils.config_loader as config_loader
        from vertex import Vertex

        configure_logging()

        emit({"type": "initializing"})
        main_config = config_loader.load_main_config("configs/_main.cfg")
        auto_response_config = config_loader.load_auto_response_config("configs/auto_response.cfg")
        raw_auto_response_config = config_loader.load_raw_auto_response_config("configs/auto_response.cfg")
        auto_delivery_config = config_loader.load_auto_delivery_config("configs/auto_delivery.cfg")

        # Keep the upstream engine version passed to its own runtime.
        vertex = Vertex(
            main_config,
            auto_delivery_config,
            auto_response_config,
            raw_auto_response_config,
            "2.0.0",
        ).init()

        _register_desktop_events(vertex)
        profile = getattr(vertex, "profile", None)
        lots_count = len(profile.get_lots()) if profile else 0
        emit({
            "type": "connected",
            "username": getattr(vertex.account, "username", None) or "FunPay",
            "lots_count": lots_count,
        })

        # run() owns the event loop and returns only when the engine stops.
        vertex.run()
        emit({"type": "engine_stopped"})
        return 0
    except KeyboardInterrupt:
        emit({"type": "engine_stopped"})
        return 0
    except Exception as exc:
        # Do not forward arbitrary exception text: it can contain request data.
        emit({
            "type": "engine_error",
            "message": f"Ошибка запуска: {type(exc).__name__}. Подробности см. в logs/log.log.",
        })
        try:
            import logging
            logging.getLogger("desktop").exception("Desktop engine startup failed")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
