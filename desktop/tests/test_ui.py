"""Offscreen smoke tests for the PySide6 desktop window."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from desktop.app import DesktopWindow


class DesktopWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])


    def test_event_journal_persists_across_windows_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = DesktopWindow()
            second = None
            try:
                first.project_root = root
                first._add_activity("Persisted test event")
                path = root / "storage" / "desktop_events.jsonl"
                self.assertTrue(path.is_file())
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 1)
                self.assertIn("Persisted test event", lines[0])

                second = DesktopWindow()
                second.project_root = root
                second._load_activity_history()
                self.assertEqual(
                    second._activity_history[0][1], "Persisted test event"
                )
                self.assertGreater(second.notifications_list.count(), 0)
                second._clear_notifications()
                self.assertEqual(path.read_text(encoding="utf-8"), "")
                self.assertEqual(second._activity_history, [])
            finally:
                if second is not None:
                    second.close()
                first.close()


    def test_order_pages_merge_without_duplicates_and_refresh_existing_rows(self):
        window = DesktopWindow()
        try:
            window._set_orders([
                {"id": "100", "buyer": "Buyer A", "description": "Old title",
                 "price": 2.0, "currency": "BYN", "status": "PAID", "date": "2026-11-11"},
            ])
            window._set_orders([
                {"id": "101", "buyer": "Buyer B", "description": "Second order",
                 "price": 3.0, "currency": "BYN", "status": "CLOSED", "date": "2026-11-10"},
            ], append=True)
            window._upsert_order(
                {"id": "100", "buyer": "Buyer A", "description": "Updated title",
                 "price": 2.5, "currency": "BYN", "status": "CLOSED", "date": "2026-11-11"}
            )
            self.assertEqual(window.order_table.rowCount(), 2)
            rows = {
                window.order_table.item(row, 0).text(): row
                for row in range(window.order_table.rowCount())
            }
            self.assertEqual(
                window.order_table.item(rows["100"], 2).text(), "Updated title"
            )
            self.assertEqual(
                window.order_table.item(rows["100"], 3).text(), "2.5 BYN"
            )
        finally:
            window.close()

    def test_analytics_pages_accumulate_daily_totals_and_statuses(self):
        window = DesktopWindow()
        try:
            window._render_analytics({
                "orders_count": 2,
                "gross_total": 25.5,
                "status_counts": {"PAID": 1, "CLOSED": 1},
                "daily": [{"date": "2026-11-11", "orders": 2, "amount": 25.5}],
                "has_more": True,
            })
            window._render_analytics({
                "orders_count": 1,
                "gross_total": 7.0,
                "status_counts": {"REFUNDED": 1},
                "daily": [{"date": "2026-11-11", "orders": 1, "amount": 7.0}],
                "has_more": False,
            }, append=True)
            self.assertIn("Загружено продаж: 3", window.analytics_summary.text())
            self.assertIn("Сумма цен: 32.50", window.analytics_summary.text())
            self.assertIn("CLOSED: 1", window.analytics_summary.text())
            self.assertIn("PAID: 1", window.analytics_summary.text())
            self.assertIn("REFUNDED: 1", window.analytics_summary.text())
            self.assertEqual(window.analytics_table.rowCount(), 1)
            self.assertEqual(window.analytics_table.item(0, 1).text(), "3")
            self.assertEqual(window.analytics_table.item(0, 2).text(), "32.50")
        finally:
            window.close()

    def test_window_builds_all_pages_and_initial_state(self):
        window = DesktopWindow()
        try:
            self.assertEqual(window.pages.count(), len(window.PAGES))
            self.assertEqual(window.navigation.count(), len(window.PAGES))
            self.assertEqual(window.navigation.currentRow(), 0)
            self.assertEqual(window.page_title.text(), "Главная")
            self.assertEqual(window.engine_button.text(), "Запустить движок")
            self.assertEqual(window.engine_process.state(), QProcess.ProcessState.NotRunning)
            self.assertEqual(window.lot_table.columnCount(), 8)
            self.assertEqual(window.order_table.columnCount(), 6)
            self.assertEqual(window.analytics_table.columnCount(), 3)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
