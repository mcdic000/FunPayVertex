"""Initial desktop shell for FunPay Assistant.

This first milestone intentionally provides UI scaffolding only. It does not
connect to FunPay or perform account actions.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DesktopWindow(QMainWindow):
    """Main application window."""

    PAGES = (
        ("Главная", "Обзор и состояние подключения"),
        ("Заказы", "Здесь появится список заказов FunPay"),
        ("Сообщения", "Здесь появятся чаты и быстрые ответы"),
        ("Автовыдача", "Настройка правил автоматической выдачи"),
        ("Лоты", "Управление лотами и автоподнятием"),
        ("Аналитика", "Продажи и статистика"),
        ("Уведомления", "События и настройки уведомлений"),
        ("Настройки", "Подключение и параметры приложения"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FunPay Assistant")
        self.resize(1120, 720)
        self.setMinimumSize(900, 600)

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 22, 16, 16)
        sidebar_layout.setSpacing(12)

        brand = QLabel("FunPay\nAssistant")
        brand.setObjectName("brand")
        sidebar_layout.addWidget(brand)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        for title, _ in self.PAGES:
            self.navigation.addItem(QListWidgetItem(title))
        sidebar_layout.addWidget(self.navigation, 1)

        version = QLabel("Desktop • ранняя версия")
        version.setObjectName("muted")
        sidebar_layout.addWidget(version)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 24)
        content_layout.setSpacing(18)

        topbar = QHBoxLayout()
        self.page_title = QLabel("Главная")
        self.page_title.setObjectName("pageTitle")
        topbar.addWidget(self.page_title)
        topbar.addStretch(1)
        self.connection_badge = QLabel("● Не подключено")
        self.connection_badge.setObjectName("status")
        topbar.addWidget(self.connection_badge)
        content_layout.addLayout(topbar)

        self.pages = QStackedWidget()
        for title, description in self.PAGES:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 10, 0, 0)
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            intro = QLabel(description)
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            card = QFrame()
            card.setObjectName("panel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(22, 20, 22, 20)
            card_layout.addWidget(heading)
            card_layout.addWidget(intro)
            if title == "Главная":
                note = QLabel(
                    "Рабочее пространство подготовлено. Подключение к FunPay "
                    "пока отключено — сначала настроим безопасное хранение "
                    "учётных данных и адаптер к движку Vertex."
                )
                note.setWordWrap(True)
                note.setObjectName("notice")
                card_layout.addSpacing(12)
                card_layout.addWidget(note)
            page_layout.addWidget(card)
            page_layout.addStretch(1)
            self.pages.addWidget(page)

        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._change_title)
        self.navigation.setCurrentRow(0)
        self._apply_style()

    def _change_title(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.page_title.setText(self.PAGES[index][0])

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111318; color: #edf0f6;
                font-family: Segoe UI; font-size: 10pt; }
            #sidebar { background: #191c23; border-right: 1px solid #292e39; }
            #brand { font-size: 19pt; font-weight: 700; padding: 4px 2px 18px; }
            #navigation { background: transparent; border: 0; outline: 0; }
            #navigation::item { padding: 12px 12px; border-radius: 7px;
                color: #b8bfcc; }
            #navigation::item:selected { background: #2c3444; color: #ffffff; }
            #pageTitle { font-size: 18pt; font-weight: 650; }
            #sectionTitle { font-size: 15pt; font-weight: 600; }
            #muted { color: #9ba4b4; }
            #status { color: #e5bd70; padding: 7px 11px;
                background: #30291d; border-radius: 10px; }
            #panel { background: #1a1e27; border: 1px solid #2b3240;
                border-radius: 12px; }
            #notice { color: #bac7da; background: #202a39;
                border-radius: 8px; padding: 14px; }
        """)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FunPay Assistant")
    window = DesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
