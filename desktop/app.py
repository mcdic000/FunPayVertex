"""Qt desktop shell and process controller for FunPay Vertex."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DesktopWindow(QMainWindow):
    """Main application window."""

    PROTOCOL_PREFIX = "FPV_DESKTOP:"
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
        self.project_root = Path(__file__).resolve().parents[1]
        self._stdout_buffer = ""
        self._closing = False

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

        self.engine_button = QPushButton("Запустить движок")
        self.engine_button.setObjectName("primaryButton")
        self.engine_button.clicked.connect(self._toggle_engine)
        topbar.addWidget(self.engine_button)
        content_layout.addLayout(topbar)

        self.pages = QStackedWidget()
        for title, description in self.PAGES:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 10, 0, 0)
            page_layout.setSpacing(14)

            card = QFrame()
            card.setObjectName("panel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(22, 20, 22, 20)
            card_layout.setSpacing(10)

            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            intro = QLabel(description)
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            card_layout.addWidget(heading)
            card_layout.addWidget(intro)

            if title == "Главная":
                self.engine_details = QLabel(
                    "Движок остановлен. Для подключения нужна готовая конфигурация Vertex."
                )
                self.engine_details.setWordWrap(True)
                self.engine_details.setObjectName("notice")
                card_layout.addWidget(self.engine_details)

                activity_heading = QLabel("Последние события")
                activity_heading.setObjectName("sectionTitle")
                card_layout.addSpacing(8)
                card_layout.addWidget(activity_heading)

                self.activity_list = QListWidget()
                self.activity_list.setObjectName("activityList")
                self.activity_list.setMaximumHeight(190)
                card_layout.addWidget(self.activity_list)
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

        self.engine_process = QProcess(self)
        self.engine_process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.engine_process.readyReadStandardOutput.connect(self._read_engine_output)
        self.engine_process.started.connect(self._on_engine_started)
        self.engine_process.finished.connect(self._on_engine_finished)
        self.engine_process.errorOccurred.connect(self._on_engine_error)

        self._apply_style()

    def _change_title(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.page_title.setText(self.PAGES[index][0])

    def _toggle_engine(self) -> None:
        if self.engine_process.state() != QProcess.ProcessState.NotRunning:
            self._stop_engine()
            return

        config_path = self.project_root / "configs" / "_main.cfg"
        if not config_path.is_file():
            QMessageBox.information(
                self,
                "Нужна первичная настройка",
                "Не найден файл configs/_main.cfg. Сначала запусти Start.bat "
                "в корневой папке FunPay Vertex и заверши мастер настройки.",
            )
            self.engine_details.setText("Сначала выполни первичную настройку Vertex через Start.bat.")
            return

        answer = QMessageBox.warning(
            self,
            "Запуск движка FunPay Vertex",
            "Будут загружены настройки из configs. Если в них включены "
            "автоответы, автовыдача, автоподнятие или другие автоматизации, "
            "они начнут работать вместе с движком. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._stdout_buffer = ""
        self.activity_list.clear()
        self.connection_badge.setText("● Запуск...")
        self.engine_details.setText("Запускаю Vertex и проверяю подключение к FunPay...")
        self.engine_button.setText("Отключить движок")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        self.engine_process.setProcessEnvironment(environment)
        self.engine_process.setWorkingDirectory(str(self.project_root))
        self.engine_process.start(
            sys.executable,
            ["-u", "-m", "desktop.engine_runner"],
        )

    def _stop_engine(self) -> None:
        if self.engine_process.state() == QProcess.ProcessState.NotRunning:
            return
        self.connection_badge.setText("● Отключение...")
        self.engine_details.setText("Останавливаю отдельный процесс движка...")
        self.engine_button.setEnabled(False)
        self.engine_process.terminate()
        QTimer.singleShot(1800, self._force_stop_engine)

    def _force_stop_engine(self) -> None:
        if self.engine_process.state() != QProcess.ProcessState.NotRunning:
            self.engine_process.kill()

    def _on_engine_started(self) -> None:
        self.connection_badge.setText("● Запуск...")
        self.engine_details.setText("Процесс Vertex запущен. Ожидаю авторизацию и загрузку профиля...")
        self._add_activity("Процесс Vertex запущен")

    def _on_engine_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self.connection_badge.setText("● Не подключено")
        self.engine_button.setText("Запустить движок")
        self.engine_button.setEnabled(True)
        if self._closing:
            return
        if exit_code == 0:
            self.engine_details.setText("Движок Vertex остановлен.")
        else:
            self.engine_details.setText(
                "Движок завершился с ошибкой. Проверь logs/log.log и зависимости Python."
            )

    def _on_engine_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.connection_badge.setText("● Ошибка запуска")
            self.engine_details.setText(
                "Не удалось запустить Python-процесс. Проверь Python 3.11+ и установку зависимостей."
            )
            self.engine_button.setText("Запустить движок")
            self.engine_button.setEnabled(True)

    def _read_engine_output(self) -> None:
        chunk = bytes(self.engine_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            if not line.startswith(self.PROTOCOL_PREFIX):
                continue
            try:
                message = json.loads(line[len(self.PROTOCOL_PREFIX):])
            except json.JSONDecodeError:
                continue
            self._handle_engine_message(message)

    def _handle_engine_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "initializing":
            self.connection_badge.setText("● Авторизация...")
            self.engine_details.setText("Vertex загружается и подключается к FunPay...")
        elif kind == "connected":
            username = message.get("username") or "FunPay"
            lots_count = message.get("lots_count", 0)
            self.connection_badge.setText(f"● {username}")
            self.engine_details.setText(
                f"Подключено к аккаунту {username}. Загружено лотов: {lots_count}."
            )
            self._add_activity(f"Подключён аккаунт {username}; лотов: {lots_count}")
        elif kind == "setup_required":
            self.connection_badge.setText("● Нужна настройка")
            self.engine_details.setText(message.get("message", "Сначала настрой Vertex."))
        elif kind == "engine_error":
            self.connection_badge.setText("● Ошибка подключения")
            self.engine_details.setText(message.get("message", "Ошибка запуска движка."))
            self._add_activity("Ошибка запуска движка; подробности в logs/log.log")
        elif kind == "activity":
            title = message.get("title", "Событие FunPay")
            event_name = message.get("event", "")
            self._add_activity(f"{title} ({event_name})")

    def _add_activity(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.activity_list.insertItem(0, f"{timestamp}  ·  {text}")
        while self.activity_list.count() > 20:
            self.activity_list.takeItem(self.activity_list.count() - 1)

    def closeEvent(self, event) -> None:
        self._closing = True
        if self.engine_process.state() != QProcess.ProcessState.NotRunning:
            # The engine has several long-running worker threads; terminate the
            # child process as a unit so no background poller is left behind.
            self.engine_process.kill()
            self.engine_process.waitForFinished(1200)
        event.accept()

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
            #activityList { background: #151922; border: 1px solid #2b3240;
                border-radius: 8px; padding: 6px; color: #d1d7e2; }
            QPushButton#primaryButton { background: #526fe5; color: white;
                border: 0; border-radius: 8px; padding: 9px 14px;
                font-weight: 600; }
            QPushButton#primaryButton:hover { background: #6380f0; }
            QPushButton#primaryButton:disabled { background: #343b4b; color: #8d96a8; }
        """)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FunPay Assistant")
    window = DesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
