"""
渲染器抽象基类
定义三种渲染方式（Live2D / VRM / Sprite）的统一接口
"""

from abc import ABC, abstractmethod
from PyQt5.QtCore import QObject, pyqtSignal


class BaseRenderer(QObject):
    """渲染器抽象基类"""

    # 统一信号
    model_ready = pyqtSignal(str)       # 模型就绪 (character_id)
    motion_played = pyqtSignal(str)     # 动作播放完成 (motion_name)
    fallback_visible = pyqtSignal(bool) # 降级界面可见

    @abstractmethod
    def load(self, character_id, profile, characters_dir):
        """加载角色模型，返回 True/False"""

    @abstractmethod
    def play_motion(self, name, group=""):
        """播放动作"""

    @abstractmethod
    def set_expression(self, name):
        """设置表情"""

    @abstractmethod
    def set_random_motion(self):
        """播放随机动作"""

    @abstractmethod
    def mouse_follow(self, x, y):
        """鼠标跟随"""

    @abstractmethod
    def start_idle_timer(self, interval_ms=5000):
        """启动空闲定时器"""

    @abstractmethod
    def stop_idle_timer(self):
        """停止空闲定时器"""

    @abstractmethod
    def set_scale(self, factor):
        """缩放"""

    @abstractmethod
    def get_widget(self):
        """返回用于显示的 QWidget"""

    @abstractmethod
    def get_cache_stats(self):
        """获取缓存统计信息"""

    @abstractmethod
    def cleanup(self):
        """清理资源"""

    def load_animations(self, anim_config, base_url):
        """加载动画文件（非抽象，默认空实现）"""
        pass
