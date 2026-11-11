"""Run Vertex in a child process and expose a small JSON-lines desktop bridge."""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PROTOCOL_PREFIX = "FPV_DESKTOP:"
_OUTPUT_LOCK = threading.Lock()


def emit(payload: dict[str, Any]) -> None:
    with _OUTPUT_LOCK:
        print(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def _value(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "name", value))


def serialize_order(order: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(order, "id", "")),
        "buyer": getattr(order, "buyer_username", None) or "",
        "description": getattr(order, "description", None) or "",
        "price": getattr(order, "price", None),
        "currency": _value(getattr(order, "currency", None)),
        "status": _value(getattr(order, "status", None)),
        "date": getattr(order, "date", None).isoformat(sep=" ", timespec="minutes")
                if isinstance(getattr(order, "date", None), (datetime, date)) else "",
        "chat_id": str(getattr(order, "chat_id", "")),
    }


def serialize_chat(chat: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(chat, "id", "")),
        "name": getattr(chat, "name", None) or "Пользователь",
        "last_message": getattr(chat, "last_message_text", None) or "",
        "unread": bool(getattr(chat, "unread", False)),
    }


def serialize_message(message: Any) -> dict[str, Any]:
    return {
        "id": str(getattr(message, "id", "")),
        "text": getattr(message, "text", None) or "",
        "image": getattr(message, "image_link", None) or "",
        "author": getattr(message, "author", None) or "Система",
        "author_id": getattr(message, "author_id", None),
        "by_bot": bool(getattr(message, "by_bot", False)),
        "by_vertex": bool(getattr(message, "by_vertex", False)),
    }


def _prepare_working_tree(root: Path) -> None:
    os.chdir(root)
    for folder in ("configs", "logs", "storage", "storage/cache", "storage/plugins",
                   "storage/products", "plugins"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for file_name in ("configs/auto_response.cfg", "configs/auto_delivery.cfg"):
        (root / file_name).touch(exist_ok=True)


def _register_desktop_events(vertex: Any) -> None:
    """Forward engine event data without exposing HTML, cookies, or credentials."""
    module = ModuleType("desktop_event_bridge")

    def order_handler(_vertex: Any, event: Any) -> None:
        order = getattr(event, "order", None)
        if order is not None:
            emit({"type": "order_event", "order": serialize_order(order),
                  "event": type(event).__name__})

    def chat_handler(_vertex: Any, event: Any) -> None:
        chat = getattr(event, "chat", None)
        if chat is not None:
            emit({"type": "chat_event", "chat": serialize_chat(chat),
                  "event": type(event).__name__})

    def message_handler(_vertex: Any, event: Any) -> None:
        message = getattr(event, "message", None)
        if message is not None:
            emit({"type": "message_event", "message": serialize_message(message),
                  "chat_id": str(getattr(message, "chat_id", "")),
                  "chat_name": getattr(message, "chat_name", None) or ""})

    def orders_changed(_vertex: Any, event: Any) -> None:
        emit({"type": "activity", "title": "Список заказов обновлён",
              "event": type(event).__name__})
        emit({"type": "refresh", "target": "orders"})

    def chats_changed(_vertex: Any, event: Any) -> None:
        emit({"type": "activity", "title": "Список чатов обновлён",
              "event": type(event).__name__})
        emit({"type": "refresh", "target": "chats"})

    def lots_raised(_vertex: Any, *event_data: Any) -> None:
        emit({"type": "activity", "title": "Событие поднятия лота"})

    module.BIND_TO_INIT_ORDER = [order_handler]
    module.BIND_TO_NEW_ORDER = [order_handler]
    module.BIND_TO_ORDER_STATUS_CHANGED = [order_handler]
    module.BIND_TO_INIT_MESSAGE = [chat_handler]
    module.BIND_TO_LAST_CHAT_MESSAGE_CHANGED = [chat_handler]
    module.BIND_TO_NEW_MESSAGE = [message_handler]
    module.BIND_TO_ORDERS_LIST_CHANGED = [orders_changed]
    module.BIND_TO_MESSAGES_LIST_CHANGED = [chats_changed]
    module.BIND_TO_POST_LOTS_RAISE = [lots_raised]
    vertex.add_handlers_from_plugin(module)


def _handle_command(vertex: Any, command: dict[str, Any]) -> dict[str, Any]:
    action = command.get("action")
    account = vertex.account

    if action == "get_orders":
        _next, orders, _locale, _subcategories = account.get_sales(
            include_paid=True, include_closed=True, include_refunded=True
        )
        return {"orders": [serialize_order(order) for order in orders]}

    if action == "get_chats":
        chats = account.get_chats(update=True)
        return {"chats": [serialize_chat(chat) for chat in chats.values()]}

    if action == "get_chat_history":
        chat_id = command.get("chat_id")
        if not chat_id:
            raise ValueError("Не указан ID чата")
        chat = account.get_chat_by_id(int(chat_id), make_request=False)
        chat_name = getattr(chat, "name", None) if chat else command.get("chat_name")
        messages = account.get_chat_history(int(chat_id), interlocutor_username=chat_name)
        return {"chat_id": str(chat_id), "messages": [serialize_message(m) for m in messages]}

    if action == "send_message":
        chat_id = command.get("chat_id")
        message_text = command.get("text", "")
        if not chat_id or not isinstance(message_text, str) or not message_text.strip():
            raise ValueError("Укажи чат и непустое сообщение")
        chat = account.get_chat_by_id(int(chat_id), make_request=False)
        chat_name = getattr(chat, "name", None) if chat else None
        sent = account.send_message(int(chat_id), message_text, chat_name=chat_name)
        return {"message": serialize_message(sent), "chat_id": str(chat_id)}

    raise ValueError(f"Неизвестная команда: {action}")


def _command_loop(vertex: Any) -> None:
    """Read commands from the GUI without blocking Vertex's event listener."""
    for raw_line in sys.stdin:
        try:
            command = json.loads(raw_line)
            request_id = command.get("request_id")
            try:
                result = _handle_command(vertex, command)
                emit({"type": "response", "request_id": request_id,
                      "action": command.get("action"), "ok": True, "data": result})
            except Exception as exc:
                emit({"type": "response", "request_id": request_id,
                      "action": command.get("action"), "ok": False,
                      "error": f"{type(exc).__name__}: {exc}"})
        except json.JSONDecodeError:
            emit({"type": "protocol_error", "message": "Некорректная команда desktop-клиента"})


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    _prepare_working_tree(root)

    if not (root / "configs" / "_main.cfg").is_file():
        emit({"type": "setup_required",
              "message": "Не найден configs/_main.cfg. Сначала выполни первичную настройку Vertex."})
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

        vertex = Vertex(main_config, auto_delivery_config, auto_response_config,
                        raw_auto_response_config, "2.0.0")
        _register_desktop_events(vertex)
        vertex.init()

        profile = getattr(vertex, "profile", None)
        lots_count = len(profile.get_lots()) if profile else 0
        emit({"type": "connected",
              "username": getattr(vertex.account, "username", None) or "FunPay",
              "lots_count": lots_count})

        threading.Thread(target=_command_loop, args=(vertex,), daemon=True,
                         name="desktop-command-loop").start()
        vertex.run()
        emit({"type": "engine_stopped"})
        return 0
    except KeyboardInterrupt:
        emit({"type": "engine_stopped"})
        return 0
    except Exception as exc:
        emit({"type": "engine_error",
              "message": f"Ошибка запуска: {type(exc).__name__}. Подробности см. в logs/log.log."})
        try:
            import logging
            logging.getLogger("desktop").exception("Desktop engine startup failed")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
