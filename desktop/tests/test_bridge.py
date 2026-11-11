import configparser
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from PIL import Image

from desktop.engine_runner import (
    _collect_sales, _currency_editor_payload, _get_desktop_preferences,
    _handle_command,
    _command_loop, _order_analytics, _prepare_image_payload, _refresh_profile,
    _save_product_file, _list_product_files, _read_product_file, _stock_file_path,
    _save_rule_config, main as engine_main,
    _serialize_create_categories,
    serialize_chat, serialize_lot,
    serialize_message, serialize_order,
)


class DesktopBridgeSerializationTests(unittest.TestCase):
    def test_order_serializes_datetime_and_enum_like_values(self):
        order = SimpleNamespace(
            id="#12345",
            buyer_username="buyer",
            description="Blade Ball item",
            price=12.5,
            currency=SimpleNamespace(name="BYN"),
            status=SimpleNamespace(name="PAID"),
            date=datetime(2026, 11, 11, 12, 34),
            chat_id=987,
        )
        result = serialize_order(order)
        self.assertEqual(result["id"], "#12345")
        self.assertEqual(result["currency"], "BYN")
        self.assertEqual(result["status"], "PAID")
        self.assertEqual(result["date"], "2026-11-11 12:34")
        self.assertEqual(result["chat_id"], "987")


    def test_order_serializes_full_order_sum_when_price_is_not_present(self):
        order = SimpleNamespace(
            id="42", sum_=None, sum=19.75, buyer_username="buyer",
            description=None, currency=SimpleNamespace(name="RUB"),
            status=SimpleNamespace(name="CLOSED"), date=None, chat_id=5,
        )
        result = serialize_order(order)
        self.assertEqual(result["price"], 19.75)
        self.assertEqual(result["description"], "")

    def test_order_serializes_date_without_datetime_arguments(self):
        order = SimpleNamespace(
            id="1", buyer_username=None, description="", price=1,
            currency=None, status=None, date=date(2026, 11, 11), chat_id=1,
        )
        self.assertEqual(serialize_order(order)["date"], "2026-11-11")

    def test_chat_serializes_unread_state(self):
        chat = SimpleNamespace(id=10, name="Buyer", last_message_text="Hello", unread=True)
        self.assertEqual(
            serialize_chat(chat),
            {"id": "10", "name": "Buyer", "last_message": "Hello", "unread": True},
        )


    def test_lot_serialization_contains_editable_metadata_but_not_raw_html(self):
        lot = SimpleNamespace(
            id=77, description="Premium item", title="Premium item", server="EU",
            side="Alliance", amount=5, price=12.5,
            currency=SimpleNamespace(name="BYN"), active=True, auto=False,
            subcategory=SimpleNamespace(
                id=12, name="Game", fullname="Game / Currency",
                type=SimpleNamespace(name="COMMON"),
                category=SimpleNamespace(id=9, name="Test Game"),
            ),
            public_link="https://funpay.com/lots/offer?id=77",
            html="<div>private widget</div>",
        )
        result = serialize_lot(lot)
        self.assertEqual(result["id"], "77")
        self.assertEqual(result["subcategory_type"], "COMMON")
        self.assertEqual(result["price"], 12.5)
        self.assertEqual(result["active"], True)
        self.assertEqual(result["category_id"], 9)
        self.assertEqual(result["category_name"], "Test Game")
        self.assertEqual(
            result["edit_link"], "https://funpay.com/lots/offerEdit?offer=77"
        )
        self.assertNotIn("html", result)
        self.assertNotIn("private widget", str(result))



    def test_create_category_serialization_includes_both_offer_types(self):
        common = SimpleNamespace(
            id=10, name="Items", fullname="Items Game",
            type=SimpleNamespace(name="COMMON"),
            category=SimpleNamespace(id=3, name="Game"),
        )
        currency = SimpleNamespace(
            id=11, name="Zulu", fullname="Zulu Game",
            type=SimpleNamespace(name="CURRENCY"),
            category=SimpleNamespace(id=3, name="Game"),
        )
        categories = _serialize_create_categories({
            "COMMON": {10: common},
            "CURRENCY": {11: currency},
        })
        self.assertEqual([item["type"] for item in categories], ["COMMON", "CURRENCY"])
        self.assertEqual(
            categories[0]["create_link"], "https://funpay.com/lots/offerEdit?node=10"
        )
        self.assertEqual(
            categories[1]["create_link"], "https://funpay.com/chips/11/trade"
        )
        self.assertEqual(categories[0]["category_name"], "Game")

    def test_currency_editor_payload_uses_desktop_lot_cache(self):
        offer = SimpleNamespace(price=4.25, amount=9, active=False)
        result = _currency_editor_payload(
            {"title": "My currency offer"},
            offer,
        )
        self.assertEqual(result["title"], "My currency offer")
        self.assertEqual(result["price"], 4.25)
        self.assertEqual(result["amount"], 9)
        self.assertFalse(result["active"])
        self.assertTrue(result["is_currency"])


    def test_preferences_only_expose_keys_already_in_config(self):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read_string(
            "[FunPay]\nautoRestore = true\nkeepSentMessagesUnread = false\n"
            "[NewMessageView]\nshowImageName = true\n"
        )
        self.assertEqual(
            _get_desktop_preferences(config),
            {
                "FunPay.autoRestore": True,
                "FunPay.keepSentMessagesUnread": False,
                "NewMessageView.showImageName": True,
            },
        )


    def test_send_review_reply_uses_vertex_api_only_when_review_exists(self):
        review = SimpleNamespace(text="Great buyer", reply="Old reply")
        sent = []

        class FakeAccount:
            def get_order(self, order_id, include_review=True):
                self.order_id = order_id
                self.include_review = include_review
                return SimpleNamespace(review=review)

            def send_review(self, order_id, text):
                sent.append((order_id, text))

        vertex = SimpleNamespace(account=FakeAccount())
        result = _handle_command(vertex, {
            "action": "send_review_reply",
            "order_id": "#987",
            "text": "  Thank you!  ",
        })
        self.assertEqual(sent, [("987", "Thank you!")])
        self.assertEqual(result["order_id"], "987")
        self.assertEqual(result["reply"], "Thank you!")
        self.assertTrue(result["updated"])

        rating_only_review = SimpleNamespace(text="", reply="")
        vertex.account.get_order = lambda *_args, **_kwargs: SimpleNamespace(
            review=rating_only_review
        )
        second = _handle_command(vertex, {
            "action": "send_review_reply",
            "order_id": "989",
            "text": "Thanks for the rating!",
        })
        self.assertEqual(sent[-1], ("989", "Thanks for the rating!"))
        self.assertTrue(second["updated"])

        vertex.account.get_order = lambda *_args, **_kwargs: SimpleNamespace(review=None)
        with self.assertRaisesRegex(ValueError, "нет отзыва"):
            _handle_command(vertex, {
                "action": "send_review_reply",
                "order_id": "988",
                "text": "A reply",
            })


    def test_update_regular_lot_saves_only_supported_fields(self):
        subcategory = SimpleNamespace(
            id=50, name="Items", fullname="Test Game / Items",
            type=SimpleNamespace(name="COMMON"),
            category=SimpleNamespace(id=7, name="Test Game"),
        )
        lot = SimpleNamespace(
            id=42, description="Before", title="Before", server="", side="",
            amount=3, price=10.0, currency=SimpleNamespace(name="BYN"),
            active=True, auto=False, subcategory=subcategory,
            public_link="https://funpay.com/lots/offer?id=42",
        )
        fields = SimpleNamespace(
            title_ru="Before", description_ru="Old description",
            price=10.0, amount=3, active=True, auto_delivery=False,
        )

        class Profile:
            def get_lots(self):
                return []

        class FakeAccount:
            id = 1
            currency = SimpleNamespace(name="BYN")

            def get_lot_fields(self, lot_id):
                self.requested_id = lot_id
                return fields

            def save_lot(self, saved_fields):
                self.saved_fields = saved_fields

            def get_user(self, _user_id):
                return Profile()

        account = FakeAccount()
        vertex = SimpleNamespace(
            account=account, profile=None, curr_profile=None, lots_ids=[],
            desktop_lots={"42": serialize_lot(lot)},
        )
        result = _handle_command(vertex, {
            "action": "update_lot",
            "lot_id": "42",
            "values": {
                "title": "After",
                "description": "New description",
                "price": 17.5,
                "amount": 8,
                "active": False,
            },
        })
        self.assertEqual(account.requested_id, 42)
        self.assertEqual(account.saved_fields.title_ru, "After")
        self.assertEqual(account.saved_fields.description_ru, "New description")
        self.assertEqual(account.saved_fields.price, 17.5)
        self.assertEqual(account.saved_fields.amount, 8)
        self.assertFalse(account.saved_fields.active)
        self.assertEqual(result["saved_lot_id"], "42")

    def test_update_regular_lot_does_not_allow_quantity_change_with_builtin_delivery(self):
        subcategory = SimpleNamespace(
            id=50, name="Items", fullname="Test Game / Items",
            type=SimpleNamespace(name="COMMON"),
            category=SimpleNamespace(id=7, name="Test Game"),
        )
        lot = SimpleNamespace(
            id=42, description="Item", title="Item", server="", side="",
            amount=2, price=10.0, currency=SimpleNamespace(name="BYN"),
            active=True, auto=True, subcategory=subcategory,
            public_link="https://funpay.com/lots/offer?id=42",
        )
        fields = SimpleNamespace(auto_delivery=True, amount=2)

        class FakeAccount:
            id = 1

            def get_lot_fields(self, _lot_id):
                return fields

            def save_lot(self, _fields):
                self.saved = True

        account = FakeAccount()
        vertex = SimpleNamespace(
            account=account,
            desktop_lots={"42": serialize_lot(lot)},
        )
        with self.assertRaisesRegex(ValueError, "встроенная автовыдача"):
            _handle_command(vertex, {
                "action": "update_lot", "lot_id": "42",
                "values": {"amount": 9},
            })
        self.assertFalse(hasattr(account, "saved"))

    def test_update_currency_offer_uses_chip_fields_api(self):
        subcategory = SimpleNamespace(
            id=88, name="Coins", fullname="Game / Coins",
            type=SimpleNamespace(name="CURRENCY"),
            category=SimpleNamespace(id=8, name="Game"),
        )
        lot = SimpleNamespace(
            id="1-2-88-3", description="Coins", title="Coins", server="", side="",
            amount=2, price=4.0, currency=SimpleNamespace(name="BYN"),
            active=True, auto=False, subcategory=subcategory,
            public_link="https://funpay.com/chips/offer?id=1-2-88-3",
        )
        offer = SimpleNamespace(lot_id="1-2-88-3", price=4.0, amount=2, active=True)
        chip_fields = SimpleNamespace(chip_offers={"1-2-88-3": offer})

        class Profile:
            def get_lots(self):
                return []

        class FakeAccount:
            id = 1
            currency = SimpleNamespace(name="BYN")

            def get_chip_fields(self, subcategory_id):
                self.requested_subcategory_id = subcategory_id
                return chip_fields

            def save_chip(self, fields_to_save):
                self.saved = fields_to_save

            def get_user(self, _user_id):
                return Profile()

        account = FakeAccount()
        vertex = SimpleNamespace(
            account=account, profile=None, curr_profile=None, lots_ids=[],
            desktop_lots={"1-2-88-3": serialize_lot(lot)},
        )
        result = _handle_command(vertex, {
            "action": "update_lot",
            "lot_id": "1-2-88-3",
            "values": {"price": 6.5, "amount": 12, "active": False},
        })
        self.assertEqual(account.requested_subcategory_id, 88)
        self.assertIs(account.saved, chip_fields)
        self.assertEqual(offer.price, 6.5)
        self.assertEqual(offer.amount, 12)
        self.assertFalse(offer.active)
        self.assertEqual(result["saved_lot_id"], "1-2-88-3")

    def test_raise_category_is_scoped_to_owned_regular_subcategories(self):
        class FakeAccount:
            def raise_lots(self, category_id, subcategories=None):
                self.raised_category = category_id
                self.raised_subcategories = subcategories
                return 1800

        account = FakeAccount()
        vertex = SimpleNamespace(
            account=account,
            desktop_lots={
                "1": {"subcategory_type": "COMMON", "category_id": 7,
                      "category_name": "Game", "subcategory_id": 70},
                "2": {"subcategory_type": "CURRENCY", "category_id": 7,
                      "category_name": "Game", "subcategory_id": 71},
                "3": {"subcategory_type": "COMMON", "category_id": 7,
                      "category_name": "Game", "subcategory_id": 72},
            },
        )
        result = _handle_command(vertex, {"action": "raise_category", "category_id": 7})
        self.assertEqual(account.raised_category, 7)
        self.assertEqual(account.raised_subcategories, [70, 72])
        self.assertEqual(result["wait_seconds"], 1800)
        with self.assertRaisesRegex(ValueError, "не найдено обычных лотов"):
            _handle_command(vertex, {"action": "raise_category", "category_id": 8})
        self.assertEqual(account.raised_category, 7)

        vertex.desktop_lots["1"].pop("subcategory_id")
        vertex.desktop_lots["3"].pop("subcategory_id")
        with self.assertRaisesRegex(ValueError, "Не удалось определить подкатегории"):
            _handle_command(vertex, {"action": "raise_category", "category_id": 7})
        self.assertEqual(account.raised_category, 7)


    def test_update_lot_rejects_non_finite_prices_and_fractional_amounts(self):
        class FakeAccount:
            def get_lot_fields(self, _lot_id):
                raise AssertionError("The API must not be called for invalid values")

        vertex = SimpleNamespace(
            account=FakeAccount(),
            desktop_lots={"42": {"id": "42", "subcategory_type": "COMMON"}},
        )
        for values, message in (
            ({"price": float("nan")}, "конечным числом"),
            ({"price": float("inf")}, "конечным числом"),
            ({"amount": 2.5}, "целым числом"),
            ({"amount": True}, "целым числом"),
        ):
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, message):
                    _handle_command(vertex, {
                        "action": "update_lot", "lot_id": "42", "values": values,
                    })

    def test_raise_category_rejects_fractional_and_boolean_ids(self):
        class FakeAccount:
            def raise_lots(self, _category_id):
                raise AssertionError("The API must not be called for invalid IDs")

        vertex = SimpleNamespace(
            account=FakeAccount(),
            desktop_lots={"1": {"subcategory_type": "COMMON", "category_id": 7}},
        )
        for value in (7.5, True, float("nan")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "корректную категорию"):
                    _handle_command(vertex, {"action": "raise_category", "category_id": value})

    def test_order_analytics_groups_by_date_and_counts_statuses(self):
        orders = [
            SimpleNamespace(
                price=10.0, status=SimpleNamespace(name="PAID"),
                date=datetime(2026, 11, 11, 9, 0),
            ),
            SimpleNamespace(
                price=15.5, status=SimpleNamespace(name="CLOSED"),
                date=datetime(2026, 11, 11, 12, 0),
            ),
            SimpleNamespace(
                price=3.0, status=SimpleNamespace(name="REFUNDED"),
                date=date(2026, 11, 10),
            ),
        ]
        result = _order_analytics(orders)
        self.assertEqual(result["orders_count"], 3)
        self.assertEqual(result["gross_total"], 28.5)
        self.assertEqual(result["status_counts"], {"PAID": 1, "CLOSED": 1, "REFUNDED": 1})
        self.assertEqual(result["daily"][0]["date"], "2026-11-11")
        self.assertEqual(result["daily"][0]["orders"], 2)
        self.assertEqual(result["daily"][0]["amount"], 25.5)


    def test_refresh_profile_includes_private_paused_lots_and_currency_offers(self):
        common = SimpleNamespace(
            id=50, name="Game items", fullname="Game / Items",
            type=SimpleNamespace(name="COMMON"),
            category=SimpleNamespace(id=7, name="Test Game"),
        )
        currency = SimpleNamespace(
            id=88, name="Coins", fullname="Game / Coins",
            type=SimpleNamespace(name="CURRENCY"),
            category=SimpleNamespace(id=8, name="Test Currency Game"),
        )
        public_common = SimpleNamespace(
            id=100, description="Active item", title="Active item", server="", side="",
            amount=1, price=10.0, currency=SimpleNamespace(name="BYN"), active=True,
            auto=False, subcategory=common, public_link="https://funpay.com/lots/offer?id=100",
        )
        public_currency = SimpleNamespace(
            id="1-2-88-1", description="Coins", title="Coins", server="", side="",
            amount=2, price=4.0, currency=SimpleNamespace(name="BYN"), active=True,
            auto=False, subcategory=currency,
            public_link="https://funpay.com/chips/offer?id=1-2-88-1",
        )
        paused_lot = SimpleNamespace(
            id=101, description="Paused item", title="Paused item", server="", side="",
            amount=0, price=12.0, currency=SimpleNamespace(name="BYN"), active=False,
            auto=False, subcategory=common, public_link="https://funpay.com/lots/offer?id=101",
        )

        class Profile:
            def get_lots(self):
                return [public_common, public_currency]

        class FakeAccount:
            id = 1
            currency = SimpleNamespace(name="BYN")

            def get_user(self, _user_id):
                return Profile()

            def get_my_subcategory_lots(self, subcategory_id):
                self.requested_subcategory = subcategory_id
                return [paused_lot]

            def get_chip_fields(self, subcategory_id):
                self.requested_chip_subcategory = subcategory_id
                offer = SimpleNamespace(
                    lot_id="1-2-88-2", amount=7, price=9.5, active=False
                )
                return SimpleNamespace(chip_offers={"1-2-88-2": offer})

        account = FakeAccount()
        vertex = SimpleNamespace(
            account=account, profile=None, curr_profile=None, lots_ids=[]
        )
        result = _refresh_profile(vertex)
        by_id = {lot["id"]: lot for lot in result}

        self.assertIn("100", by_id)
        self.assertIn("101", by_id)
        self.assertIn("1-2-88-1", by_id)
        self.assertIn("1-2-88-2", by_id)
        self.assertFalse(by_id["101"]["active"])
        self.assertFalse(by_id["1-2-88-2"]["active"])
        self.assertEqual(account.requested_subcategory, 50)
        self.assertEqual(account.requested_chip_subcategory, 88)
        self.assertEqual(vertex.lots_ids, [100, "1-2-88-1"])
        self.assertNotIn(101, vertex.lots_ids)
        self.assertEqual(by_id["101"]["category_id"], 7)
        self.assertEqual(by_id["1-2-88-2"]["category_id"], 8)
        self.assertEqual(
            by_id["1-2-88-2"]["edit_link"], "https://funpay.com/chips/88/trade"
        )
        self.assertIn("1-2-88-2", vertex.desktop_lots)

    def test_collect_sales_follows_cursor_and_deduplicates(self):
        first = SimpleNamespace(id="1", price=3.0)
        second = SimpleNamespace(id="2", price=4.0)
        third = SimpleNamespace(id="3", price=5.0)

        class FakeAccount:
            calls = []

            def get_sales(self, start_from=None, **_kwargs):
                self.calls.append(start_from)
                if start_from is None:
                    return "2", [first, second], "ru", {}
                if start_from == "2":
                    return None, [second, third], "ru", {}
                raise AssertionError(f"Unexpected cursor: {start_from}")

        account = FakeAccount()
        orders, cursor, locale, has_more = _collect_sales(account, max_pages=10)
        self.assertEqual([order.id for order in orders], ["1", "2", "3"])
        self.assertIsNone(cursor)
        self.assertEqual(locale, "ru")
        self.assertFalse(has_more)
        self.assertEqual(account.calls, [None, "2"])

    def test_collect_sales_continues_from_existing_cursor(self):
        fourth = SimpleNamespace(id="4", price=6.0)
        fifth = SimpleNamespace(id="5", price=7.0)

        class FakeAccount:
            calls = []

            def get_sales(self, start_from=None, locale=None, **_kwargs):
                self.calls.append((start_from, locale))
                if start_from == "4":
                    return None, [fourth, fifth], "ru", {}
                raise AssertionError(f"Unexpected cursor: {start_from}")

        account = FakeAccount()
        orders, cursor, locale, has_more = _collect_sales(
            account, max_pages=10, start_from="4", locale="ru"
        )
        self.assertEqual([order.id for order in orders], ["4", "5"])
        self.assertIsNone(cursor)
        self.assertEqual(locale, "ru")
        self.assertFalse(has_more)
        self.assertEqual(account.calls, [("4", "ru")])

    def test_image_payload_normalizes_jpeg_and_webp_to_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpeg_path = root / "sample.jpg"
            webp_path = root / "sample.webp"
            Image.new("RGB", (32, 24), (30, 120, 210)).save(jpeg_path, format="JPEG")
            Image.new("RGBA", (20, 20), (20, 200, 100, 120)).save(webp_path, format="WEBP")

            for path in (jpeg_path, webp_path):
                payload = _prepare_image_payload(str(path))
                self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertLessEqual(len(payload), 10 * 1024 * 1024)
                from io import BytesIO
                with Image.open(BytesIO(payload)) as normalized:
                    self.assertEqual(normalized.format, "PNG")
                    self.assertGreater(normalized.width, 0)
                    self.assertGreater(normalized.height, 0)

    def test_image_payload_rejects_missing_or_unsupported_files(self):
        with tempfile.TemporaryDirectory() as directory:
            unsupported = Path(directory) / "notes.txt"
            unsupported.write_text("not an image", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "не найден"):
                _prepare_image_payload(str(Path(directory) / "missing.png"))
            with self.assertRaisesRegex(ValueError, "Поддерживаются"):
                _prepare_image_payload(str(unsupported))


    def test_send_image_command_passes_png_bytes_to_vertex_api(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "picture.jpg"
            Image.new("RGB", (12, 10), (200, 30, 80)).save(image_path, format="JPEG")
            sent = {}

            class FakeAccount:
                def get_chat_by_id(self, chat_id, make_request=False):
                    return SimpleNamespace(name="Buyer")

                def get_chat_history(self, _chat_id, interlocutor_username=None):
                    return []

                def send_image(self, chat_id, image, chat_name=None, interlocutor_id=None):
                    sent.update({
                        "chat_id": chat_id,
                        "image": image,
                        "chat_name": chat_name,
                        "interlocutor_id": interlocutor_id,
                    })
                    return SimpleNamespace(
                        id=55, text=None, image_link="https://example.invalid/image.png",
                        image_name="picture.png", author="Seller", author_id=1,
                        by_bot=False, by_vertex=False,
                    )

            vertex = SimpleNamespace(account=FakeAccount(), runner=None)
            result = _handle_command(vertex, {
                "action": "send_image",
                "chat_id": "123",
                "image_path": str(image_path),
            })
            self.assertEqual(sent["chat_id"], 123)
            self.assertEqual(sent["chat_name"], "Buyer")
            self.assertTrue(sent["image"].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(result["chat_id"], "123")
            self.assertEqual(result["message"]["id"], "55")

    def test_command_loop_acknowledges_shutdown_before_stopping_vertex(self):
        events = []

        class FakeVertex:
            account = object()

            def stop(self):
                events.append("stop")

        vertex = FakeVertex()
        command = json.dumps({"request_id": 9, "action": "shutdown"}) + "\n"
        with patch("desktop.engine_runner.sys.stdin", io.StringIO(command)):
            with patch("desktop.engine_runner.emit", side_effect=lambda payload: events.append(payload)):
                _command_loop(vertex)

        self.assertEqual(events[0]["type"], "response")
        self.assertEqual(events[0]["request_id"], 9)
        self.assertTrue(events[0]["ok"])
        self.assertEqual(events[0]["data"], {"stopping": True})
        self.assertEqual(events[1], "stop")


    def test_collect_sales_detects_repeated_cursor(self):
        first = SimpleNamespace(id="1", price=1.0)
        second = SimpleNamespace(id="2", price=2.0)

        class FakeAccount:
            def get_sales(self, start_from=None, **_kwargs):
                if start_from is None:
                    return "2", [first], "ru", {}
                return "2", [second], "ru", {}

        with self.assertRaisesRegex(RuntimeError, "повторил курсор"):
            _collect_sales(FakeAccount(), max_pages=10)

    def test_get_orders_detects_repeated_cursor(self):
        class FakeAccount:
            def get_sales(self, start_from=None, **_kwargs):
                return "20", [], "ru", {}

        vertex = SimpleNamespace(account=FakeAccount())
        with self.assertRaisesRegex(RuntimeError, "повторил курсор"):
            _handle_command(vertex, {"action": "get_orders", "start_from": "20"})

    def test_engine_main_runs_full_lifecycle_with_fake_vertex_and_no_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            (root / "configs" / "_main.cfg").write_text("[FunPay]\\n", encoding="utf-8")

            calls = []
            fake_utils = ModuleType("Utils")
            fake_utils.__path__ = []
            fake_logger = ModuleType("Utils.logger")
            fake_logger.configure_logging = lambda: calls.append("logging")
            fake_config = ModuleType("Utils.config_loader")
            fake_config.load_main_config = lambda path: calls.append(("main", path)) or {"main": True}
            fake_config.load_auto_response_config = lambda path: calls.append(("response", path)) or {"response": True}
            fake_config.load_raw_auto_response_config = lambda path: calls.append(("raw_response", path)) or {"raw": True}
            fake_config.load_auto_delivery_config = lambda path: calls.append(("delivery", path)) or {"delivery": True}

            class FakeProfile:
                def get_lots(self):
                    return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

            class FakeVertex:
                def __init__(self, main, delivery, response, raw_response, version):
                    calls.append(("vertex_init", main, delivery, response, raw_response, version))
                    self.account = SimpleNamespace(username="OfflineSeller", id=12345)
                    self.profile = None

                def add_handlers_from_plugin(self, module):
                    calls.append(("handlers", bool(getattr(module, "BIND_TO_NEW_ORDER", None))))

                def init(self):
                    calls.append("vertex_init_call")
                    self.profile = FakeProfile()

                def run(self):
                    calls.append("vertex_run")

            fake_vertex = ModuleType("vertex")
            fake_vertex.Vertex = FakeVertex
            fake_utils.logger = fake_logger
            fake_utils.config_loader = fake_config

            with patch.dict(sys.modules, {
                "Utils": fake_utils,
                "Utils.logger": fake_logger,
                "Utils.config_loader": fake_config,
                "vertex": fake_vertex,
            }):
                with patch("desktop.engine_runner.emit") as emit_mock:
                    old_cwd = Path.cwd()
                    old_path = list(sys.path)
                    try:
                        result = engine_main(root=root, start_command_loop=False)
                    finally:
                        os.chdir(old_cwd)
                        sys.path[:] = old_path

            self.assertEqual(result, 0)
            self.assertIn("logging", calls)
            self.assertIn("vertex_init_call", calls)
            self.assertIn("vertex_run", calls)
            payloads = [call.args[0] for call in emit_mock.call_args_list]
            types = [payload.get("type") for payload in payloads]
            self.assertEqual(types, ["initializing", "connected", "engine_stopped"])
            connected = payloads[1]
            self.assertEqual(connected["username"], "OfflineSeller")
            self.assertEqual(connected["account_id"], 12345)
            self.assertEqual(connected["lots_count"], 2)
            self.assertTrue((root / "configs" / "auto_response.cfg").is_file())
            self.assertTrue((root / "configs" / "auto_delivery.cfg").is_file())

    def test_engine_main_reports_setup_required_without_account_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_cwd = Path.cwd()
            old_path = list(sys.path)
            try:
                with patch("desktop.engine_runner.emit") as emit_mock:
                    result = engine_main(root=root, start_command_loop=False)
            finally:
                os.chdir(old_cwd)
                sys.path[:] = old_path
            self.assertEqual(result, 2)
            self.assertEqual(
                emit_mock.call_args.args[0]["type"],
                "setup_required",
            )
            self.assertTrue((root / "configs" / "auto_response.cfg").is_file())


    def test_save_auto_response_config_validates_backs_up_and_hot_reloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            target = root / "configs" / "auto_response.cfg"
            target.write_text("[old]\nresponse: Old response\n", encoding="utf-8")
            old_config = object()
            vertex = SimpleNamespace(AR_CFG=old_config, RAW_AR_CFG=old_config, AD_CFG=None)

            fake_utils = ModuleType("Utils")
            fake_utils.__path__ = []
            fake_loader = ModuleType("Utils.config_loader")

            def read_config(path):
                config = configparser.ConfigParser(delimiters=(":",), interpolation=None)
                config.optionxform = str
                with open(path, "r", encoding="utf-8") as file:
                    config.read_file(file)
                return config

            def load_auto_response(path):
                config = read_config(path)
                command_sets = []
                for section in list(config.sections()):
                    if not config.has_option(section, "response") or not config[section]["response"].strip():
                        raise ValueError(f"Response missing in {section}")
                    if "|" in section:
                        command_sets.append(section)
                for command_set in command_sets:
                    parameters = dict(config[command_set])
                    for command in command_set.split("|"):
                        command = command.strip()
                        if command and command not in config.sections():
                            config.add_section(command)
                            for key, value in parameters.items():
                                config.set(command, key, value)
                return config

            fake_loader.load_auto_response_config = load_auto_response
            fake_loader.load_raw_auto_response_config = read_config
            fake_utils.config_loader = fake_loader

            content = (
                "[sell|buy]\nresponse: Hello $buyer\n"
                "telegramNotification: 0\nenabled: 1\n"
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(sys.modules, {
                    "Utils": fake_utils,
                    "Utils.config_loader": fake_loader,
                }):
                    result = _save_rule_config(vertex, root, "auto_response", content)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(result["sections"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), content)
            self.assertEqual(vertex.AR_CFG.sections(), ["sell|buy", "sell", "buy"])
            self.assertEqual(vertex.RAW_AR_CFG.sections(), ["sell|buy"])
            self.assertTrue((root / result["backup"]).is_file())
            self.assertEqual(
                (root / result["backup"]).read_text(encoding="utf-8"),
                "[old]\nresponse: Old response\n",
            )

    def test_save_invalid_rule_config_keeps_original_and_live_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            target = root / "configs" / "auto_response.cfg"
            original = "[old]\nresponse: keep me\n"
            target.write_text(original, encoding="utf-8")
            old_config = object()
            vertex = SimpleNamespace(AR_CFG=old_config, RAW_AR_CFG=old_config, AD_CFG=None)
            fake_utils = ModuleType("Utils")
            fake_utils.__path__ = []
            fake_loader = ModuleType("Utils.config_loader")
            fake_loader.load_auto_response_config = lambda _path: (_ for _ in ()).throw(
                ValueError("Response is required")
            )
            fake_loader.load_raw_auto_response_config = lambda _path: configparser.ConfigParser()
            fake_utils.config_loader = fake_loader

            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(sys.modules, {
                    "Utils": fake_utils,
                    "Utils.config_loader": fake_loader,
                }):
                    with self.assertRaisesRegex(ValueError, "Response is required"):
                        _save_rule_config(vertex, root, "auto_response", "[bad]\n")
            finally:
                os.chdir(old_cwd)

            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertIs(vertex.AR_CFG, old_config)
            self.assertIs(vertex.RAW_AR_CFG, old_config)
            self.assertEqual(list((root / "configs").glob("*.tmp")), [])

    def test_save_delivery_rules_requires_existing_products_file_before_replacing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            (root / "storage" / "products").mkdir(parents=True)
            target = root / "configs" / "auto_delivery.cfg"
            original = "[old]\nresponse: Old $product\n"
            target.write_text(original, encoding="utf-8")
            old_config = object()
            vertex = SimpleNamespace(AD_CFG=old_config)

            fake_utils = ModuleType("Utils")
            fake_utils.__path__ = []
            fake_loader = ModuleType("Utils.config_loader")

            def load_delivery(path):
                config = configparser.ConfigParser(delimiters=(":",), interpolation=None)
                config.optionxform = str
                with open(path, "r", encoding="utf-8") as file:
                    config.read_file(file)
                for section in config.sections():
                    products = config[section].get("productsFileName")
                    if products and not (root / "storage" / "products" / products).is_file():
                        raise ValueError("ProductsFileNotFoundError")
                    if products and "$product" not in config[section].get("response", ""):
                        raise ValueError("NoProductVarError")
                return config

            fake_loader.load_auto_delivery_config = load_delivery
            fake_utils.config_loader = fake_loader
            content = "[lot]\nresponse: You receive $product\nproductsFileName: stock.txt\n"

            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(sys.modules, {
                    "Utils": fake_utils,
                    "Utils.config_loader": fake_loader,
                }):
                    with self.assertRaisesRegex(ValueError, "ProductsFileNotFoundError"):
                        _save_rule_config(vertex, root, "auto_delivery", content)
                    self.assertEqual(target.read_text(encoding="utf-8"), original)
                    (root / "storage" / "products" / "stock.txt").write_text(
                        "item-1\n", encoding="utf-8"
                    )
                    result = _save_rule_config(vertex, root, "auto_delivery", content)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(result["sections"], 1)
            self.assertEqual(target.read_text(encoding="utf-8"), content)
            self.assertEqual(vertex.AD_CFG.sections(), ["lot"])
            self.assertTrue((root / result["backup"]).is_file())


    def test_rule_config_save_runs_real_vertex_config_validators(self):
        from Utils.config_loader import (
            load_auto_delivery_config, load_auto_response_config,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            products_dir = root / "storage" / "products"
            products_dir.mkdir(parents=True)
            response_target = root / "configs" / "auto_response.cfg"
            delivery_target = root / "configs" / "auto_delivery.cfg"
            response_target.write_text(
                "[old]\nresponse: Original\n", encoding="utf-8"
            )
            delivery_target.write_text(
                "[old]\nresponse: Original $product\n", encoding="utf-8"
            )
            vertex = SimpleNamespace(AR_CFG=None, RAW_AR_CFG=None, AD_CFG=None)
            response_text = (
                "[sell|buy]\nresponse: Hello $buyer\n"
                "telegramNotification: 0\n"
            )
            delivery_text = (
                "[stock offer]\nresponse: Here is $product\n"
                "productsFileName: stock.txt\n"
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                response_result = _save_rule_config(
                    vertex, root, "auto_response", response_text
                )
                self.assertEqual(
                    vertex.AR_CFG.sections(), ["sell|buy", "sell", "buy"]
                )
                self.assertEqual(vertex.RAW_AR_CFG.sections(), ["sell|buy"])
                self.assertEqual(
                    load_auto_response_config(str(response_target)).sections(),
                    ["sell|buy", "sell", "buy"],
                )

                with self.assertRaises(Exception):
                    _save_rule_config(vertex, root, "auto_delivery", delivery_text)
                self.assertEqual(
                    delivery_target.read_text(encoding="utf-8"),
                    "[old]\nresponse: Original $product\n",
                )
                (products_dir / "stock.txt").write_text("item-1\n", encoding="utf-8")
                delivery_result = _save_rule_config(
                    vertex, root, "auto_delivery", delivery_text
                )
                self.assertEqual(vertex.AD_CFG.sections(), ["stock offer"])
                self.assertEqual(
                    load_auto_delivery_config(str(delivery_target)).sections(),
                    ["stock offer"],
                )
            finally:
                os.chdir(old_cwd)

            self.assertTrue((root / response_result["backup"]).is_file())
            self.assertTrue((root / delivery_result["backup"]).is_file())
            self.assertEqual(response_result["sections"], 1)
            self.assertEqual(delivery_result["sections"], 1)


    def test_stock_file_create_read_update_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            created = _save_product_file(root, "blade_ball.txt", "item-a\n\nitem-b\n")
            self.assertEqual(created["products"], 2)
            self.assertEqual(created["lines"], 3)
            self.assertIsNone(created["backup"])

            loaded = _read_product_file(root, "blade_ball.txt")
            self.assertEqual(loaded["content"], "item-a\n\nitem-b\n")

            updated = _save_product_file(root, "blade_ball.txt", "item-c\n")
            self.assertEqual(updated["products"], 1)
            backup = root / updated["backup"]
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_text(encoding="utf-8"), "item-a\n\nitem-b\n")
            self.assertEqual(
                _read_product_file(root, "blade_ball.txt")["content"], "item-c\n"
            )
            files = _list_product_files(root)
            self.assertEqual([item["name"] for item in files], ["blade_ball.txt"])
            self.assertEqual(files[0]["products"], 1)

    def test_stock_file_names_cannot_escape_products_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "../outside.txt", "folder/file.txt", "folder\\\\file.txt",
                "CON", "NUL.txt", ".hidden", "bad?.txt", "name.",
            ):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        _stock_file_path(root, name)
            with self.assertRaisesRegex(ValueError, "нулевой символ"):
                _save_product_file(root, "safe.txt", "valid" + chr(0) + "invalid")

    def test_stock_file_rejects_symbolic_storage_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()
            try:
                (root / "storage").symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Windows runner does not permit symlink creation: {exc}")
            with self.assertRaisesRegex(ValueError, "символическими ссылками"):
                _stock_file_path(root, "stock.txt")
            self.assertFalse((external / "products").exists())
            with self.assertRaisesRegex(ValueError, "символическими ссылками"):
                _list_product_files(root)
            self.assertFalse((external / "products").exists())


    def test_stock_file_backup_rejects_symlinked_backup_folder_without_writing_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            products = storage / "products"
            products.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            (storage / "config_backups").symlink_to(external, target_is_directory=True)
            target = products / "stock.txt"
            target.write_text("original\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "символическими ссылками"):
                _save_product_file(root, "stock.txt", "replacement\n")

            self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
            self.assertFalse((external / "products").exists())


    def test_rule_config_rejects_symlinked_configs_directory_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()
            (root / "configs").symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "символическими ссылками"):
                _save_rule_config(
                    SimpleNamespace(), root, "auto_response",
                    "[test]\nresponse: safe\n",
                )
            self.assertFalse((external / "auto_response.cfg").exists())

    def test_message_serializes_text_and_author(self):
        message = SimpleNamespace(
            id=7, text="Hi", image_link=None, author="Buyer", author_id=42,
            by_bot=False, by_vertex=False,
        )
        result = serialize_message(message)
        self.assertEqual(result["text"], "Hi")
        self.assertEqual(result["author"], "Buyer")
        self.assertEqual(result["author_id"], 42)


if __name__ == "__main__":
    unittest.main()
