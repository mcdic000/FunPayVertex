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
    order_date = getattr(order, "date", None)
    if isinstance(order_date, datetime):
        order_date_text = order_date.isoformat(sep=" ", timespec="minutes")
    elif isinstance(order_date, date):
        order_date_text = order_date.isoformat()
    else:
        order_date_text = ""
    return {
        "id": str(getattr(order, "id", "")),
        "buyer": getattr(order, "buyer_username", None) or "",
        "description": getattr(order, "description", None) or "",
        "price": getattr(order, "price", None),
        "currency": _value(getattr(order, "currency", None)),
        "status": _value(getattr(order, "status", None)),
        "date": order_date_text,
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




def serialize_lot(lot: Any) -> dict[str, Any]:
    subcategory = getattr(lot, "subcategory", None)
    return {
        "id": str(getattr(lot, "id", "")),
        "title": getattr(lot, "description", None) or getattr(lot, "title", None) or "",
        "server": getattr(lot, "server", None) or "",
        "side": getattr(lot, "side", None) or "",
        "amount": getattr(lot, "amount", None),
        "price": getattr(lot, "price", None),
        "currency": _value(getattr(lot, "currency", None)),
        "active": bool(getattr(lot, "active", True)),
        "auto": bool(getattr(lot, "auto", False)),
        "subcategory": (
            getattr(subcategory, "fullname", None)
            or getattr(subcategory, "name", None)
            or "Без категории"
        ),
        "subcategory_id": getattr(subcategory, "id", None),
        "subcategory_type": _value(getattr(subcategory, "type", None)).upper(),
        "public_link": getattr(lot, "public_link", "") or "",
    }


def _refresh_profile(vertex: Any) -> list[dict[str, Any]]:
    """Refresh the public profile and enrich it with the owner's private trade pages."""
    account = vertex.account
    previous_profile = getattr(vertex, "profile", None)
    profile = account.get_user(account.id)
    vertex.profile = profile
    if hasattr(vertex, "curr_profile"):
        vertex.curr_profile = profile

    lots_by_id = {str(lot.id): serialize_lot(lot) for lot in profile.get_lots()}
    profiles = [profile] + ([previous_profile] if previous_profile is not None else [])
    common_subcategories: dict[int, Any] = {}
    currency_subcategories: dict[int, Any] = {}
    for source_profile in profiles:
        for lot in source_profile.get_lots():
            subcategory = getattr(lot, "subcategory", None)
            if subcategory is None:
                continue
            subcategory_id = getattr(subcategory, "id", None)
            if subcategory_id is None:
                continue
            kind = _value(getattr(subcategory, "type", None)).upper()
            if kind == "COMMON":
                common_subcategories[int(subcategory_id)] = subcategory
            elif kind == "CURRENCY":
                currency_subcategories[int(subcategory_id)] = subcategory

    # Private trade pages also show paused standard listings.
    for subcategory_id in sorted(common_subcategories):
        try:
            owned_lots = account.get_my_subcategory_lots(subcategory_id)
        except Exception:
            continue
        for lot in owned_lots:
            lots_by_id[str(lot.id)] = serialize_lot(lot)

    # ChipFields is the supported edit surface for currency offers and contains
    # the full set of offers in each currency subcategory, including inactive ones.
    for subcategory_id, subcategory in currency_subcategories.items():
        try:
            chip_fields = account.get_chip_fields(subcategory_id)
        except Exception:
            continue
        for offer in chip_fields.chip_offers.values():
            lot_id = str(offer.lot_id)
            current = lots_by_id.get(lot_id, {})
            lots_by_id[lot_id] = {
                **current,
                "id": lot_id,
                "title": current.get("title") or "Валютное предложение",
                "server": current.get("server", ""),
                "side": current.get("side", ""),
                "amount": offer.amount,
                "price": offer.price,
                "currency": current.get("currency") or _value(account.currency),
                "active": bool(offer.active),
                "auto": False,
                "subcategory": current.get("subcategory") or
                    getattr(subcategory, "fullname", None) or
                    getattr(subcategory, "name", None) or "Валюта",
                "subcategory_id": subcategory_id,
                "subcategory_type": "CURRENCY",
                "public_link": current.get("public_link") or
                    f"https://funpay.com/chips/offer?id={lot_id}",
            }

    if hasattr(vertex, "lots_ids"):
        vertex.lots_ids = list(lots_by_id)
    return list(lots_by_id.values())


DESKTOP_PREFERENCE_KEYS = {
    "FunPay": ("multiDelivery", "autoRestore", "autoDisable", "oldMsgGetMode",
               "keepSentMessagesUnread"),
    "Greetings": ("ignoreSystemMessages", "onlyNewChats", "sendGreetings"),
    "BlockList": ("blockDelivery", "blockResponse", "blockNewMessageNotification",
                  "blockNewOrderNotification", "blockCommandNotification"),
    "NewMessageView": ("includeMyMessages", "includeFPMessages", "includeBotMessages",
                       "notifyOnlyMyMessages", "notifyOnlyFPMessages",
                       "notifyOnlyBotMessages", "showImageName"),
}


def _get_desktop_preferences(config: Any) -> dict[str, bool]:
    result = {}
    for section_name, keys in DESKTOP_PREFERENCE_KEYS.items():
        if section_name not in config:
            continue
        section = config[section_name]
        for key in keys:
            result[f"{section_name}.{key}"] = section.getboolean(key, fallback=False)
    return result


def _order_analytics(orders: list[Any]) -> dict[str, Any]:
    from collections import defaultdict

    counts: dict[str, int] = defaultdict(int)
    daily: dict[str, dict[str, Any]] = {}
    gross_total = 0.0
    for order in orders:
        status = _value(getattr(order, "status", None)).upper() or "UNKNOWN"
        counts[status] += 1
        raw_price = getattr(order, "price", None)
        try:
            price = float(raw_price) if raw_price is not None else 0.0
        except (TypeError, ValueError):
            price = 0.0
        gross_total += price
        raw_date = getattr(order, "date", None)
        day = raw_date.date().isoformat() if isinstance(raw_date, datetime) else (
            raw_date.isoformat() if isinstance(raw_date, date) else ""
        )
        if day:
            item = daily.setdefault(day, {"date": day, "orders": 0, "amount": 0.0})
            item["orders"] += 1
            item["amount"] += price
    return {
        "orders_count": len(orders),
        "gross_total": round(gross_total, 2),
        "status_counts": dict(counts),
        "daily": sorted(daily.values(), key=lambda item: item["date"], reverse=True),
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
        emit({"type": "refresh", "target": "analytics"})

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

    if action == "get_settings":
        funpay_config = vertex.MAIN_CFG["FunPay"]
        return {
            "auto_delivery": funpay_config.getboolean("autoDelivery"),
            "auto_response": funpay_config.getboolean("autoResponse"),
            "auto_raise": funpay_config.getboolean("autoRaise"),
        }

    if action == "update_automation_settings":
        settings = command.get("settings")
        if not isinstance(settings, dict):
            raise ValueError("Не переданы настройки автоматизаций")
        allowed = {"autoDelivery", "autoResponse", "autoRaise"}
        if set(settings) - allowed or any(type(value) is not bool for value in settings.values()):
            raise ValueError("Недопустимые параметры автоматизаций")
        for key, value in settings.items():
            vertex.MAIN_CFG["FunPay"][key] = "1" if value else "0"
        vertex.save_config(vertex.MAIN_CFG, "configs/_main.cfg")
        return {
            "auto_delivery": vertex.MAIN_CFG["FunPay"].getboolean("autoDelivery"),
            "auto_response": vertex.MAIN_CFG["FunPay"].getboolean("autoResponse"),
            "auto_raise": vertex.MAIN_CFG["FunPay"].getboolean("autoRaise"),
        }

    if action == "get_lots":
        lots = _refresh_profile(vertex)
        return {"lots": lots, "count": len(lots)}

    if action == "get_lot_editor":
        lot_id = str(command.get("lot_id", "")).strip()
        if not lot_id:
            raise ValueError("Не указан ID лота")
        profile = vertex.profile or account.get_user(account.id)
        lot = profile.get_lot(lot_id)
        if lot is None:
            raise ValueError("Лот не найден в профиле. Обнови список лотов.")
        is_currency = _value(getattr(lot.subcategory, "type", None)).upper() == "CURRENCY"
        if is_currency:
            chip_fields = account.get_chip_fields(int(lot.subcategory.id))
            chip_offer = chip_fields.chip_offers.get(str(lot_id))
            if chip_offer is None:
                chip_offer = next(
                    (item for item in chip_fields.chip_offers.values()
                     if str(item.lot_id) == str(lot_id)), None
                )
            if chip_offer is None:
                raise ValueError("Валютное предложение не найдено в форме редактирования")
            editor = {
                "title": getattr(lot, "description", None) or "",
                "description": "",
                "price": chip_offer.price,
                "amount": chip_offer.amount,
                "active": chip_offer.active,
                "auto_delivery": False,
                "is_currency": True,
            }
        else:
            fields = account.get_lot_fields(int(lot_id))
            editor = {
                "title": fields.title_ru,
                "description": fields.description_ru,
                "price": fields.price,
                "amount": fields.amount,
                "active": fields.active,
                "auto_delivery": bool(fields.auto_delivery),
                "is_currency": False,
            }
        return {"lot": serialize_lot(lot), "editor": editor}

    if action == "update_lot":
        lot_id = str(command.get("lot_id", "")).strip()
        if not lot_id:
            raise ValueError("Не указан ID лота")
        profile = vertex.profile or account.get_user(account.id)
        lot = profile.get_lot(lot_id)
        if lot is None:
            raise ValueError("Лот не найден в профиле. Обнови список лотов.")
        values = command.get("values")
        if not isinstance(values, dict):
            raise ValueError("Не переданы новые значения лота")
        for key in ("title", "description"):
            if key in values and not isinstance(values[key], str):
                raise ValueError(f"Поле {key} должно быть текстом")
        if "price" in values:
            try:
                price = float(values["price"])
            except (TypeError, ValueError):
                raise ValueError("Цена должна быть числом")
            if price <= 0:
                raise ValueError("Цена должна быть больше нуля")
        if "amount" in values:
            try:
                amount = int(values["amount"])
            except (TypeError, ValueError):
                raise ValueError("Количество должно быть целым числом")
            if amount < 0:
                raise ValueError("Количество не может быть отрицательным")
        if "active" in values and type(values["active"]) is not bool:
            raise ValueError("Статус активности должен быть логическим значением")

        subcategory_type = _value(getattr(lot.subcategory, "type", None)).upper()
        if subcategory_type == "CURRENCY":
            chip_fields = account.get_chip_fields(int(lot.subcategory.id))
            chip_offer = chip_fields.chip_offers.get(str(lot_id))
            if chip_offer is None:
                chip_offer = next(
                    (item for item in chip_fields.chip_offers.values()
                     if str(item.lot_id) == str(lot_id)), None
                )
            if chip_offer is None:
                raise ValueError("Валютное предложение не найдено в форме редактирования")
            if "price" in values:
                chip_offer.price = float(values["price"])
            if "amount" in values:
                chip_offer.amount = int(values["amount"])
            if "active" in values:
                chip_offer.active = bool(values["active"])
            account.save_chip(chip_fields)
        else:
            fields = account.get_lot_fields(int(lot_id))
            if "title" in values:
                fields.title_ru = values["title"].strip()
            if "description" in values:
                fields.description_ru = values["description"]
            if "price" in values:
                fields.price = float(values["price"])
            if "amount" in values:
                if fields.auto_delivery:
                    raise ValueError(
                        "У этого лота включена встроенная автовыдача FunPay. "
                        "Количество зависит от списка товаров, поэтому измените его в форме автовыдачи."
                    )
                fields.amount = int(values["amount"])
            if "active" in values:
                fields.active = bool(values["active"])
            account.save_lot(fields)

        lots = _refresh_profile(vertex)
        return {"lots": lots, "count": len(lots), "saved_lot_id": lot_id}

    if action == "delete_lot":
        lot_id = str(command.get("lot_id", "")).strip()
        if not lot_id:
            raise ValueError("Не указан ID лота")
        profile = vertex.profile or account.get_user(account.id)
        lot = profile.get_lot(lot_id)
        if lot is None:
            raise ValueError("Лот не найден в профиле. Обнови список лотов.")
        if _value(getattr(lot.subcategory, "type", None)).upper() == "CURRENCY":
            raise ValueError("Удаление валютных предложений через этот экран пока не поддерживается.")
        account.delete_lot(int(lot_id))
        lots = _refresh_profile(vertex)
        return {"lots": lots, "count": len(lots), "deleted_lot_id": lot_id}

    if action == "get_analytics":
        _next, orders, _locale, _subcategories = account.get_sales(
            include_paid=True, include_closed=True, include_refunded=True
        )
        return {"analytics": _order_analytics(list(orders))}

    if action == "get_preferences":
        return {"preferences": _get_desktop_preferences(vertex.MAIN_CFG)}

    if action == "update_preferences":
        updates = command.get("preferences")
        if not isinstance(updates, dict):
            raise ValueError("Не переданы настройки")
        allowed = {
            f"{section}.{key}"
            for section, keys in DESKTOP_PREFERENCE_KEYS.items()
            for key in keys
        }
        if set(updates) - allowed or any(type(value) is not bool for value in updates.values()):
            raise ValueError("Недопустимые параметры настроек")
        for full_key, value in updates.items():
            section_name, key = full_key.split(".", 1)
            vertex.MAIN_CFG[section_name][key] = "1" if value else "0"
        vertex.save_config(vertex.MAIN_CFG, "configs/_main.cfg")
        return {"preferences": _get_desktop_preferences(vertex.MAIN_CFG)}

    if action == "get_order_details":
        order_id = str(command.get("order_id", "")).lstrip("#")
        if not order_id:
            raise ValueError("Не указан ID заказа")
        order = account.get_order(order_id)
        fields = []
        for field_id, field in (getattr(order, "fields", None) or {}).items():
            fields.append({
                "id": str(field_id),
                "name": getattr(field, "name", None) or str(field_id),
                "value": str(getattr(field, "value", "")),
            })
        review = getattr(order, "review", None)
        review_data = None if review is None else {
            "stars": getattr(review, "stars", None),
            "text": getattr(review, "text", None) or "",
            "reply": getattr(review, "reply", None) or "",
        }
        subcategory = getattr(order, "subcategory", None)
        server = getattr(order, "server", None)
        side = getattr(order, "side", None)
        return {"order": {
            "id": str(getattr(order, "id", order_id)),
            "status": _value(getattr(order, "status", None)),
            "buyer": getattr(order, "buyer_username", None) or "",
            "buyer_id": getattr(order, "buyer_id", ""),
            "sum": getattr(order, "sum", ""),
            "currency": _value(getattr(order, "currency", None)),
            "amount": getattr(order, "amount", ""),
            "category": getattr(subcategory, "fullname", "") if subcategory else "",
            "server": getattr(server, "name", "") if server else "",
            "side": getattr(side, "name", "") if side else "",
            "player": getattr(order, "player", None) or "",
            "fields": fields,
            "review": review_data,
        }}

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
        numeric_chat_id = int(chat_id)
        chat = account.get_chat_by_id(numeric_chat_id, make_request=False)
        chat_name = getattr(chat, "name", None) if chat else None
        interlocutor_id = None
        if vertex.runner:
            interlocutor_id = vertex.runner.users_ids.get(numeric_chat_id)
        if interlocutor_id is None:
            history = account.get_chat_history(numeric_chat_id, interlocutor_username=chat_name)
            if history:
                interlocutor_id = history[-1].interlocutor_id
        sent = account.send_message(numeric_chat_id, message_text, chat_name=chat_name,
                                    interlocutor_id=interlocutor_id)
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
