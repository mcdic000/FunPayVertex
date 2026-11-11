"""Qt desktop interface for FunPay Vertex."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)


class DesktopWindow(QMainWindow):
    PROTOCOL_PREFIX = "FPV_DESKTOP:"
    PAGES = (
        ("Главная", "Обзор и состояние подключения"),
        ("Заказы", "Продажи и статусы заказов"),
        ("Сообщения", "Чаты, история переписки и отправка сообщений"),
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
        self._request_counter = 0
        self._selected_chat_id: str | None = None
        self._chats: dict[str, dict] = {}

        self.setWindowTitle("FunPay Assistant")
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)

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
        sidebar_layout.addWidget(QLabel("Desktop • ранняя версия", objectName="muted"))

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
        self._build_pages()
        content_layout.addWidget(self.pages, 1)
        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.currentRowChanged.connect(self._change_title)
        self.navigation.setCurrentRow(0)

        self.engine_process = QProcess(self)
        self.engine_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.engine_process.readyReadStandardOutput.connect(self._read_engine_output)
        self.engine_process.started.connect(self._on_engine_started)
        self.engine_process.finished.connect(self._on_engine_finished)
        self.engine_process.errorOccurred.connect(self._on_engine_error)
        self._apply_style()

    def _panel(self, title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        if description:
            intro = QLabel(description)
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            layout.addWidget(intro)
        return panel, layout

    def _build_pages(self) -> None:
        # Home
        home = QWidget()
        home_layout = QVBoxLayout(home)
        home_layout.setContentsMargins(0, 8, 0, 0)
        panel, layout = self._panel("Состояние движка",
            "Подключение к FunPay выполняется существующим движком Vertex.")
        self.engine_details = QLabel(
            "Движок остановлен. Для подключения нужна готовая конфигурация Vertex."
        )
        self.engine_details.setObjectName("notice")
        self.engine_details.setWordWrap(True)
        layout.addWidget(self.engine_details)
        activity_title = QLabel("Последние события")
        activity_title.setObjectName("sectionTitle")
        layout.addWidget(activity_title)
        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        layout.addWidget(self.activity_list)
        home_layout.addWidget(panel, 1)
        self.pages.addWidget(home)

        # Orders
        orders_page = QWidget()
        orders_layout = QVBoxLayout(orders_page)
        orders_layout.setContentsMargins(0, 8, 0, 0)
        orders_panel, orders_box = self._panel("Заказы",
            "Список продаж FunPay. Нажми «Обновить», чтобы запросить актуальные данные.")
        order_toolbar = QHBoxLayout()
        self.orders_summary = QLabel("Заказы ещё не загружены")
        self.orders_summary.setObjectName("muted")
        order_toolbar.addWidget(self.orders_summary)
        order_toolbar.addStretch(1)
        refresh_orders = QPushButton("Обновить")
        refresh_orders.clicked.connect(lambda: self._send_command("get_orders"))
        order_toolbar.addWidget(refresh_orders)
        orders_box.addLayout(order_toolbar)
        self.order_table = QTableWidget(0, 6)
        self.order_table.setHorizontalHeaderLabels(
            ["ID", "Покупатель", "Описание", "Сумма", "Статус", "Дата"]
        )
        self.order_table.setObjectName("dataTable")
        self.order_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.order_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.order_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.order_table.verticalHeader().setVisible(False)
        self.order_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4, 5):
            self.order_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        orders_box.addWidget(self.order_table, 1)
        orders_layout.addWidget(orders_panel, 1)
        self.pages.addWidget(orders_page)

        # Messages
        messages_page = QWidget()
        messages_layout = QHBoxLayout(messages_page)
        messages_layout.setContentsMargins(0, 8, 0, 0)
        messages_layout.setSpacing(14)

        chats_panel, chats_box = self._panel("Диалоги")
        chats_toolbar = QHBoxLayout()
        self.chats_summary = QLabel("Чаты не загружены")
        self.chats_summary.setObjectName("muted")
        chats_toolbar.addWidget(self.chats_summary)
        chats_toolbar.addStretch(1)
        refresh_chats = QPushButton("↻")
        refresh_chats.setToolTip("Обновить чаты")
        refresh_chats.clicked.connect(lambda: self._send_command("get_chats"))
        chats_toolbar.addWidget(refresh_chats)
        chats_box.addLayout(chats_toolbar)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.currentItemChanged.connect(self._on_chat_selected)
        chats_box.addWidget(self.chat_list, 1)
        chats_panel.setMinimumWidth(245)
        chats_panel.setMaximumWidth(320)
        messages_layout.addWidget(chats_panel)

        conversation_panel, conversation_box = self._panel("Переписка")
        self.current_chat_label = QLabel("Выбери чат слева")
        self.current_chat_label.setObjectName("muted")
        conversation_box.addWidget(self.current_chat_label)
        self.message_list = QListWidget()
        self.message_list.setObjectName("messageList")
        conversation_box.addWidget(self.message_list, 1)
        compose = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Напиши сообщение...")
        self.message_input.returnPressed.connect(self._send_chat_message)
        compose.addWidget(self.message_input, 1)
        self.send_button = QPushButton("Отправить")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self._send_chat_message)
        compose.addWidget(self.send_button)
        conversation_box.addLayout(compose)
        messages_layout.addWidget(conversation_panel, 1)
        self.pages.addWidget(messages_page)

        # Other sections are explicit placeholders until their services are implemented.
        for title, description in self.PAGES[3:]:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 8, 0, 0)
            panel, box = self._panel(title, description)
            note = QLabel("Этот раздел подключим следующим этапом. Пока здесь нет рабочих настроек.")
            note.setObjectName("notice")
            note.setWordWrap(True)
            box.addWidget(note)
            box.addStretch(1)
            page_layout.addWidget(panel, 1)
            self.pages.addWidget(page)

    def _change_title(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.page_title.setText(self.PAGES[index][0])
            if index == 1 and self.engine_process.state() == QProcess.ProcessState.Running:
                if self.order_table.rowCount() == 0:
                    self._send_command("get_orders")
            elif index == 2 and self.engine_process.state() == QProcess.ProcessState.Running:
                if not self._chats:
                    self._send_command("get_chats")

    def _toggle_engine(self) -> None:
        if self.engine_process.state() != QProcess.ProcessState.NotRunning:
            self._stop_engine()
            return
        config_path = self.project_root / "configs" / "_main.cfg"
        if not config_path.is_file():
            QMessageBox.information(self, "Нужна первичная настройка",
                "Не найден configs/_main.cfg. Сначала запусти Start.bat "
                "в корневой папке FunPay Vertex и заверши мастер настройки.")
            self.engine_details.setText("Сначала выполни первичную настройку Vertex через Start.bat.")
            return
        answer = QMessageBox.warning(self, "Запуск движка FunPay Vertex",
            "Будут загружены настройки из configs. Если включены автоответы, автовыдача, "
            "автоподнятие или другие автоматизации, они начнут работать. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._stdout_buffer = ""
        self.activity_list.clear()
        self.connection_badge.setText("● Запуск...")
        self.engine_details.setText("Запускаю Vertex и проверяю подключение к FunPay...")
        self.engine_button.setText("Отключить движок")
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.engine_process.setProcessEnvironment(env)
        self.engine_process.setWorkingDirectory(str(self.project_root))
        self.engine_process.start(sys.executable, ["-u", "-m", "desktop.engine_runner"])

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
        if not self._closing:
            self.engine_details.setText(
                "Движок Vertex остановлен." if exit_code == 0 else
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

    def _send_command(self, action: str, **data: object) -> None:
        if self.engine_process.state() != QProcess.ProcessState.Running:
            QMessageBox.information(self, "Движок не запущен",
                "Сначала подключи аккаунт через кнопку «Запустить движок».")
            return
        self._request_counter += 1
        command = {"request_id": self._request_counter, "action": action, **data}
        self.engine_process.write((json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8"))

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
            self.connection_badge.setText(f"● {username}")
            self.engine_details.setText(
                f"Подключено к аккаунту {username}. Загружено лотов: {message.get('lots_count', 0)}."
            )
            self._add_activity(f"Подключён аккаунт {username}")
            self._send_command("get_orders")
            self._send_command("get_chats")
        elif kind == "setup_required":
            self.connection_badge.setText("● Нужна настройка")
            self.engine_details.setText(message.get("message", "Сначала настрой Vertex."))
        elif kind == "engine_error":
            self.connection_badge.setText("● Ошибка подключения")
            self.engine_details.setText(message.get("message", "Ошибка запуска движка."))
            self._add_activity("Ошибка запуска движка; подробности в logs/log.log")
        elif kind == "activity":
            self._add_activity(message.get("title", "Событие FunPay"))
        elif kind == "refresh":
            if message.get("target") == "orders":
                self._send_command("get_orders")
            elif message.get("target") == "chats":
                self._send_command("get_chats")
        elif kind == "order_event":
            self._add_activity(f"{message.get('event', 'Заказ')}: #{message.get('order', {}).get('id', '')}")
            self._upsert_order(message.get("order", {}))
        elif kind == "chat_event":
            self._upsert_chat(message.get("chat", {}))
        elif kind == "message_event":
            self._add_activity(f"Новое сообщение: {message.get('chat_name') or 'чат'}")
            if str(message.get("chat_id")) == self._selected_chat_id:
                self._send_command("get_chat_history", chat_id=self._selected_chat_id)
        elif kind == "response":
            self._handle_response(message)

    def _handle_response(self, response: dict) -> None:
        if not response.get("ok"):
            self._add_activity(f"Ошибка {response.get('action')}: {response.get('error', 'неизвестная ошибка')}")
            return
        action = response.get("action")
        data = response.get("data", {})
        if action == "get_orders":
            self._set_orders(data.get("orders", []))
        elif action == "get_chats":
            self._set_chats(data.get("chats", []))
        elif action == "get_chat_history":
            if str(data.get("chat_id")) == self._selected_chat_id:
                self._set_messages(data.get("messages", []))
        elif action == "send_message":
            self.message_input.clear()
            self._add_activity("Сообщение отправлено")
            self._send_command("get_chat_history", chat_id=self._selected_chat_id)

    def _set_orders(self, orders: list[dict]) -> None:
        self.order_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            amount = order.get("price")
            price = f"{amount} {order.get('currency', '')}" if amount is not None else ""
            values = [order.get("id", ""), order.get("buyer", ""), order.get("description", ""),
                      price, order.get("status", ""), order.get("date", "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, order.get("chat_id"))
                self.order_table.setItem(row, column, item)
        self.orders_summary.setText(f"Загружено заказов: {len(orders)}")

    def _upsert_order(self, order: dict) -> None:
        order_id = str(order.get("id", ""))
        if not order_id:
            return
        for row in range(self.order_table.rowCount()):
            if self.order_table.item(row, 0).text() == order_id:
                orders = []
                for r in range(self.order_table.rowCount()):
                    orders.append({
                        "id": self.order_table.item(r, 0).text(),
                        "buyer": self.order_table.item(r, 1).text(),
                        "description": self.order_table.item(r, 2).text(),
                        "price": self.order_table.item(r, 3).text(),
                        "status": self.order_table.item(r, 4).text(),
                        "date": self.order_table.item(r, 5).text(),
                    })
                orders[row] = {**orders[row], **order}
                self._set_orders(orders)
                return
        self._send_command("get_orders")

    def _set_chats(self, chats: list[dict]) -> None:
        selected = self._selected_chat_id
        self._chats = {str(chat.get("id")): chat for chat in chats}
        self.chat_list.clear()
        for chat_id, chat in self._chats.items():
            unread = "● " if chat.get("unread") else ""
            preview = chat.get("last_message", "")
            label = f"{unread}{chat.get('name', 'Пользователь')}\n{preview[:70]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, chat_id)
            self.chat_list.addItem(item)
            if chat_id == selected:
                self.chat_list.setCurrentItem(item)
        self.chats_summary.setText(f"Чатов: {len(chats)}")

    def _upsert_chat(self, chat: dict) -> None:
        chat_id = str(chat.get("id", ""))
        if not chat_id:
            return
        self._chats[chat_id] = chat
        self._set_chats(list(self._chats.values()))

    def _on_chat_selected(self, current: QListWidgetItem | None,
                          _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        chat_id = current.data(Qt.ItemDataRole.UserRole)
        if not chat_id:
            return
        self._selected_chat_id = str(chat_id)
        chat = self._chats.get(self._selected_chat_id, {})
        self.current_chat_label.setText(chat.get("name", "Переписка"))
        self.message_list.clear()
        self._send_command("get_chat_history", chat_id=self._selected_chat_id,
                           chat_name=chat.get("name", ""))

    def _set_messages(self, messages: list[dict]) -> None:
        self.message_list.clear()
        for message in messages:
            author = message.get("author") or "Система"
            body = message.get("text") or (f"[Изображение] {message.get('image')}" if message.get("image") else "[Без текста]")
            label = f"{author}: {body}"
            item = QListWidgetItem(label)
            item.setToolTip(label)
            self.message_list.addItem(item)
        self.message_list.scrollToBottom()

    def _send_chat_message(self) -> None:
        if not self._selected_chat_id:
            QMessageBox.information(self, "Чат не выбран", "Сначала выбери диалог.")
            return
        text = self.message_input.text().strip()
        if not text:
            return
        answer = QMessageBox.question(self, "Отправить сообщение?",
            "Отправить это сообщение через FunPay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.send_button.setEnabled(False)
            self._send_command("send_message", chat_id=self._selected_chat_id, text=text)
            QTimer.singleShot(800, lambda: self.send_button.setEnabled(True))

    def _add_activity(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.activity_list.insertItem(0, f"{timestamp}  ·  {text}")
        while self.activity_list.count() > 60:
            self.activity_list.takeItem(self.activity_list.count() - 1)

    def closeEvent(self, event) -> None:
        self._closing = True
        if self.engine_process.state() != QProcess.ProcessState.NotRunning:
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
            #navigation::item { padding: 12px; border-radius: 7px; color: #b8bfcc; }
            #navigation::item:selected { background: #2c3444; color: #ffffff; }
            #pageTitle { font-size: 18pt; font-weight: 650; }
            #sectionTitle { font-size: 14pt; font-weight: 600; }
            #muted { color: #9ba4b4; }
            #status { color: #e5bd70; padding: 7px 11px; background: #30291d; border-radius: 10px; }
            #panel { background: #1a1e27; border: 1px solid #2b3240; border-radius: 12px; }
            #notice { color: #bac7da; background: #202a39; border-radius: 8px; padding: 14px; }
            #activityList, #chatList, #messageList, #dataTable {
                background: #151922; border: 1px solid #2b3240; border-radius: 8px;
                padding: 6px; color: #d1d7e2; gridline-color: #2b3240;
            }
            QLineEdit { background: #151922; border: 1px solid #343d4e;
                border-radius: 7px; padding: 10px; color: #edf0f6; }
            QPushButton { background: #303746; color: #edf0f6; border: 0;
                border-radius: 8px; padding: 9px 13px; }
            QPushButton:hover { background: #3c4659; }
            QPushButton#primaryButton { background: #526fe5; color: white; font-weight: 600; }
            QPushButton#primaryButton:hover { background: #6380f0; }
            QHeaderView::section { background: #202633; color: #cbd3e1;
                border: 0; padding: 8px; }
            QTableWidget::item:selected, QListWidget::item:selected {
                background: #2c3444; color: white;
            }
        """)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FunPay Assistant")
    window = DesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
