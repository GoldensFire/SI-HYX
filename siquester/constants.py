"""UI constants: colour palette, Qt enum aliases, stylesheet fragments, MIME types, sort flags."""

from .qt import *

_AlignC   = Qt.AlignmentFlag.AlignCenter


_AlignL   = Qt.AlignmentFlag.AlignLeft


_AlignR   = Qt.AlignmentFlag.AlignRight


_AlignVC  = Qt.AlignmentFlag.AlignVCenter


_AlignTop = Qt.AlignmentFlag.AlignTop


_Expand   = QSizePolicy.Policy.Expanding


_Fixed    = QSizePolicy.Policy.Fixed


_Pref     = QSizePolicy.Policy.Preferred


_Minimum  = QSizePolicy.Policy.Minimum


_MEDIA_EXTS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif',
    '.mp3', '.ogg', '.wav', '.aac', '.flac', '.m4a',
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm',
})


_IMG_EXTS   = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.avif'})


_AUDIO_EXTS = frozenset({'.mp3', '.ogg', '.wav', '.aac', '.flac', '.m4a'})


_VIDEO_EXTS = frozenset({'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm'})


_DH_SS_HIDDEN = ("QPushButton{background:transparent;color:transparent;border:none;"
                 "font-size:11px;padding:0;}")


_DH_SS_SHOWN  = ("QPushButton{background:transparent;color:#585b70;border:none;"
                 "font-size:11px;padding:0;}"
                 "QPushButton:hover{color:#89b4fa;}")


_DEL_SS_HIDDEN = ("QPushButton{background:transparent;color:transparent;"
                  "border:none;border-radius:3px;font-size:10px;padding:0;}")


_DEL_SS_SHOWN  = ("QPushButton{background:rgba(243,139,168,0.15);color:#f38ba8;"
                  "border:1px solid #f38ba8;border-radius:3px;font-size:10px;padding:0;}"
                  "QPushButton:hover{background:rgba(243,139,168,0.4);}")


_SB_OFF = ("QPushButton{background:transparent;color:transparent;"
           "border:none;border-radius:3px;font-size:10px;padding:0;}")


_SB_ON  = ("QPushButton{background:rgba(137,180,250,0.20);color:#89b4fa;"
           "border:1px solid #89b4fa;border-radius:3px;font-size:10px;padding:0;}"
           "QPushButton:hover{background:rgba(137,180,250,0.35);}")


_SB_HOV = ("QPushButton{background:rgba(137,180,250,0.08);color:#585b70;"
           "border:1px solid #45475a;border-radius:3px;font-size:10px;padding:0;}"
           "QPushButton:hover{color:#89b4fa;border-color:#89b4fa;}")


_RB_OFF    = ("QPushButton{background:transparent;color:transparent;"
              "border:none;border-radius:3px;font-size:10px;padding:0;}")


_RB_HOV    = ("QPushButton{background:rgba(137,180,250,0.08);color:#585b70;"
              "border:1px solid #45475a;border-radius:3px;font-size:10px;padding:0;}"
              "QPushButton:hover{color:#89b4fa;border-color:#89b4fa;}")


_RB_ACTIVE = ("QPushButton{background:rgba(137,180,250,0.20);color:#89b4fa;"
              "border:1px solid #89b4fa;border-radius:3px;font-size:10px;padding:0;}"
              "QPushButton:hover{background:rgba(137,180,250,0.35);}")


_TB_OFF = ("QPushButton{background:transparent;color:transparent;"
           "border:none;border-radius:3px;font-size:10px;padding:0 4px;}")


_TB_HOV = ("QPushButton{background:rgba(203,166,247,0.10);color:#585b70;"
           "border:1px solid #45475a;border-radius:3px;font-size:10px;padding:0 4px;}"
           "QPushButton:hover{color:#cba6f7;border-color:#cba6f7;}")


_TB_ON  = ("QPushButton{background:rgba(203,166,247,0.20);color:#cba6f7;"
           "border:1px solid #cba6f7;border-radius:3px;font-size:10px;padding:0 4px;}"
           "QPushButton:hover{background:rgba(203,166,247,0.35);}")


