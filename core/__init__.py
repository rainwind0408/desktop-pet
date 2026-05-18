"""
核心业务逻辑模块
包含角色管理和记忆系统
"""

from .character_manager import CharacterManager
from .memory_system import MemorySystem
from .music_analyzer import MusicAnalyzer

__all__ = ['CharacterManager', 'MemorySystem', 'MusicAnalyzer']
