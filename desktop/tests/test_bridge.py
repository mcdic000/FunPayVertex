import configparser
import unittest
from datetime import date, datetime
from types import SimpleNamespace

from desktop.engine_runner import (
    _collect_sales, _currency_editor_payload, _get_desktop_preferences,
    _handle_command,
    _order_analytics, _refresh_profile,
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
        self.assertFalse(second["updated"])

        vertex.account.get_order = lambda *_args, **_kwargs: SimpleNamespace(review=None)
        with self.assertRaisesRegex(ValueError, "нет отзыва"):
            _handle_command(vertex, {
                "action": "send_review_reply",
                "order_id": "988",
                "text": "A reply",
            })

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