_ITEM_OUTER_SS = ("QFrame{background:transparent;border:none;"
                  "border-radius:6px;}")


_ITEM_INNER_SS = ("QFrame{background:#1e1e2e;color:#cdd6f4;font-size:13px;"
                  "border:1px solid #313244;border-radius:5px;}")


_ITEM_FOCUS_SS = ("QFrame{background:rgba(137,180,250,0.07);"
                  "border-left:3px solid #89b4fa;"
                  "border-radius:5px;color:#cdd6f4;font-size:13px;}")


_ITEM_JOIN_SS  = ("QFrame{background:rgba(137,180,250,0.07);"
                  "border-left:3px solid #89b4fa;"
                  "border-radius:0px 4px 4px 0px;}")


_C_BG       = "#181825"   # main window background


_C_BG2      = "#1e1e2e"   # slightly lighter surface (inputs, cards)


_C_TEXT     = "#cdd6f4"   # primary text


_C_TEXT_DIM = "#a6adc8"   # muted / secondary text


_C_BORDER   = "#45475a"   # default border


_C_ACCENT   = "#89b4fa"   # blue accent / hover


_C_BG       = '#181825'   # main background


_C_BG2      = '#1e1e2e'   # secondary background


_C_BG3      = '#313244'   # tertiary / hover


_C_BG4      = '#313244'   # slightly lighter bg


_C_BORDER   = '#45475a'   # default border


_C_TEXT     = '#cdd6f4'   # primary text


_C_TEXT2    = '#a6adc8'   # muted text


_C_TEXT3    = '#6c7086'   # even more muted


_C_TEXT4    = '#585b70'   # disabled / placeholder


_C_ACCENT   = '#89b4fa'   # primary accent blue


_C_ACCENT2  = '#89b4fa'   # lighter accent


_C_ACCENT3  = '#b4befe'   # lightest accent


_C_GREEN    = '#a6e3a1'   # success green


_C_RED      = '#f38ba8'   # error red


_C_PURPLE   = '#cba6f7'   # purple accent


_SS_BG      = f'background:{_C_BG};'


_SS_BG_NONE = f'border:none; background:{_C_BG};'


_SS_DIVIDER = f'background:{_C_BG3}; max-height:1px;'


_SS_LBL_SM  = f'color:{_C_TEXT2};font-size:11px;'


_SS_LBL_XS  = f'color:{_C_TEXT3};font-size:10px;'


_SS_LBL_MED = f'color:{_C_TEXT};font-size:13px;'


_MIME_BLOCK = 'application/x-siq-block'


_MIME_ANS   = 'application/x-ans-row'


