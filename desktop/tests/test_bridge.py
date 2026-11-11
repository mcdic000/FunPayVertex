import unittest
from datetime import date, datetime
from types import SimpleNamespace

from desktop.engine_runner import (
    _order_analytics, serialize_chat, serialize_lot, serialize_message, serialize_order,
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
            ),
            public_link="https://funpay.com/lots/offer?id=77",
            html="<div>private widget</div>",
        )
        result = serialize_lot(lot)
        self.assertEqual(result["id"], "77")
        self.assertEqual(result["subcategory_type"], "COMMON")
        self.assertEqual(result["price"], 12.5)
        self.assertEqual(result["active"], True)
        self.assertNotIn("html", result)
        self.assertNotIn("private widget", str(result))

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
