"""Offscreen smoke tests for the PySide6 desktop window."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop.app import DesktopWindow


class DesktopWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_window_builds_all_pages_and_initial_state(self):
        window = DesktopWindow()
        try:
            self.assertEqual(window.pages.count(), len(window.PAGES))
            self.assertEqual(window.navigation.count(), len(window.PAGES))
            self.assertEqual(window.navigation.currentRow(), 0)
            self.assertEqual(window.page_title.text(), "Главная")
            self.assertEqual(window.engine_button.text(), "Запустить движок")
            self.assertEqual(window.engine_process.state(), window.engine_process.ProcessState.NotRunning)
            self.assertEqual(window.lot_table.columnCount(), 8)
            self.assertEqual(window.order_table.columnCount(), 6)
            self.assertEqual(window.analytics_table.columnCount(), 3)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