STYLESHEET = """
* { font-family: 'Segoe UI', Arial, sans-serif; }
QMainWindow { background: #181825; }
QListWidget { background:transparent; border:none; outline:none; padding:3px 2px; }
QListWidget::item { background:transparent; border-radius:5px; padding:2px 0; margin:1px 0; }
QListWidget::item:hover    { background:#313244; }
QListWidget::item:selected { background:rgba(137,180,250,0.16); }
QPushButton {
    background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #45475a,stop:1 #313244);
    color:#cdd6f4; border:1px solid #585b70; border-bottom:2px solid #313244;
    border-radius:6px; padding:7px 16px; font-size:13px; font-weight:500;
}
QPushButton:hover { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #585b70,stop:1 #45475a); color:#cdd6f4; border-color:#6c7086; }
QPushButton:pressed { background:#313244; border-color:#89b4fa; border-bottom-width:1px; padding-top:8px; padding-bottom:6px; color:#b4befe; }
QPushButton#btn_analyze { background:#a6e3a1; color:#181825; border:none; font-weight:700; }
QPushButton#btn_analyze:hover { background:#94e2d5; } QPushButton#btn_analyze:pressed { background:#94e2d5; }
QPushButton#btn_paste, QPushButton#btn_paste_main { background:rgba(137,180,250,0.16); color:#89b4fa; border:1px solid #89b4fa99; font-weight:700; padding:9px 22px; border-radius:7px; }
QPushButton#btn_paste:hover, QPushButton#btn_paste_main:hover { background:rgba(137,180,250,0.30); color:#cdd6f4; border-color:#89b4fa; }
QPushButton#btn_update { background:rgba(249,226,175,0.14); color:#f9e2af; border:1px solid #f9e2af99; font-size:12px; font-weight:600; padding:5px 12px; border-radius:5px; }
QPushButton#btn_update:hover { background:rgba(249,226,175,0.26); color:#f9e2af; border-color:#f9e2af; }
QPushButton#btn_del { background:transparent; color:#585b70; border:none; padding:0; font-size:13px; border-radius:4px; font-weight:700; }
QPushButton#btn_del:hover { color:#f38ba8; background:rgba(243,139,168,0.12); }
QPushButton#btn_reset { background:transparent; color:#6c7086; border:1px solid #313244; font-size:12px; padding:5px 12px; }
QPushButton#btn_reset:hover { color:#f38ba8; border-color:rgba(243,139,168,0.6); }
QPushButton#btn_restart { background:rgba(203,166,247,0.14); color:#cba6f7; border:1px solid #cba6f799; font-size:12px; padding:5px 12px; border-radius:5px; }
QPushButton#btn_restart:hover { background:rgba(203,166,247,0.28); color:#cdd6f4; border-color:#cba6f7; }
QPushButton#btn_compare { background:rgba(137,180,250,0.14); color:#89b4fa; border:1px solid #89b4fa77; font-size:12px; padding:5px 12px; border-radius:5px; }
QPushButton#btn_compare:hover { background:rgba(137,180,250,0.28); color:#cdd6f4; }
QPushButton#btn_search { background:rgba(137,180,250,0.14); color:#89b4fa; border:1px solid #89b4fa77; font-size:12px; padding:5px 12px; border-radius:5px; }
QPushButton#btn_search:hover { background:rgba(137,180,250,0.28); color:#cdd6f4; }
QPushButton#btn_media_search { background:rgba(203,166,247,0.14); color:#cba6f7; border:1px solid #cba6f777; font-size:12px; padding:5px 12px; border-radius:5px; }
QPushButton#btn_media_search:hover { background:rgba(203,166,247,0.28); color:#cdd6f4; }
QPushButton#btn_sort { background:transparent; color:#6c7086; border:1px solid #313244; border-radius:4px; padding:1px 5px; font-size:14px; min-width:26px; min-height:22px; }
QPushButton#btn_sort:hover { background:#313244; color:#cdd6f4; } QPushButton#btn_sort:checked { background:rgba(137,180,250,0.18); color:#89b4fa; border-color:#89b4fa; }
QPushButton#btn_tab_add { background:transparent; color:#585b70; border:none; font-size:15px; padding:0 4px; min-width:22px; min-height:22px; }
QPushButton#btn_tab_add:hover { color:#cdd6f4; }
QTabWidget::pane { border:none; background:transparent; } QTabWidget { background:transparent; }
QTabBar { background:#11111b; }
QTabBar::tab { background:#11111b; color:#585b70; border:none; border-bottom:2px solid transparent; padding:5px 10px; font-size:12px; margin-right:1px; }
QTabBar::tab:selected { color:#89b4fa; border-bottom-color:#89b4fa; background:#181825; }
QTabBar::tab:hover:!selected { color:#a6adc8; background:#181825; }
QTextEdit { background:transparent; color:#cdd6f4; border:none; font-size:13px; selection-background-color:#45475a; }
QTableWidget { background:#181825; gridline-color:#313244; border:none; outline:none; }
QTableWidget::item { padding:0; border:none; background:transparent; }
QTableWidget::item:selected { background:rgba(137,180,250,0.20); }
QHeaderView { background:#1e1e2e; }
QHeaderView::section { background:#1e1e2e; color:#a6adc8; border:none; border-right:1px solid #313244; border-bottom:1px solid #45475a; padding:5px 4px; font-size:12px; font-weight:600; }
QMenu { background:#1e1e2e; color:#cdd6f4; border:1px solid #45475a; border-radius:6px; padding:4px; }
QMenu::item { padding:6px 20px; border-radius:4px; } QMenu::item:selected { background:rgba(137,180,250,0.18); color:#89b4fa; }
QScrollBar:vertical   { background:#181825; width:8px;  border-radius:4px; }
QScrollBar:horizontal { background:#181825; height:8px; border-radius:4px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background:#45475a; border-radius:4px; min-width:20px; min-height:20px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background:#585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QComboBox { background:#313244; color:#cdd6f4; border:1px solid #45475a; border-radius:4px; padding:4px 8px; }
QComboBox QAbstractItemView { background:#1e1e2e; color:#cdd6f4; selection-background-color:#313244; }
QSplitter::handle { background:#313244; }
"""


