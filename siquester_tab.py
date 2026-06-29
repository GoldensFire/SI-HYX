# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# siquester_tab.py — обёртка, встраивающая SiQuester (просмотр .siq + анализ
# статистики SIGame) как вкладку SI-HYX. Видеоплеер портирован на QtMultimedia
# (QMediaPlayer + QVideoWidget) — нативная зависимость mpv/libmpv-2.dll убрана.
import os
import traceback

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QApplication
from PyQt6.QtCore import Qt

# SiQuester зовёт ffmpeg как "ffmpeg" из PATH (замер LUFS/инфо о медиа). Кладём
# каталоги bin SI-HYX в PATH, чтобы нашёлся bundled ffmpeg.exe (и в .exe-сборке).
try:
    from config import _bin_dirs
    _extra = _bin_dirs()
    if _extra:
        os.environ["PATH"] = os.pathsep.join(_extra) + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass

# Пакет siquester тяжёлый (и тянет QtMultimedia) — импортируем при загрузке этого
# модуля, который сам подгружается лениво (только когда вкладка включена).
_SIQ_IMPORT_ERROR = ""
try:
    from siquester.main_window import MainWindow as _SiqMainWindow
    from siquester.constants import STYLESHEET as _SIQ_STYLESHEET
    _HAS_SIQ = True
except Exception as _e:
    _HAS_SIQ = False
    _SIQ_IMPORT_ERROR = "".join(traceback.format_exception_only(type(_e), _e)).strip()


