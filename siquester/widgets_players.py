"""Audio / video player widgets built on QtMultimedia (QMediaPlayer)."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _threading, math, os, pyqtSignal, QApplication, QAudioOutput, QBrush, QColor,
    QHBoxLayout, QLabel, QMediaMetaData, QMediaPlayer, QMenu, QPainter, QPainterPath,
    QRectF, QSize, QSlider, Qt, QTimer, QUrl, QVBoxLayout, QVideoWidget, QWidget
)
from .constants import _AlignVC, _Expand, _Pref, _SS_LABEL_DIM
from .media import (
    _extract_waveform_bars, _get_media_info, _get_ui_bridge, _m4a_audio_bitrate_kbps,
    _measure_lufs, _mp4_video_size
)
from .util import _lbl, fmt_dur

from si_hyx_parts.siquester.widgets_players.seek_slider import SeekSlider


SEEK_SLIDER_STYLE = """
    QSlider { min-height: 18px; }
    QSlider::groove:horizontal { background: #45475a; height: 4px; border-radius: 2px; }
    QSlider::sub-page:horizontal {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #cba6f7,stop:1 #89b4fa);
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #cdd6f4; border: 2px solid #89b4fa;
        width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    }
    QSlider::handle:horizontal:hover { background: #89b4fa; }
"""

from si_hyx_parts.siquester.widgets_players.waveform_widget import WaveformWidget, _AspectWidget

from si_hyx_parts.siquester.widgets_players.video_player_widget import VideoPlayerWidget


# Историческое имя класса (вкладка вопросов ссылается на него) — оставляем как
# алиас, чтобы не трогать call-site после порта с mpv на QtMultimedia.
MpvVideoPlayerWidget = VideoPlayerWidget

from si_hyx_parts.siquester.widgets_players.circle_play_button import (
    CirclePlayButton,
    AudioPlayerWidget,
)

__all__ = [
    'AudioPlayerWidget',
    'CirclePlayButton',
    'MpvVideoPlayerWidget',
    'SEEK_SLIDER_STYLE',
    'SeekSlider',
    'VideoPlayerWidget',
    'WaveformWidget',
    '_AspectWidget',
]