TILE_MIME  = "application/x-tile-question"


_THEME_MIME = "application/x-siq-theme"


_RE_TILE_BORDER = re.compile(r'border:1px solid [^;]+;')


_SS_TRANSPARENT   = "background:transparent;"


_SS_DARK_BASE     = "background:#181825;"


_SS_SEPARATOR_H   = "background:#313244; max-height:1px;"


_SS_LABEL_DIM     = "color:#585b70;font-size:10px;background:transparent;"


_SS_LABEL_MUTED   = "color:#a6adc8;font-size:11px;"


_SS_LABEL_MICRO   = "color:#6c7086;font-size:10px;"


_SS_BTN_ICON      = "QPushButton{background:transparent;color:#585b70;border:none;padding:0;font-size:13px;}"


_SS_DIALOG        = "QDialog{background:#181825;color:#cdd6f4;}"


_ON_BTN_DEL     = "btn_del"


_ON_BTN_COMPARE = "btn_compare"


_ON_BTN_ANALYZE = "btn_analyze"


_ON_BTN_SORT    = "btn_sort"


_ON_BTN_UPDATE  = "btn_update"


_SS_DROP_ZONE     = ("QFrame#drop_zone{background:#181825;border:2px dashed #45475a;"
                     "border-radius:8px;}")


_SS_DROP_ZONE_LG  = ("QFrame#drop_zone{background:#181825;border:2px dashed #45475a;"
                     "border-radius:16px;}")


_SS_DROP_ZONE_HOV = ("QFrame#drop_zone{background:rgba(137,180,250,0.06);"
                     "border:2px dashed #89b4fa;border-radius:8px;}")


_SS_SECTION_HDR   = ("color:#6c7086;font-size:9px;font-weight:700;letter-spacing:2px;"
                     "background:rgba(255,255,255,0.02);")


_SS_LABEL_DIM_BRD = ("color:#585b70;font-size:10px;background:transparent;"
                     "border:1px solid #313244;")


_SS_PANEL_BORDER  = ("QFrame{background:#1e1e2e;border-right:1px solid #45475a;"
                     "border-bottom:1px solid #313244;}")


_SS_INPUT_DARK    = ("QLineEdit{background:#181825;color:#cdd6f4;border:1px solid #45475a;"
                     "border-radius:4px;padding:4px 8px;font-size:12px;}"
                     "QLineEdit:focus{border-color:#89b4fa;}")


_SS_TOPBAR        = "background:#11111b;border-bottom:1px solid #313244;"


_SS_TOPBAR_LABEL  = ("color:#6c7086;font-size:9px;font-weight:700;letter-spacing:2px;"
                     "background:#11111b;padding:4px 14px;border-bottom:1px solid #313244;")


_SS_PANEL_BRD2    = ("QFrame{background:#1e1e2e;border-right:1px solid #45475a;"
                     "border-bottom:1px solid #45475a;}")


_SS_INPUT_LARGE   = ("QLineEdit{background:#181825;color:#cdd6f4;border:1px solid #45475a;"
                     "border-radius:6px;padding:6px 12px;font-size:13px;}"
                     "QLineEdit:focus{border-color:#89b4fa;}")


_SS_BADGE_MUTED   = ("color:#585b70;font-size:10px;background:transparent;"
                     "border:1px solid #45475a;border-radius:3px;padding:1px 5px;")


