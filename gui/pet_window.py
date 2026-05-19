"""
桌面宠物主窗口模块
"""

import json
import os
import urllib.request
import threading

from PyQt5.QtWidgets import (
    QMainWindow, QMenu, QSystemTrayIcon, QAction, QLabel,
    QApplication, QDialog, QVBoxLayout, QSlider, QGroupBox,
    QComboBox, QPushButton, QHBoxLayout, QScrollArea, QWidget,
    QTextBrowser, QLineEdit, QSplitter, QMessageBox, QFormLayout,
    QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor

from .model_widget import ModelWidget
from llm.factory import PROVIDER_PRESETS


API_BASE = "http://127.0.0.1:5000/api"


def api_post(path, data):
    url = f"{API_BASE}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_get(path):
    url = f"{API_BASE}{path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ChatSignals(QObject):
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)


class ChatDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("桌面宠物 - 对话")
        self.setFixedSize(420, 480)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.signals = ChatSignals()
        self.signals.response_ready.connect(self.on_response)
        self.signals.error_occurred.connect(self.on_error)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.chat_history = QTextBrowser()
        self.chat_history.setOpenExternalLinks(False)
        self.chat_history.setStyleSheet("""
            QTextBrowser {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }
        """)
        layout.addWidget(self.chat_history)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息，按 Enter 发送...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #7c3aed;
            }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field)

        send_btn = QPushButton("发送")
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
            QPushButton:pressed {
                background-color: #5b21b6;
            }
        """)
        send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout)

        self.append_system_message("欢迎与桌面宠物对话！输入消息开始聊天。")

    def send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self.input_field.setEnabled(False)
        self.append_user_message(text)

        def do_request():
            try:
                data = api_post("/character/chat", {"message": text})
                self.signals.response_ready.emit(data.get("response", ""))
            except Exception as e:
                self.signals.error_occurred.emit(str(e))

        threading.Thread(target=do_request, daemon=True).start()

    def on_response(self, text):
        self.append_assistant_message(text)
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def on_error(self, error_msg):
        self.append_system_message(f"⚠ 请求失败: {error_msg}")
        self.input_field.setEnabled(True)
        self.input_field.setFocus()

    def append_user_message(self, text):
        self.chat_history.append(
            f'<div style="margin:6px 0;"><b style="color:#7c3aed;">🧑 你</b><br>'
            f'<span style="color:#333;">{self._escape(text)}</span></div>'
        )

    def append_assistant_message(self, text):
        self.chat_history.append(
            f'<div style="margin:6px 0;"><b style="color:#059669;">🎀 宠物</b><br>'
            f'<span style="color:#333;">{self._escape(text)}</span></div>'
        )

    def append_system_message(self, text):
        self.chat_history.append(
            f'<div style="margin:6px 0; color:#888; font-style:italic;">{self._escape(text)}</div>'
        )

    def _escape(self, text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


class SettingsSignals(QObject):
    config_saved = pyqtSignal(str)
    config_error = pyqtSignal(str)


class SettingsDialog(QDialog):
    """设置对话框，支持每个提供商独立配置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("桌面宠物 - 设置")
        self.setFixedSize(420, 520)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.providers_data = {}
        self.current_provider_models = []
        self._current_provider_key = ""  # 当前选中的提供商 key
        self._signals = SettingsSignals()
        self._signals.config_saved.connect(self._on_config_saved)
        self._signals.config_error.connect(self._on_config_error)
        self._loading = False  # 防止循环触发
        self.init_ui()
        self.init_default_providers()
        self.load_current_provider()

    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        size_group = QGroupBox("宠物大小")
        size_layout = QVBoxLayout(size_group)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(50, 200)
        self.size_slider.setValue(100)
        self.size_slider.valueChanged.connect(self.on_size_changed)
        self.size_label = QLabel("100%")
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("50%"))
        size_row.addWidget(self.size_slider)
        size_row.addWidget(QLabel("200%"))
        size_layout.addLayout(size_row)
        size_layout.addWidget(self.size_label, 0, Qt.AlignCenter)
        layout.addWidget(size_group)

        position_group = QGroupBox("窗口位置")
        position_layout = QVBoxLayout(position_group)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("30%"))
        op_row.addWidget(self.opacity_slider)
        op_row.addWidget(QLabel("100%"))
        position_layout.addLayout(op_row)
        layout.addWidget(position_group)

        behavior_group = QGroupBox("行为设置")
        behavior_layout = QVBoxLayout(behavior_group)
        self.always_top_combo = QComboBox()
        self.always_top_combo.addItems(["始终置顶", "正常显示"])
        self.always_top_combo.setCurrentIndex(0)
        behavior_layout.addWidget(QLabel("窗口层级:"))
        behavior_layout.addWidget(self.always_top_combo)
        layout.addWidget(behavior_group)

        api_group = QGroupBox("API 配置")
        api_layout = QFormLayout(api_group)
        api_layout.setSpacing(8)

        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(200)
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        api_layout.addRow("提供商:", self.provider_combo)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(200)
        api_layout.addRow("模型:", self.model_combo)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("输入 API Key")
        api_layout.addRow("API Key:", self.api_key_input)

        self.api_base_input = QLineEdit()
        self.api_base_input.setPlaceholderText("默认自动填充")
        api_layout.addRow("API 地址:", self.api_base_input)

        temp_row = QHBoxLayout()
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(0, 100)
        self.temp_slider.setValue(70)
        self.temp_slider.valueChanged.connect(self.on_temp_changed)
        self.temp_label = QLabel("0.7")
        temp_row.addWidget(self.temp_slider)
        temp_row.addWidget(self.temp_label)
        api_layout.addRow("Temperature:", temp_row)

        self.max_tokens_input = QLineEdit("2000")
        self.max_tokens_input.setPlaceholderText("最大输出 token 数")
        api_layout.addRow("Max Tokens:", self.max_tokens_input)

        save_btn = QPushButton("保存 API 配置")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
        """)
        save_btn.clicked.connect(self.save_llm_config)
        api_layout.addRow(save_btn)

        self.api_status_label = QLabel("")
        self.api_status_label.setStyleSheet("color: #888; font-size: 11px;")
        api_layout.addRow(self.api_status_label)

        layout.addWidget(api_group)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def init_default_providers(self):
        """从 LLM 工厂的 PROVIDER_PRESETS 动态加载提供商列表"""
        default_providers = []
        for key, preset in PROVIDER_PRESETS.items():
            default_providers.append({
                "key": key,
                "name": preset["name"],
                "models": preset["models"],
                "default_model": preset["default_model"],
            })
        self.providers_data = {p["key"]: p for p in default_providers}
        self.provider_combo.clear()
        self.provider_combo.addItems([p["name"] for p in default_providers])

    def load_current_provider(self):
        """加载当前激活的提供商配置"""
        try:
            # 从后端获取当前配置
            data = api_get("/config/llm")
            provider_key = data.get("provider", "deepseek")
            self._current_provider_key = provider_key

            # 设置提供商下拉框
            self._loading = True
            for i, (key, info) in enumerate(self.providers_data.items()):
                if key == provider_key:
                    self.provider_combo.setCurrentIndex(i)
                    break

            # 更新模型列表
            preset = self.providers_data.get(provider_key, {})
            self.model_combo.clear()
            self.model_combo.addItems(preset.get("models", []))

            # 填充表单
            self._fill_form(data)
            self._loading = False
        except Exception as e:
            self._loading = False
            print(f"加载配置失败: {e}")

    def _fill_form(self, config):
        """用配置数据填充表单"""
        # API Key
        api_key = config.get("api_key", "")
        self.api_key_input.setText(api_key if api_key != "***" else "")

        # API Base
        api_base = config.get("api_base", "")
        self.api_base_input.setText(api_base)

        # Temperature
        temp = config.get("temperature", 0.7)
        self.temp_slider.setValue(int(temp * 100))

        # Max Tokens
        max_tokens = config.get("max_tokens", 2000)
        self.max_tokens_input.setText(str(max_tokens))

        # Model
        model = config.get("model", "")
        if model:
            idx = self.model_combo.findText(model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            else:
                self.model_combo.setCurrentText(model)

    def on_provider_changed(self, index):
        """切换提供商时自动保存当前配置并加载新配置"""
        if self._loading:
            return

        name = self.provider_combo.currentText()
        new_provider_key = None
        for key, info in self.providers_data.items():
            if info["name"] == name:
                new_provider_key = key
                break

        if not new_provider_key or new_provider_key == self._current_provider_key:
            return

        # 保存当前提供商的配置
        if self._current_provider_key:
            self._save_current_provider_to_file()

        # 更新当前提供商
        self._current_provider_key = new_provider_key

        # 更新模型列表
        self._loading = True
        preset = self.providers_data.get(new_provider_key, {})
        self.model_combo.clear()
        self.model_combo.addItems(preset.get("models", []))

        # 从后端加载新提供商的配置
        try:
            data = api_get(f"/config/llm/provider?provider={new_provider_key}")
            self._fill_form(data)
        except Exception:
            # 如果加载失败，使用默认值
            self.api_key_input.clear()
            self.api_base_input.setText(preset.get("api_base", ""))
            self.temp_slider.setValue(70)
            self.max_tokens_input.setText("2000")
            default_model = preset.get("default_model", "")
            if default_model:
                idx = self.model_combo.findText(default_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)

        self._loading = False

    def _save_current_provider_to_file(self):
        """保存当前提供商配置到文件（不重新初始化 LLM）"""
        if not self._current_provider_key:
            return

        data = {
            "provider": self._current_provider_key,
            "model": self.model_combo.currentText().strip(),
            "api_key": self.api_key_input.text().strip(),
            "api_base": self.api_base_input.text().strip(),
            "temperature": self.temp_slider.value() / 100.0,
            "max_tokens": int(self.max_tokens_input.text().strip() or "2000"),
        }

        try:
            api_post("/config/llm", data)
        except Exception:
            pass

    def save_llm_config(self):
        """保存当前配置并应用"""
        if not self._current_provider_key:
            return

        data = {
            "provider": self._current_provider_key,
            "model": self.model_combo.currentText().strip(),
            "api_key": self.api_key_input.text().strip(),
            "api_base": self.api_base_input.text().strip(),
            "temperature": self.temp_slider.value() / 100.0,
            "max_tokens": int(self.max_tokens_input.text().strip() or "2000"),
        }

        def do_request():
            try:
                api_post("/config/llm", data)
                self._signals.config_saved.emit("配置已保存")
            except Exception as e:
                self._signals.config_error.emit(str(e))

        threading.Thread(target=do_request, daemon=True).start()

    def _on_config_saved(self, text):
        self.api_status_label.setText(text)
        self.api_status_label.setStyleSheet("color: #059669; font-size: 11px;")

    def _on_config_error(self, text):
        self.api_status_label.setText(f"保存失败: {text}")
        self.api_status_label.setStyleSheet("color: #dc2626; font-size: 11px;")

    def on_size_changed(self, value):
        self.size_label.setText(f"{value}%")

    def on_opacity_changed(self, value):
        pass

    def on_temp_changed(self, value):
        self.temp_label.setText(f"{value / 100.0:.1f}")


class PetWindow(QMainWindow):
    character_switch_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.drag_position = QPoint()
        self.scale_factor = 1.0
        self.init_window()
        self.init_pet_display()
        self.init_tray()
        self.character_switch_requested.connect(self.update_pet_display)
        self.show()

    def init_window(self):
        self.setWindowTitle("桌面宠物")
        self.setFixedSize(400, 500)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)

        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width() - self.width() - 50,
            screen.height() - self.height() - 80
        )

    def init_pet_display(self):
        self.pet_display = ModelWidget(self)
        self.pet_display.setGeometry(40, 40, 320, 380)
        self.pet_display.setObjectName("petDisplay")
        self.pet_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pet_display.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.pet_display.mapToGlobal(pos))
        )
        self.pet_display.model_ready.connect(self._on_model_ready)

        status = QLabel("右键点击打开菜单 | 左键拖拽移动", self)
        status.setAlignment(Qt.AlignCenter)
        status.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 11px;")
        status.setGeometry(40, 430, 320, 25)
        status.setContextMenuPolicy(Qt.CustomContextMenu)
        status.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(status.mapToGlobal(pos))
        )

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_pixmap = QPixmap(32, 32)
        icon_pixmap.fill(Qt.transparent)
        painter = QPainter(icon_pixmap)
        painter.setBrush(QColor(200, 100, 255))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        self.tray_icon.setIcon(QIcon(icon_pixmap))
        self.tray_icon.setToolTip("桌面宠物")

        tray_menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_and_raise)
        hide_action = QAction("隐藏窗口", self)
        hide_action.triggered.connect(self.hide)
        chat_action = QAction("对话", self)
        chat_action.triggered.connect(self.open_chat)
        settings_action = QAction("设置", self)
        settings_action.triggered.connect(self.open_settings)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addAction(hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(chat_action)
        tray_menu.addAction(settings_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def contextMenuEvent(self, event):
        self.show_context_menu(event.globalPos())

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #f0e6ff;
                color: #7c3aed;
            }
        """)

        chat_action = QAction("💬  对话", self)
        chat_action.triggered.connect(self.open_chat)
        character_action = QAction("👤  选择角色", self)
        character_action.triggered.connect(self.open_character_selector)
        settings_action = QAction("⚙  设置", self)
        settings_action.triggered.connect(self.open_settings)
        quit_action = QAction("✕  退出", self)
        quit_action.triggered.connect(self.quit_app)

        menu.addAction(chat_action)
        menu.addSeparator()
        menu.addAction(character_action)
        menu.addSeparator()
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        menu.exec_(pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_settings()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_and_raise()

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.size_slider.valueChanged.connect(self.on_scale_changed)
        dialog.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        dialog.always_top_combo.currentIndexChanged.connect(self.on_topmost_changed)
        dialog.exec_()

    def open_chat(self):
        dialog = ChatDialog(self)
        dialog.exec_()

    def open_character_selector(self):
        """打开角色选择对话框"""
        if not hasattr(self, 'character_manager') or not self.character_manager:
            QMessageBox.warning(self, "提示", "角色管理器未初始化")
            return

        dialog = CharacterSelectorDialog(self.character_manager, self)
        dialog.character_selected.connect(self._on_character_selected)
        dialog.exec_()

    def _on_character_selected(self, character_id):
        """角色被选择后的回调"""
        try:
            self.character_manager.switch_character(character_id)
            self.update_pet_display()
            print(f"[PetWindow] Switched to character: {character_id}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"切换角色失败: {e}")

    def on_scale_changed(self, value):
        factor = value / 100.0
        self.scale_factor = factor
        base_w, base_h = 400, 500
        new_w = int(base_w * factor)
        new_h = int(base_h * factor)
        self.setFixedSize(new_w, new_h)
        if hasattr(self, 'pet_display'):
            self.pet_display.set_scale(factor)
            self.pet_display.setGeometry(
                int(40 * factor), int(40 * factor),
                int(320 * factor), int(380 * factor)
            )

    def on_opacity_changed(self, value):
        self.setWindowOpacity(value / 100.0)

    def on_topmost_changed(self, index):
        if index == 0:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _on_model_ready(self, model_name):
        self.setWindowTitle(f"桌面宠物 - {model_name}")

    def set_character_manager(self, character_manager):
        self.character_manager = character_manager
        self.update_pet_display()

    def update_pet_display(self):
        if hasattr(self, 'character_manager') and self.character_manager:
            char_id = self.character_manager.current_character_id
            print(f"[PetWindow] update_pet_display: char_id={char_id}", flush=True)
            if char_id:
                try:
                    profile = self.character_manager.load_character_profile(char_id)
                    print(f"[PetWindow] profile loaded: {profile.get('name', '?') if profile else 'None'}", flush=True)
                    self.pet_display.load_character(char_id, profile)
                except Exception as e:
                    print(f"[PetWindow] update_pet_display error: {e}", flush=True)

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()


class CharacterSelectorDialog(QDialog):
    """角色选择对话框"""

    character_selected = pyqtSignal(str)  # 选中的角色 ID

    def __init__(self, character_manager, parent=None):
        super().__init__(parent)
        self.character_manager = character_manager
        self.setWindowTitle("选择角色")
        self.setFixedSize(300, 400)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.init_ui()
        self.load_characters()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("选择要切换的角色：")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        layout.addWidget(title)

        # 角色列表
        self.character_list = QListWidget()
        self.character_list.setStyleSheet("""
            QListWidget {
                background-color: #fafafa;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #7c3aed;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #f0e6ff;
            }
        """)
        self.character_list.itemDoubleClicked.connect(self.on_character_double_clicked)
        layout.addWidget(self.character_list)

        # 按钮区域
        btn_layout = QHBoxLayout()

        select_btn = QPushButton("选择")
        select_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        select_btn.clicked.connect(self.on_select_clicked)
        self.select_btn = select_btn

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #666;
                border: 1px solid #ddd;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def load_characters(self):
        """加载角色列表"""
        try:
            characters = self.character_manager.get_available_characters()
            current_id = self.character_manager.current_character_id

            for char_id in characters:
                try:
                    profile = self.character_manager.load_character_profile(char_id)
                    name = profile.get("name", char_id) if profile else char_id
                    description = profile.get("description", "") if profile else ""
                except Exception:
                    name = char_id
                    description = ""

                # 创建列表项
                item = QListWidgetItem()
                item.setData(Qt.UserRole, char_id)  # 存储角色 ID

                # 显示文本
                display_text = name
                if char_id == current_id:
                    display_text += " (当前)"
                if description:
                    display_text += f"\n{description[:50]}..."

                item.setText(display_text)
                self.character_list.addItem(item)

                # 高亮当前角色
                if char_id == current_id:
                    item.setSelected(True)

        except Exception as e:
            print(f"[CharacterSelector] Error loading characters: {e}")

    def on_select_clicked(self):
        """选择按钮点击"""
        current_item = self.character_list.currentItem()
        if current_item:
            character_id = current_item.data(Qt.UserRole)
            self.character_selected.emit(character_id)
            self.accept()

    def on_character_double_clicked(self, item):
        """双击角色项"""
        character_id = item.data(Qt.UserRole)
        self.character_selected.emit(character_id)
        self.accept()
