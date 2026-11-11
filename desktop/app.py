"""Qt desktop interface for FunPay Vertex."""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QFileDialog, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QScrollArea,
    QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
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
        self._lots: dict[str, dict] = {}
        self._activity_history: list[tuple[str, str]] = []
        self.preference_checks: dict[str, QCheckBox] = {}
        self._analytics_loaded = False

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
        sidebar_footer = QLabel("Desktop • ранняя версия")
        sidebar_footer.setObjectName("muted")
        sidebar_layout.addWidget(sidebar_footer)

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
        self.order_search = QLineEdit()
        self.order_search.setPlaceholderText("Поиск по ID, покупателю или описанию...")
        self.order_search.textChanged.connect(self._filter_orders)
        order_toolbar.addWidget(self.order_search, 1)
        self.orders_summary = QLabel("Заказы ещё не загружены")
        self.orders_summary.setObjectName("muted")
        order_toolbar.addWidget(self.orders_summary)
        order_toolbar.addStretch(1)
        refresh_orders = QPushButton("Обновить")
        refresh_orders.clicked.connect(lambda: self._send_command("get_orders"))
        order_toolbar.addWidget(refresh_orders)
        export_orders = QPushButton("Экспорт CSV")
        export_orders.clicked.connect(
            lambda: self._export_table_csv(self.order_table, "funpay_orders.csv")
        )
        order_toolbar.addWidget(export_orders)
        orders_box.addLayout(order_toolbar)
        self.order_table = QTableWidget(0, 6)
        self.order_table.setHorizontalHeaderLabels(
            ["ID", "Покупатель", "Описание", "Сумма", "Статус", "Дата"]
        )
        self.order_table.setObjectName("dataTable")
        self.order_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.order_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.order_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.order_table.cellDoubleClicked.connect(self._open_order_details)
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
        self.image_button = QPushButton("Фото")
        self.image_button.setToolTip("Отправить изображение в личный чат")
        self.image_button.clicked.connect(self._send_chat_image)
        compose.addWidget(self.image_button)
        self.send_button = QPushButton("Отправить")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self._send_chat_message)
        compose.addWidget(self.send_button)
        conversation_box.addLayout(compose)
        messages_layout.addWidget(conversation_panel, 1)
        self.pages.addWidget(messages_page)

        # Automation controls
        automation_page = QWidget()
        automation_layout = QVBoxLayout(automation_page)
        automation_layout.setContentsMargins(0, 8, 0, 0)
        automation_panel, automation_box = self._panel(
            "Автоматизации Vertex",
            "Переключатели управляют существующими функциями Vertex. Правила выдачи и автоответов "
            "по-прежнему хранятся в локальных конфигурационных файлах."
        )
        automation_note = QLabel(
            "Перед включением проверь шаблоны и товары в configs/auto_delivery.cfg и "
            "configs/auto_response.cfg. Автоматизации начнут выполнять действия в аккаунте сразу "
            "после запуска движка."
        )
        automation_note.setObjectName("notice")
        automation_note.setWordWrap(True)
        automation_box.addWidget(automation_note)
        self.auto_delivery_check = QCheckBox("Автоматическая выдача товаров")
        self.auto_response_check = QCheckBox("Автоматические ответы в чатах")
        self.auto_raise_check = QCheckBox("Автоматическое поднятие лотов")
        for checkbox in (self.auto_delivery_check, self.auto_response_check, self.auto_raise_check):
            checkbox.setObjectName("automationCheck")
            automation_box.addWidget(checkbox)
        save_automations = QPushButton("Сохранить настройки")
        save_automations.setObjectName("primaryButton")
        save_automations.clicked.connect(self._save_automation_settings)
        automation_box.addWidget(save_automations)
        self.automation_status = QLabel("Подключи аккаунт, чтобы загрузить настройки.")
        self.automation_status.setObjectName("muted")
        automation_box.addWidget(self.automation_status)
        automation_box.addStretch(1)
        automation_layout.addWidget(automation_panel, 1)
        self.pages.addWidget(automation_page)

        # Lot management
        lots_page = QWidget()
        lots_layout = QVBoxLayout(lots_page)
        lots_layout.setContentsMargins(0, 8, 0, 0)
        lots_panel, lots_box = self._panel(
            "Мои лоты",
            "Загружаются из профиля FunPay. Обычные и валютные предложения показываются отдельно по типу."
        )
        lots_toolbar = QHBoxLayout()
        self.lot_search = QLineEdit()
        self.lot_search.setPlaceholderText("Поиск по ID, названию, категории или серверу...")
        self.lot_search.textChanged.connect(self._filter_lots)
        lots_toolbar.addWidget(self.lot_search, 1)
        self.lots_summary = QLabel("Лоты ещё не загружены")
        self.lots_summary.setObjectName("muted")
        lots_toolbar.addWidget(self.lots_summary)
        refresh_lots = QPushButton("Обновить")
        refresh_lots.clicked.connect(lambda: self._send_command("get_lots"))
        lots_toolbar.addWidget(refresh_lots)
        lots_box.addLayout(lots_toolbar)
        self.lot_table = QTableWidget(0, 8)
        self.lot_table.setHorizontalHeaderLabels(
            ["ID", "Категория", "Название", "Сервер / сторона", "Кол-во", "Цена", "Тип", "Статус"]
        )
        self.lot_table.setObjectName("dataTable")
        self.lot_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lot_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lot_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lot_table.verticalHeader().setVisible(False)
        self.lot_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (0, 1, 3, 4, 5, 6, 7):
            self.lot_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        lots_box.addWidget(self.lot_table, 1)
        lot_actions = QHBoxLayout()
        edit_lot_button = QPushButton("Изменить выбранный")
        edit_lot_button.setObjectName("primaryButton")
        edit_lot_button.clicked.connect(self._edit_selected_lot)
        lot_actions.addWidget(edit_lot_button)
        delete_lot_button = QPushButton("Удалить обычный лот")
        delete_lot_button.clicked.connect(self._delete_selected_lot)
        lot_actions.addWidget(delete_lot_button)
        open_lot_button = QPushButton("Открыть на FunPay")
        open_lot_button.clicked.connect(self._open_selected_lot)
        lot_actions.addWidget(open_lot_button)
        export_lots = QPushButton("Экспорт CSV")
        export_lots.clicked.connect(
            lambda: self._export_table_csv(self.lot_table, "funpay_lots.csv")
        )
        lot_actions.addWidget(export_lots)
        self.raise_category_combo = QComboBox()
        self.raise_category_combo.setMinimumWidth(170)
        self.raise_category_combo.addItem("Выбери игру для поднятия", None)
        lot_actions.addWidget(self.raise_category_combo)
        raise_category_button = QPushButton("Поднять лоты")
        raise_category_button.clicked.connect(self._raise_selected_category)
        lot_actions.addWidget(raise_category_button)
        lot_actions.addStretch(1)
        lots_box.addLayout(lot_actions)
        self.lot_status = QLabel("Изменения отправляются напрямую через API Vertex.")
        self.lot_status.setObjectName("muted")
        lots_box.addWidget(self.lot_status)
        lots_layout.addWidget(lots_panel, 1)
        self.pages.addWidget(lots_page)

        # Analytics
        analytics_page = QWidget()
        analytics_layout = QVBoxLayout(analytics_page)
        analytics_layout.setContentsMargins(0, 8, 0, 0)
        analytics_panel, analytics_box = self._panel(
            "Статистика продаж",
            "Показатели рассчитываются по истории продаж, которую возвращает FunPay для подключённого аккаунта."
        )
        analytics_toolbar = QHBoxLayout()
        self.analytics_summary = QLabel("Статистика ещё не загружена")
        self.analytics_summary.setObjectName("notice")
        self.analytics_summary.setWordWrap(True)
        analytics_toolbar.addWidget(self.analytics_summary, 1)
        refresh_analytics = QPushButton("Пересчитать")
        refresh_analytics.clicked.connect(lambda: self._send_command("get_analytics"))
        analytics_toolbar.addWidget(refresh_analytics)
        export_analytics = QPushButton("Экспорт CSV")
        export_analytics.clicked.connect(
            lambda: self._export_table_csv(self.analytics_table, "funpay_analytics.csv")
        )
        analytics_toolbar.addWidget(export_analytics)
        analytics_box.addLayout(analytics_toolbar)
        self.analytics_table = QTableWidget(0, 3)
        self.analytics_table.setHorizontalHeaderLabels(["Дата", "Заказов", "Сумма"])
        self.analytics_table.setObjectName("dataTable")
        self.analytics_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.analytics_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.analytics_table.verticalHeader().setVisible(False)
        self.analytics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.analytics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.analytics_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        analytics_box.addWidget(self.analytics_table, 1)
        self.analytics_note = QLabel(
            "Сумма — сумма цен в полученной выборке заказов; она не заменяет баланс FunPay "
            "и не является расчётом чистой прибыли."
        )
        self.analytics_note.setObjectName("muted")
        self.analytics_note.setWordWrap(True)
        analytics_box.addWidget(self.analytics_note)
        analytics_layout.addWidget(analytics_panel, 1)
        self.pages.addWidget(analytics_page)

        # Notifications and activity
        notifications_page = QWidget()
        notifications_layout = QVBoxLayout(notifications_page)
        notifications_layout.setContentsMargins(0, 8, 0, 0)
        notifications_panel, notifications_box = self._panel(
            "Журнал событий",
            "Здесь отображаются новые заказы, сообщения, ошибки и другие события текущего сеанса."
        )
        notifications_toolbar = QHBoxLayout()
        self.notifications_summary = QLabel("Событий пока нет")
        self.notifications_summary.setObjectName("muted")
        notifications_toolbar.addWidget(self.notifications_summary)
        notifications_toolbar.addStretch(1)
        clear_notifications = QPushButton("Очистить журнал")
        clear_notifications.clicked.connect(self._clear_notifications)
        notifications_toolbar.addWidget(clear_notifications)
        notifications_box.addLayout(notifications_toolbar)
        self.notifications_list = QListWidget()
        self.notifications_list.setObjectName("activityList")
        notifications_box.addWidget(self.notifications_list, 1)
        notifications_layout.addWidget(notifications_panel, 1)
        self.pages.addWidget(notifications_page)

        # Additional local Vertex preferences
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(0, 8, 0, 0)
        settings_panel, settings_box = self._panel(
            "Настройки Vertex",
            "Безопасные переключатели из локального configs/_main.cfg. Секреты и токены приложение не показывает."
        )
        settings_note = QLabel(
            "Изменение некоторых параметров влияет на уведомления, обработку сообщений и поведение бота. "
            "Не меняй настройки, смысл которых тебе неизвестен."
        )
        settings_note.setObjectName("notice")
        settings_note.setWordWrap(True)
        settings_box.addWidget(settings_note)
        preference_labels = {
            "FunPay.multiDelivery": "Множественная выдача",
            "FunPay.autoRestore": "Восстанавливать лоты после продажи",
            "FunPay.autoDisable": "Автоматически отключать лоты",
            "FunPay.oldMsgGetMode": "Использовать старый режим получения сообщений",
            "FunPay.keepSentMessagesUnread": "Оставлять отправленные сообщения непрочитанными",
            "Greetings.ignoreSystemMessages": "Игнорировать системные сообщения приветствиями",
            "Greetings.onlyNewChats": "Приветствовать только новые чаты",
            "Greetings.sendGreetings": "Отправлять приветствия",
            "BlockList.blockDelivery": "Блокировать автовыдачу",
            "BlockList.blockResponse": "Блокировать автоответы",
            "BlockList.blockNewMessageNotification": "Не уведомлять о новых сообщениях",
            "BlockList.blockNewOrderNotification": "Не уведомлять о новых заказах",
            "BlockList.blockCommandNotification": "Не уведомлять о командах",
            "NewMessageView.includeMyMessages": "Учитывать мои сообщения",
            "NewMessageView.includeFPMessages": "Учитывать сообщения FunPay",
            "NewMessageView.includeBotMessages": "Учитывать сообщения ботов",
            "NewMessageView.notifyOnlyMyMessages": "Уведомлять только о моих сообщениях",
            "NewMessageView.notifyOnlyFPMessages": "Уведомлять только о системных сообщениях FunPay",
            "NewMessageView.notifyOnlyBotMessages": "Уведомлять только о сообщениях ботов",
            "NewMessageView.showImageName": "Показывать имя изображения",
        }
        section_title = None
        for key, label_text in preference_labels.items():
            section_name = key.split(".", 1)[0]
            if section_name != section_title:
                section_title = section_name
                heading = QLabel(section_name)
                heading.setObjectName("sectionTitle")
                settings_box.addWidget(heading)
            checkbox = QCheckBox(label_text)
            checkbox.setObjectName("automationCheck")
            self.preference_checks[key] = checkbox
            settings_box.addWidget(checkbox)
        preference_actions = QHBoxLayout()
        save_preferences = QPushButton("Сохранить дополнительные настройки")
        save_preferences.setObjectName("primaryButton")
        save_preferences.clicked.connect(self._save_preferences)
        preference_actions.addWidget(save_preferences)
        open_config_folder = QPushButton("Открыть папку configs")
        open_config_folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project_root / "configs")))
        )
        preference_actions.addWidget(open_config_folder)
        open_auto_response = QPushButton("Правила автоответов")
        open_auto_response.clicked.connect(self._open_auto_response_config)
        preference_actions.addWidget(open_auto_response)
        open_auto_delivery = QPushButton("Товары автовыдачи")
        open_auto_delivery.clicked.connect(self._open_auto_delivery_config)
        preference_actions.addWidget(open_auto_delivery)
        preference_actions.addStretch(1)
        settings_box.addLayout(preference_actions)
        self.preferences_status = QLabel("Подключи аккаунт, чтобы загрузить параметры.")
        self.preferences_status.setObjectName("muted")
        settings_box.addWidget(self.preferences_status)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidget(settings_panel)
        settings_layout.addWidget(settings_scroll, 1)
        self.pages.addWidget(settings_page)

    def _change_title(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.page_title.setText(self.PAGES[index][0])
            if index == 1 and self.engine_process.state() == QProcess.ProcessState.Running:
                if self.order_table.rowCount() == 0:
                    self._send_command("get_orders")
            elif index == 2 and self.engine_process.state() == QProcess.ProcessState.Running:
                if not self._chats:
                    self._send_command("get_chats")
            elif self.engine_process.state() == QProcess.ProcessState.Running:
                if index == 3:
                    self._send_command("get_settings")
                elif index == 4 and not self._lots:
                    self._send_command("get_lots")
                elif index == 5 and not self._analytics_loaded:
                    self._send_command("get_analytics")
                elif index == 7:
                    self._send_command("get_preferences")

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
            self._send_command("get_settings")
            self._send_command("get_lots")
            self._send_command("get_analytics")
            self._send_command("get_preferences")
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
            elif message.get("target") == "analytics":
                self._send_command("get_analytics")
        elif kind == "order_event":
            self._add_activity(f"{message.get('event', 'Заказ')}: #{message.get('order', {}).get('id', '')}")
            self._upsert_order(message.get("order", {}))
        elif kind == "chat_event":
            self._upsert_chat(message.get("chat", {}))
        elif kind == "message_event":
            self._add_activity(f"Новое сообщение: {message.get('chat_name') or 'чат'}")
            if str(message.get("chat_id")) == self._selected_chat_id:
                self._append_message(message.get("message", {}))
        elif kind == "response":
            self._handle_response(message)

    def _handle_response(self, response: dict) -> None:
        if not response.get("ok"):
            action = response.get("action")
            error = response.get("error", "неизвестная ошибка")
            self._add_activity(f"Ошибка {action}: {error}")
            if action in ("get_lot_editor", "update_lot", "delete_lot"):
                self.lot_status.setText(f"Ошибка работы с лотом: {error}")
            elif action == "update_preferences":
                self.preferences_status.setText(f"Не удалось сохранить настройки: {error}")
            elif action == "update_automation_settings":
                self.automation_status.setText(f"Не удалось сохранить автоматизации: {error}")
            elif action == "send_image":
                QMessageBox.warning(self, "Не удалось отправить изображение", error)
                self.image_button.setEnabled(True)
            elif action == "raise_category":
                self.lot_status.setText(f"Не удалось поднять лоты: {error}")
                QMessageBox.warning(self, "Поднятие лотов", error)
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
        elif action == "get_settings":
            self.auto_delivery_check.setChecked(bool(data.get("auto_delivery")))
            self.auto_response_check.setChecked(bool(data.get("auto_response")))
            self.auto_raise_check.setChecked(bool(data.get("auto_raise")))
            self.automation_status.setText("Настройки загружены из configs/_main.cfg")
        elif action == "get_lots":
            self._set_lots(data.get("lots", []))
        elif action == "get_lot_editor":
            self._show_lot_editor(data)
        elif action in ("update_lot", "delete_lot"):
            self._set_lots(data.get("lots", []))
            self.lot_status.setText(
                f"Лот #{data.get('saved_lot_id') or data.get('deleted_lot_id')} успешно обновлён."
                if action == "update_lot" else "Лот удалён."
            )
            self._add_activity(self.lot_status.text())
        elif action == "raise_category":
            wait = data.get("wait_seconds")
            try:
                wait_text = self._format_wait_time(int(wait)) if wait is not None else "время не указано"
            except (TypeError, ValueError):
                wait_text = "время не указано"
            self.lot_status.setText(
                f"Запрос на поднятие отправлен: {data.get('category_name', 'категория')}. "
                f"Следующая попытка — через {wait_text}."
            )
            self._add_activity(self.lot_status.text())
        elif action == "get_analytics":
            self._render_analytics(data.get("analytics", {}))
        elif action == "get_preferences":
            self._set_preferences(data.get("preferences", {}))
        elif action == "update_preferences":
            self._set_preferences(data.get("preferences", {}))
            self.preferences_status.setText("Дополнительные настройки сохранены.")
            self._add_activity("Настройки Vertex сохранены")
        elif action == "update_automation_settings":
            self.automation_status.setText("Настройки автоматизаций сохранены.")
            self._add_activity("Настройки автоматизаций сохранены")
        elif action == "get_order_details":
            self._show_order_details(data.get("order", {}))
        elif action in ("send_message", "send_image"):
            self.image_button.setEnabled(True)
            self.message_input.clear()
            self._add_activity(
                "Изображение отправлено" if action == "send_image" else "Сообщение отправлено"
            )
            self._send_command(
                "get_chat_history", chat_id=self._selected_chat_id,
                chat_name=self._chats.get(self._selected_chat_id, {}).get("name", "")
            )

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

    def _set_lots(self, lots: list[dict]) -> None:
        self._lots = {str(lot.get("id")): lot for lot in lots if lot.get("id") is not None}
        self.lot_table.setRowCount(len(self._lots))
        for row, (lot_id, lot) in enumerate(self._lots.items()):
            location = " / ".join(part for part in (lot.get("server", ""), lot.get("side", "")) if part)
            amount = "∞" if lot.get("amount") is None else str(lot.get("amount"))
            price = lot.get("price")
            price_text = f"{price} {lot.get('currency', '')}".strip() if price is not None else ""
            lot_type = "Валюта" if lot.get("subcategory_type") == "CURRENCY" else "Обычный"
            status = "Активен" if lot.get("active") else "Отключён"
            if lot.get("auto"):
                status += " · авто"
            values = [
                lot_id, lot.get("subcategory", ""), lot.get("title", ""), location,
                amount, price_text, lot_type, status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, lot)
                self.lot_table.setItem(row, column, item)
        self.lots_summary.setText(f"Лотов: {len(self._lots)}")
        selected_category = self.raise_category_combo.currentData()
        self.raise_category_combo.clear()
        self.raise_category_combo.addItem("Выбери игру для поднятия", None)
        categories: dict[int, dict] = {}
        for lot in self._lots.values():
            if lot.get("subcategory_type") != "COMMON" or lot.get("category_id") is None:
                continue
            category_id = int(lot["category_id"])
            category = categories.setdefault(category_id, {
                "name": lot.get("category_name") or f"Категория {category_id}",
                "count": 0,
            })
            category["count"] += 1
        for category_id, category in sorted(categories.items(), key=lambda item: item[1]["name"].casefold()):
            label = f"{category['name']} ({category['count']} подкатегорий/лотов)"
            self.raise_category_combo.addItem(label, category_id)
        if selected_category is not None:
            index = self.raise_category_combo.findData(selected_category)
            if index >= 0:
                self.raise_category_combo.setCurrentIndex(index)
        self._filter_lots(self.lot_search.text())

    def _filter_lots(self, query: str) -> None:
        needle = query.casefold().strip()
        visible = 0
        for row in range(self.lot_table.rowCount()):
            values = [
                self.lot_table.item(row, column).text()
                if self.lot_table.item(row, column) else ""
                for column in range(self.lot_table.columnCount())
            ]
            matches = not needle or needle in " ".join(values).casefold()
            self.lot_table.setRowHidden(row, not matches)
            visible += int(matches)
        self.lots_summary.setText(
            f"Показано: {visible} из {self.lot_table.rowCount()}"
            if needle else f"Лотов: {self.lot_table.rowCount()}"
        )

    @staticmethod
    def _format_wait_time(seconds: int) -> str:
        seconds = max(0, seconds)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        pieces = []
        if days:
            pieces.append(f"{days} д.")
        if hours:
            pieces.append(f"{hours} ч.")
        if minutes:
            pieces.append(f"{minutes} мин.")
        if seconds and not pieces:
            pieces.append(f"{seconds} сек.")
        return " ".join(pieces) or "0 сек."

    def _raise_selected_category(self) -> None:
        category_id = self.raise_category_combo.currentData()
        if category_id is None:
            QMessageBox.information(self, "Категория не выбрана", "Выбери игру из списка.")
            return
        category_name = self.raise_category_combo.currentText()
        answer = QMessageBox.warning(
            self, "Поднять обычные лоты?",
            f"FunPay получит запрос на поднятие всех обычных лотов игры «{category_name}». "
            "Валютные предложения не поднимаются. Если включено автоподнятие Vertex, "
            "ручной запрос может пересечься с ним; окончательный интервал определяет FunPay. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.lot_status.setText(f"Отправляю запрос на поднятие: {category_name}...")
            self._send_command("raise_category", category_id=category_id)

    def _selected_lot(self) -> dict | None:
        row = self.lot_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Лот не выбран", "Сначала выбери лот в таблице.")
            return None
        item = self.lot_table.item(row, 0)
        lot = item.data(Qt.ItemDataRole.UserRole) if item else None
        return lot if isinstance(lot, dict) else None

    def _edit_selected_lot(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        self.lot_status.setText(f"Загружаю все поля лота #{lot.get('id')}...")
        self._send_command("get_lot_editor", lot_id=str(lot.get("id")))

    def _show_lot_editor(self, data: dict) -> None:
        lot = data.get("lot") or {}
        editor = data.get("editor") or {}
        if not lot or not editor:
            self.lot_status.setText("Не удалось получить поля выбранного лота.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Изменение лота #{lot.get('id')}")
        dialog.setMinimumWidth(540)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        is_currency = bool(editor.get("is_currency"))

        title_input = QLineEdit(str(editor.get("title") or ""))
        title_input.setMaxLength(250)
        form.addRow("Название", title_input)
        description_input = QTextEdit()
        description_input.setPlainText(str(editor.get("description") or ""))
        description_input.setMinimumHeight(115)
        form.addRow("Описание", description_input)

        price_input = QDoubleSpinBox()
        price_input.setRange(0.01, 1000000000.0)
        price_input.setDecimals(2)
        price_input.setSingleStep(1.0)
        try:
            price_input.setValue(float(editor.get("price") or 0.01))
        except (TypeError, ValueError):
            price_input.setValue(0.01)
        form.addRow("Цена", price_input)

        amount_input = QSpinBox()
        amount_input.setRange(0, 1000000000)
        try:
            amount_input.setValue(int(editor.get("amount") or 0))
        except (TypeError, ValueError):
            amount_input.setValue(0)
        if editor.get("auto_delivery") and not is_currency:
            amount_input.setEnabled(False)
        form.addRow("Количество", amount_input)

        active_input = QCheckBox("Лот активен и отображается покупателям")
        active_input.setChecked(bool(editor.get("active")))
        form.addRow("Статус", active_input)
        layout.addLayout(form)

        if is_currency:
            title_input.setEnabled(False)
            description_input.setEnabled(False)
            note_text = (
                "Валютные предложения редактируются отдельной формой ChipFields. "
                "Здесь доступны цена, количество и активность."
            )
        elif editor.get("auto_delivery"):
            note_text = (
                "У лота включена встроенная автовыдача FunPay. Количество зависит от списка товаров "
                "и не меняется этим экраном. Остальные поля можно редактировать."
            )
        else:
            note_text = "Загружены полные поля лота; остальные параметры сохраняются без изменений."
        note = QLabel(note_text)
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = {
            "price": price_input.value(),
            "active": active_input.isChecked(),
        }
        if not (editor.get("auto_delivery") and not is_currency):
            values["amount"] = amount_input.value()
        if not is_currency:
            values["title"] = title_input.text().strip()
            values["description"] = description_input.toPlainText()
        answer = QMessageBox.question(
            self, "Сохранить изменения?",
            f"Сохранить изменения лота #{lot.get('id')} на FunPay?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.lot_status.setText(f"Сохраняю лот #{lot.get('id')}...")
        self._send_command("update_lot", lot_id=str(lot.get("id")), values=values)

    def _delete_selected_lot(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        if lot.get("subcategory_type") == "CURRENCY":
            QMessageBox.information(
                self, "Неподдерживаемая операция",
                "Удаление валютных предложений через этот экран не поддерживается. "
                "Их цену, количество и активность можно изменить.",
            )
            return
        answer = QMessageBox.warning(
            self, "Удалить лот?",
            f"Лот #{lot.get('id')} будет удалён с FunPay. Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.lot_status.setText(f"Удаляю лот #{lot.get('id')}...")
            self._send_command("delete_lot", lot_id=str(lot.get("id")))

    def _open_selected_lot(self) -> None:
        lot = self._selected_lot()
        if not lot:
            return
        url = lot.get("public_link")
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QMessageBox.information(self, "Ссылка недоступна", "Для этого лота не удалось получить ссылку.")

    def _render_analytics(self, analytics: dict) -> None:
        count = int(analytics.get("orders_count", 0) or 0)
        gross = float(analytics.get("gross_total", 0) or 0)
        statuses = analytics.get("status_counts", {})
        status_text = ", ".join(
            f"{key}: {value}" for key, value in sorted(statuses.items())
        ) or "статусы не получены"
        self.analytics_summary.setText(
            f"Заказов в выборке: {count}  |  Сумма цен: {gross:,.2f}\n{status_text}"
            + ("\nПоказаны последние страницы; более старые продажи остались за пределами выборки."
               if analytics.get("has_more") else "")
        )
        daily = analytics.get("daily", [])
        self.analytics_table.setRowCount(len(daily))
        for row, item in enumerate(daily):
            values = [
                item.get("date", ""),
                item.get("orders", 0),
                f"{float(item.get('amount', 0) or 0):,.2f}",
            ]
            for column, value in enumerate(values):
                self.analytics_table.setItem(row, column, QTableWidgetItem(str(value)))
        self._analytics_loaded = True

    def _set_preferences(self, preferences: dict) -> None:
        for key, checkbox in self.preference_checks.items():
            if key in preferences:
                checkbox.setChecked(bool(preferences[key]))
        self.preferences_status.setText("Параметры загружены из configs/_main.cfg")

    def _save_preferences(self) -> None:
        if self.engine_process.state() != QProcess.ProcessState.Running:
            QMessageBox.information(
                self, "Движок не запущен",
                "Подключи аккаунт, чтобы менять настройки Vertex.",
            )
            return
        preferences = {
            key: checkbox.isChecked()
            for key, checkbox in self.preference_checks.items()
        }
        answer = QMessageBox.question(
            self, "Сохранить дополнительные настройки?",
            "Настройки будут записаны в configs/_main.cfg. Некоторые параметры влияют "
            "на обработку сообщений и автоматизаций Vertex.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._send_command("update_preferences", preferences=preferences)

    def _open_auto_response_config(self) -> None:
        path = self.project_root / "configs" / "auto_response.cfg"
        if not path.is_file():
            QMessageBox.information(self, "Файл не найден", "Сначала выполни первичную настройку Vertex.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_auto_delivery_config(self) -> None:
        path = self.project_root / "configs" / "auto_delivery.cfg"
        if not path.is_file():
            QMessageBox.information(self, "Файл не найден", "Сначала выполни первичную настройку Vertex.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _export_table_csv(self, table: QTableWidget, default_name: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить таблицу", str(self.project_root / default_name),
            "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file, delimiter=";")
                writer.writerow([
                    table.horizontalHeaderItem(column).text()
                    if table.horizontalHeaderItem(column) else f"Колонка {column + 1}"
                    for column in range(table.columnCount())
                ])
                for row in range(table.rowCount()):
                    writer.writerow([
                        table.item(row, column).text()
                        if table.item(row, column) else ""
                        for column in range(table.columnCount())
                    ])
        except OSError as exc:
            QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось сохранить CSV: {exc}")
            return
        self._add_activity(f"Таблица экспортирована: {Path(path).name}")
        QMessageBox.information(
            self, "Экспорт завершён", f"Таблица сохранена в файл:\n{path}"
        )

    def _clear_notifications(self) -> None:
        self._activity_history.clear()
        self.notifications_list.clear()
        self.notifications_summary.setText("Журнал очищен")

    def _save_automation_settings(self) -> None:
        if self.engine_process.state() != QProcess.ProcessState.Running:
            QMessageBox.information(self, "Движок не запущен",
                                    "Подключи аккаунт, чтобы менять настройки автоматизаций.")
            return
        settings = {
            "autoDelivery": self.auto_delivery_check.isChecked(),
            "autoResponse": self.auto_response_check.isChecked(),
            "autoRaise": self.auto_raise_check.isChecked(),
        }
        if any(settings.values()):
            answer = QMessageBox.warning(
                self, "Включение автоматизаций",
                "Включённые автоматизации будут выполнять действия на твоём аккаунте FunPay. "
                "Убедись, что правила автовыдачи и автоответов настроены правильно. Сохранить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._send_command("update_automation_settings", settings=settings)

    def _filter_orders(self, query: str) -> None:
        needle = query.casefold().strip()
        visible = 0
        for row in range(self.order_table.rowCount()):
            values = []
            for column in range(self.order_table.columnCount()):
                item = self.order_table.item(row, column)
                values.append(item.text() if item else "")
            matches = not needle or needle in " ".join(values).casefold()
            self.order_table.setRowHidden(row, not matches)
            visible += int(matches)
        self.orders_summary.setText(
            f"Показано: {visible} из {self.order_table.rowCount()}"
            if needle else f"Загружено заказов: {self.order_table.rowCount()}"
        )

    def _open_order_details(self, row: int, _column: int) -> None:
        item = self.order_table.item(row, 0)
        if item and item.text():
            self._send_command("get_order_details", order_id=item.text())

    def _show_order_details(self, order: dict) -> None:
        if not order:
            return
        lines = [
            f"Заказ: #{order.get('id', '')}",
            f"Статус: {order.get('status', '')}",
            f"Покупатель: {order.get('buyer', '')} (ID {order.get('buyer_id', '')})",
            f"Сумма: {order.get('sum', '')} {order.get('currency', '')}",
            f"Количество: {order.get('amount', '')}",
            f"Категория: {order.get('category', '')}",
            f"Сервер: {order.get('server', '')}",
            f"Платформа: {order.get('side', '')}",
            f"Игрок: {order.get('player', '')}",
        ]
        fields = order.get("fields", [])
        if fields:
            lines.append("")
            lines.append("Поля заказа:")
            lines.extend(f"• {field.get('name') or field.get('id')}: {field.get('value')}"
                         for field in fields)
        review = order.get("review")
        if review:
            lines.extend(["", f"Отзыв: {review.get('stars', '')}/5",
                          review.get("text", "") or ""])
        QMessageBox.information(self, f"Информация о заказе #{order.get('id', '')}",
                                "\n".join(lines))

    def _upsert_order(self, order: dict) -> None:
        order_id = str(order.get("id", ""))
        if not order_id:
            return
        target_row = None
        for row in range(self.order_table.rowCount()):
            item = self.order_table.item(row, 0)
            if item and item.text() == order_id:
                target_row = row
                break
        if target_row is None:
            target_row = 0
            self.order_table.insertRow(target_row)
        price = order.get("price")
        price_text = f"{price} {order.get('currency', '')}".strip() if price is not None else ""
        values = [order_id, order.get("buyer", ""), order.get("description", ""),
                  price_text, order.get("status", ""), order.get("date", "")]
        for column, value in enumerate(values):
            self.order_table.setItem(target_row, column, QTableWidgetItem(str(value)))
        self.orders_summary.setText(f"Заказов в списке: {self.order_table.rowCount()}")

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
            self._append_message(message)

    def _append_message(self, message: dict) -> None:
        message_id = str(message.get("id", ""))
        if message_id:
            for index in range(self.message_list.count()):
                existing = self.message_list.item(index)
                if existing.data(Qt.ItemDataRole.UserRole) == message_id:
                    return
        author = message.get("author") or "Система"
        body = message.get("text") or (f"[Изображение] {message.get('image')}" if message.get("image") else "[Без текста]")
        label = f"{author}: {body}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, message_id)
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

    def _send_chat_image(self) -> None:
        if not self._selected_chat_id:
            QMessageBox.information(self, "Чат не выбран", "Сначала выбери диалог.")
            return
        if self.engine_process.state() != QProcess.ProcessState.Running:
            QMessageBox.information(self, "Движок не запущен", "Сначала подключи аккаунт.")
            return
        chat = self._chats.get(self._selected_chat_id, {})
        if not chat:
            QMessageBox.information(self, "Чат не найден", "Обнови список чатов и выбери диалог ещё раз.")
            return
        image_path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать изображение", "",
            "Изображения (*.png *.jpg *.jpeg *.gif *.webp)"
        )
        if not image_path:
            return
        answer = QMessageBox.question(
            self, "Отправить изображение?",
            "Загрузить выбранное изображение и отправить его в этот личный чат FunPay? "
            "Размер файла должен быть не более 10 МБ.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.image_button.setEnabled(False)
            self._send_command(
                "send_image", chat_id=self._selected_chat_id, image_path=image_path
            )

    def _add_activity(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{timestamp}  ·  {text}"
        self.activity_list.insertItem(0, entry)
        while self.activity_list.count() > 60:
            self.activity_list.takeItem(self.activity_list.count() - 1)
        self._activity_history.insert(0, (timestamp, text))
        self._activity_history = self._activity_history[:250]
        if hasattr(self, "notifications_list"):
            self.notifications_list.insertItem(0, entry)
            while self.notifications_list.count() > 250:
                self.notifications_list.takeItem(self.notifications_list.count() - 1)
            self.notifications_summary.setText(f"Событий в этом сеансе: {len(self._activity_history)}")

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
            QCheckBox#automationCheck { spacing: 10px; padding: 10px 4px; }
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
