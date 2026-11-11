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