class SiQuesterTab(QWidget):
    """Экспериментальная вкладка: встраивает siquester.MainWindow (QMainWindow) как
    дочерний виджет. Включается/выключается в Настройках (по умолчанию выключена).

    • Своя тема SiQuester (GitHub-dark) применяется поверх глобального стиля SI-HYX,
      чтобы интерфейс выглядел как в оригинале.
    • Глобальные хоткеи SiQuester (Ctrl+S/F, WASD, клик-вне-панели) активны только
      пока вкладка видима — фильтр событий ставится/снимается по show/hide.
    """

    def __init__(self, main_window=None):
        super().__init__()
        self.main = main_window
        self.inner = None
        self._filter_installed = False
        self._built = False

        # Непрозрачный фон вкладки в тон теме SiQuester (QMainWindow=#181825).
        self.setObjectName("siquesterTabRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#siquesterTabRoot { background:#181825; }")
        # ГЛАВНОЕ против протекания соседней вкладки: внутри SiQuester живёт нативный
        # QVideoWidget (QtMultimedia). Из-за него ТОЛЬКО видео получает свою native-
        # поверхность, а остальная вкладка делит общий бэкстор QStackedWidget с
        # соседями — и в непокрашенные участки (угол сайдбара у «Все») просачивались
        # пиксели ShikimoriHYX (карточки аниме). Даём этой вкладке СОБСТВЕННУЮ
        # native-поверхность (WA_NativeWindow) + обещание непрозрачности — тогда
        # соседний лист рисуется в свой буфер и физически не может сюда попасть.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        # Содержимое строится ЛЕНИВО — при первом показе вкладки (см. _ensure_built и
        # showEvent), а не на старте приложения. Так старт не тормозит и не мелькает.
        # Само мелькание окна устранено в _ensure_built (см. setParent(..., Qt.Widget)):
        # siquester.MainWindow — это QMainWindow, по умолчанию ОТДЕЛЬНОЕ окно, и его
        # show() выкидывал окно поверх экрана; теперь он встраивается как дочерний
        # виджет и наружу ничего не показывается.

    def _ensure_built(self):
        """Строит содержимое вкладки ровно один раз — при первом её показе."""
        if self._built:
            return
        self._built = True

        if not _HAS_SIQ:
            self._build_unavailable(self._lay, _SIQ_IMPORT_ERROR)
            return
        try:
            self.inner = _SiqMainWindow()
        except Exception as e:
            traceback.print_exc()
            self._build_unavailable(self._lay, "".join(
                traceback.format_exception_only(type(e), e)).strip())
            return

        # Не навязываем окну SI-HYX крупный минимальный размер встроенного окна.
        try:
            self.inner.setMinimumSize(0, 0)
        except Exception:
            pass
        # Тема SiQuester поверх стиля SI-HYX (каскад: ближний стиль виджета важнее).
        try:
            self.inner.setStyleSheet(_SIQ_STYLESHEET)
        except Exception:
            pass
        # «↺ Перезапуск» перезапускал бы всё приложение SI-HYX — прячем в составе.
        for b in self.inner.findChildren(QPushButton):
            if b.objectName() == "btn_restart":
                b.hide()

        # ГЛАВНОЕ против мелькания: QMainWindow по умолчанию — ОТДЕЛЬНОЕ top-level
        # окно (флаг Qt.Window). Просто addWidget этот флаг надёжно НЕ снимает,
        # поэтому self.inner.show() на миг «выкидывал» окно наружу как самостоятельное
        # — это и есть мелькающее окошко при запуске/открытии вкладки. Двухаргументный
        # setParent выставляет и родителя, и флаги: Qt.Widget = обычный ДОЧЕРНИЙ
        # виджет (не окно). После этого окно живёт строго внутри вкладки, и show()
        # уже ничего не показывает поверх экрана.
        self.inner.setParent(self, Qt.WindowType.Widget)
        self._lay.addWidget(self.inner)
        self.inner.show()

    def _build_unavailable(self, lay, detail=""):
        text = ("Не удалось загрузить экспериментальную вкладку «SiQuester».\n\n"
                "Проверьте, что пакет «siquester» на месте рядом с программой.")
        if detail:
            text += f"\n\n{detail}"
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()

    def _hide_floating_panels(self):
        """Прячет плавающие панели SiQuester (поиск по пакам / медиа).

        Это setParent(inner)-оверлеи поверх сайдбара (move(0,46)). Если оставить
        их открытыми и переключить вкладку SI-HYX, при возврате они «висят»
        обрывком над сайдбаром («Все») — наложение чужого интерфейса. Закрываем
        их при уходе с вкладки и при входе, плюс форсируем перерисовку, чтобы не
        оставалось артефакта недорисовки от встроенного QMainWindow."""
        if self.inner is None:
            return
        for attr in ("_search_panel", "_media_search_panel"):
            p = getattr(self.inner, attr, None)
            if p is not None:
                try:
                    p.hide()
                except Exception:
                    pass
        try:
            self.inner.update()
        except Exception:
            pass

    # ── Хоткеи SiQuester активны только когда вкладка показана ──────────────
    def showEvent(self, ev):
        super().showEvent(ev)
        # Первый показ вкладки — строим содержимое (идемпотентно). К этому моменту
        # вкладка уже встроена в QTabWidget, поэтому окно встраивается как дочерний
        # виджет и не мелькает (см. _ensure_built).
        self._ensure_built()
        # Не показываем «висящую» с прошлого раза панель поиска поверх сайдбара.
        self._hide_floating_panels()
        if self.inner is not None and not self._filter_installed:
            try:
                QApplication.instance().installEventFilter(self.inner)
                self._filter_installed = True
            except Exception:
                pass

    def hideEvent(self, ev):
        super().hideEvent(ev)
        # Уходя с вкладки — закрываем плавающие панели, чтобы при возврате они не
        # оставались обрывком над сайдбаром.
        self._hide_floating_panels()
        self._remove_filter()

    def _remove_filter(self):
        if self.inner is not None and self._filter_installed:
            try:
                QApplication.instance().removeEventFilter(self.inner)
            except Exception:
                pass
            self._filter_installed = False

    def cleanup(self):
        """Останавливает медиаплееры SiQuester и снимает фильтр — зовётся при
        закрытии SI-HYX или при выключении вкладки в Настройках."""
        self._remove_filter()
        if self.inner is None:
            return
        try:
            for ds in getattr(self.inner, "datasets", []):
                w = ds.get("widget")
                if not w:
                    continue
                for mw in list(getattr(w, "_media_widgets", [])):
                    try:
                        mw.stop()
                    except Exception:
                        pass
                w._media_widgets = []
        except Exception:
            pass
