import unittest
from datetime import date, datetime
from types import SimpleNamespace

from desktop.engine_runner import serialize_chat, serialize_message, serialize_order


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
