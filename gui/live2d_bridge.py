"""
Python ↔ JavaScript 双向通信桥接模块
用于 PyQt5 QWebEngineView 与嵌入的 Live2D 网页之间传递消息
"""

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel


class Live2DBridge(QObject):
    motion_started = pyqtSignal(str, str)
    motion_finished = pyqtSignal(str, str)
    model_loaded = pyqtSignal(str)
    model_error = pyqtSignal(str)
    tap_received = pyqtSignal(float, float)
    drag_started = pyqtSignal(float, float)
    drag_moved = pyqtSignal(float, float)
    drag_ended = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callbacks = {}

    def register_callback(self, name, callback):
        self._callbacks[name] = callback

    @pyqtSlot(str, str)
    def on_motion_started(self, group, name):
        self.motion_started.emit(group, name)

    @pyqtSlot(str, str)
    def on_motion_finished(self, group, name):
        self.motion_finished.emit(group, name)

    @pyqtSlot(str)
    def on_model_loaded(self, model_name):
        self.model_loaded.emit(model_name)

    @pyqtSlot(str)
    def on_model_error(self, error_msg):
        self.model_error.emit(error_msg)

    @pyqtSlot(float, float)
    def on_tap(self, x, y):
        self.tap_received.emit(x, y)

    @pyqtSlot(float, float)
    def on_drag_started(self, x, y):
        self.drag_started.emit(x, y)

    @pyqtSlot(float, float)
    def on_drag_moved(self, x, y):
        self.drag_moved.emit(x, y)

    @pyqtSlot(float, float)
    def on_drag_ended(self, x, y):
        self.drag_ended.emit(x, y)

    def create_channel(self, view):
        channel = QWebChannel(view.page())
        channel.registerObject("live2dBridge", self)
        view.page().setWebChannel(channel)