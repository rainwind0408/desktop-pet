"""
渲染器模块
提供三种独立的渲染器：WebEngineRenderer (Live2D/VRM)、SpriteRenderer (Spritesheet 2D)
"""

from .base_renderer import BaseRenderer
from .web_engine_renderer import WebEngineRenderer
from .sprite_renderer import SpriteRenderer

__all__ = [
    'BaseRenderer',
    'WebEngineRenderer',
    'SpriteRenderer',
]