_WASD_MAP: dict[int, tuple[int, int]] = {
    int(Qt.Key.Key_A): (-1, 0), int(Qt.Key.Key_D): (1, 0),   # Latin A / D
    int(Qt.Key.Key_W): (0, -1), int(Qt.Key.Key_S): (0,  1),  # Latin W / S
    0x444: (-1, 0), 0x432: (1, 0), 0x446: (0, -1), 0x44B: (0, 1),  # ф/в/ц/ы
    0x424: (-1, 0), 0x412: (1, 0), 0x426: (0, -1), 0x42B: (0, 1),  # Ф/В/Ц/Ы
}


SORT_NONE=0; SORT_COMPLETION=1; SORT_TRIES=2; SORT_RIGHT=3


SORT_NONE=0; SORT_COMPLETION=1; SORT_TRIES=2; SORT_RIGHT=3


SORT_NONE=0; SORT_COMPLETION=1; SORT_TRIES=2; SORT_RIGHT=3


SORT_NONE=0; SORT_COMPLETION=1; SORT_TRIES=2; SORT_RIGHT=3

__all__ = [
    'SORT_COMPLETION',
    'SORT_NONE',
    'SORT_RIGHT',
    'SORT_TRIES',
    'STYLESHEET',
    'TILE_MIME',
    '_AUDIO_EXTS',
    '_AlignC',
    '_AlignL',
    '_AlignR',
    '_AlignTop',
    '_AlignVC',
    '_C_ACCENT',
    '_C_ACCENT2',
    '_C_ACCENT3',
    '_C_BG',
    '_C_BG2',
    '_C_BG3',
    '_C_BG4',
    '_C_BORDER',
    '_C_GREEN',
    '_C_PURPLE',
    '_C_RED',
    '_C_TEXT',
    '_C_TEXT2',
    '_C_TEXT3',
    '_C_TEXT4',
    '_C_TEXT_DIM',
    '_DEL_SS_HIDDEN',
    '_DEL_SS_SHOWN',
    '_DH_SS_HIDDEN',
    '_DH_SS_SHOWN',
    '_Expand',
    '_Fixed',
    '_IMG_EXTS',
    '_ITEM_FOCUS_SS',
    '_ITEM_INNER_SS',
    '_ITEM_JOIN_SS',
    '_ITEM_OUTER_SS',
    '_MEDIA_EXTS',
    '_MIME_ANS',
    '_MIME_BLOCK',
    '_Minimum',
    '_ON_BTN_ANALYZE',
    '_ON_BTN_COMPARE',
    '_ON_BTN_DEL',
    '_ON_BTN_SORT',
    '_ON_BTN_UPDATE',
    '_Pref',
    '_RB_ACTIVE',
    '_RB_HOV',
    '_RB_OFF',
    '_RE_TILE_BORDER',
    '_SB_HOV',
    '_SB_OFF',
    '_SB_ON',
    '_SS_BADGE_MUTED',
    '_SS_BG',
    '_SS_BG_NONE',
    '_SS_BTN_ICON',
    '_SS_DARK_BASE',
    '_SS_DIALOG',
    '_SS_DIVIDER',
    '_SS_DROP_ZONE',
    '_SS_DROP_ZONE_HOV',
    '_SS_DROP_ZONE_LG',
    '_SS_INPUT_DARK',
    '_SS_INPUT_LARGE',
    '_SS_LABEL_DIM',
    '_SS_LABEL_DIM_BRD',
    '_SS_LABEL_MICRO',
    '_SS_LABEL_MUTED',
    '_SS_LBL_MED',
    '_SS_LBL_SM',
    '_SS_LBL_XS',
    '_SS_PANEL_BORDER',
    '_SS_PANEL_BRD2',
    '_SS_SECTION_HDR',
    '_SS_SEPARATOR_H',
    '_SS_TOPBAR',
    '_SS_TOPBAR_LABEL',
    '_SS_TRANSPARENT',
    '_TB_HOV',
    '_TB_OFF',
    '_TB_ON',
    '_THEME_MIME',
    '_VIDEO_EXTS',
    '_WASD_MAP',
]
