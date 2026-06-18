"""Third-party + stdlib imports, the lxml/ElementTree shim and the shared logger.
Every other module does ``from .qt import *`` to get these."""

import sys, re, json, os, zipfile, struct, urllib.parse, tempfile, shutil, copy, math, random, functools, collections as _collections, threading as _threading, datetime as _dt, time as _time, stat as _stat, subprocess as _subprocess


_shutil = shutil


import ctypes as _ctypes


try:
    import lxml.etree as ET
    def _et_fromstring(xml_bytes: bytes):
        # .siq-пакеты часто скачивают из интернета, т.е. это недоверенный ввод.
        # Жёстко отключаем разбор сущностей и загрузку DTD, чтобы вредоносный
        # content.xml не смог прочитать локальные файлы через внешние
        # SYSTEM-сущности (XXE) или устроить «лавину сущностей» (billion laughs).
        # Парсер создаём на каждый вызов — он не потокобезопасен для повторного
        # использования из разных потоков. Предопределённые сущности XML
        # (&amp; &lt; …) на это не влияют и разбираются как обычно.
        parser = ET.XMLParser(resolve_entities=False, no_network=True,
                              load_dtd=False, huge_tree=False)
        return ET.fromstring(xml_bytes, parser=parser)
    def _et_tostring(root, encoding='unicode') -> str:
        return ET.tostring(root, encoding='unicode')
    _ET_IS_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    def _et_fromstring(xml_bytes: bytes): return ET.fromstring(xml_bytes.decode('utf-8-sig'))
    def _et_tostring(root, encoding='unicode') -> str:
        return ET.tostring(root, encoding='unicode')
    _ET_IS_LXML = False


from pathlib import Path


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QScrollArea, QFrame, QFileDialog,
    QStackedWidget, QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QSizePolicy, QGraphicsOpacityEffect, QMenu, QInputDialog,
    QTabWidget, QDialog, QComboBox, QSplitter, QSlider,
    QCheckBox, QLineEdit, QGroupBox,
)


from PyQt6.QtCore import (
    Qt, QSize, pyqtSignal, QTimer, QMimeData, QByteArray,
    QPropertyAnimation, QEasingCurve, QUrl, QRectF, QObject, QEvent, QRect,
)


from PyQt6.QtGui import (
    QColor, QPalette, QFont,
    QPainter, QBrush, QLinearGradient, QPainterPath, QDrag,
    QPixmap, QImage, QImageReader, QTextOption,
)


from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaMetaData


from PyQt6.QtMultimediaWidgets import QVideoWidget


import logging as _log


_log.basicConfig(level=_log.WARNING,
                 format='%(asctime)s [%(levelname)s] %(message)s',
                 datefmt='%H:%M:%S')


_logger = _log.getLogger('siquester')


# Видео-плеер вкладки портирован на QtMultimedia (QMediaPlayer + QVideoWidget),
# поэтому нативная зависимость mpv / libmpv-2.dll больше не требуется.


import queue as _queue

__all__ = [
    'ET',
    'Path',
    'QAbstractItemView',
    'QApplication',
    'QAudioOutput',
    'QBrush',
    'QByteArray',
    'QCheckBox',
    'QColor',
    'QComboBox',
    'QDialog',
    'QDrag',
    'QEasingCurve',
    'QEvent',
    'QFileDialog',
    'QFont',
    'QFrame',
    'QGraphicsOpacityEffect',
    'QGroupBox',
    'QHBoxLayout',
    'QImage',
    'QImageReader',
    'QInputDialog',
    'QLabel',
    'QLineEdit',
    'QLinearGradient',
    'QListWidget',
    'QListWidgetItem',
    'QMainWindow',
    'QMediaMetaData',
    'QMediaPlayer',
    'QMenu',
    'QMessageBox',
    'QMimeData',
    'QObject',
    'QPainter',
    'QPainterPath',
    'QPalette',
    'QPixmap',
    'QPropertyAnimation',
    'QPushButton',
    'QRect',
    'QRectF',
    'QScrollArea',
    'QSize',
    'QSizePolicy',
    'QSlider',
    'QSplitter',
    'QStackedWidget',
    'QTabWidget',
    'QTextEdit',
    'QTextOption',
    'QTimer',
    'QUrl',
    'QVBoxLayout',
    'QVideoWidget',
    'QWidget',
    'Qt',
    '_ET_IS_LXML',
    '_collections',
    '_ctypes',
    '_dt',
    '_et_fromstring',
    '_et_tostring',
    '_log',
    '_logger',
    '_queue',
    '_shutil',
    '_stat',
    '_subprocess',
    '_threading',
    '_time',
    'copy',
    'functools',
    'json',
    'math',
    'os',
    'pyqtSignal',
    'random',
    're',
    'shutil',
    'struct',
    'sys',
    'tempfile',
    'urllib',
    'zipfile',
]
