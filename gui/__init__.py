"""
图形界面模块
提供 PyQt5 桌面窗口与 3D 模型渲染组件（支持 Live2D 和 VRM）
"""

from .pet_window import PetWindow
from .model_widget import ModelWidget
from .live2d_bridge import Live2DBridge

# 向后兼容
Live2DWidget = ModelWidget

__all__ = ['PetWindow', 'ModelWidget', 'Live2DWidget', 'Live2DBridge']
