# SI-HYX; GNU GPL v3 or later. See LICENSE.
STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 5px 14px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    background-color: #1e1e2e;
    color: #585b70;
    border-color: #313244;
}
QPushButton:checked {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    border-color: #89b4fa;
}
QPushButton#b_run {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
    padding: 6px 20px;
}
QPushButton#b_run:hover { background-color: #94e2d5; }
QPushButton#b_run:disabled { background-color: #585b70; color: #1e1e2e; }
QPushButton#b_stop {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
}
QPushButton#b_stop:hover { background-color: #eba0ac; }
QPushButton#b_stop:disabled { background-color: #585b70; color: #1e1e2e; }
QPushButton#b_restart {
    background-color: #fab387;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
}
QPushButton#b_restart:hover { background-color: #f9e2af; }
QToolButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 24px;
}
QToolButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}
/* Встроенная кнопка очистки (✕) внутри QLineEdit/QComboBox — без рамки,
   паддинга и min-height, иначе она наследует стиль QToolButton и смещается. */
QLineEdit QToolButton, QComboBox QToolButton {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
    min-width: 0px;
    min-height: 0px;
}
QLineEdit QToolButton:hover, QComboBox QToolButton:hover {
    background: transparent;
    border: none;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
    min-height: 22px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #89b4fa;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #45475a;
    border: none;
    width: 16px;
    border-radius: 2px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #585b70;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {
    border-bottom-color: #585b70;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    border-top-color: #585b70;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 22px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    selection-background-color: #45475a;
    outline: none;
}
QTreeWidget {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    alternate-background-color: #1e1e2e;
    show-decoration-selected: 1;
    outline: none;
}
QTreeWidget::item {
    padding: 3px 2px;
    border: none;
}
QTreeWidget::item:hover {
    background-color: transparent;
}
QTreeWidget::item:selected {
    background-color: transparent;
    color: #cdd6f4;
}
QTableWidget {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    alternate-background-color: #1e1e2e;
    gridline-color: #313244;
    outline: none;
}
QTableWidget::item {
    padding: 3px 2px;
    border: none;
}
QTableWidget::item:hover {
    background-color: #313244;
}
QTableWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
QTableWidget::item:selected:active {
    background-color: #585b70;
}
QHeaderView::section {
    background-color: #24273a;
    color: #89b4fa;
    border: none;
    border-right: 1px solid #45475a;
    border-bottom: 1px solid #45475a;
    padding: 5px 8px;
    font-weight: bold;
    font-size: 12px;
}
QHeaderView::section:last { border-right: none; }
QTextEdit {
    background-color: #181825;
    color: #a6e3a1;
    border: 1px solid #45475a;
    border-radius: 4px;
    font-family: 'Consolas', 'Cascadia Code', 'Courier New', monospace;
    font-size: 12px;
    padding: 2px;
}
QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    text-align: center;
    color: #cdd6f4;
    font-weight: bold;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #89b4fa, stop:1 #cba6f7);
    border-radius: 4px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-top: none;
    border-bottom-left-radius: 5px;
    border-bottom-right-radius: 5px;
}
QTabBar::tab {
    background-color: #24273a;
    color: #a6adc8;
    border: 1px solid #45475a;
    border-bottom: none;
    padding: 5px 12px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
}
QTabBar::tab:hover:!selected {
    background-color: #313244;
    color: #cdd6f4;
}
QCheckBox {
    color: #cdd6f4;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #585b70;
    border-radius: 4px;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QCheckBox::indicator:hover { border-color: #89b4fa; }
QSlider::groove:horizontal {
    height: 5px;
    background: #45475a;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    border: 2px solid #1e1e2e;
}
QSlider::handle:horizontal:hover { background: #cba6f7; }
QSlider::sub-page:horizontal {
    background: #89b4fa;
    border-radius: 3px;
}
QScrollBar:vertical {
    background: #181825;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #181825;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #585b70; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 20px;
    border-radius: 4px;
}
QMenu::item:selected { background-color: #45475a; }
QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 8px;
}
QLabel { color: #cdd6f4; }
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget { background: transparent; }
QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QMessageBox { background-color: #1e1e2e; color: #cdd6f4; }
QMessageBox QLabel { color: #cdd6f4; }
QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #89b4fa;
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}
QLabel#infoBadge {
    color: #89b4fa;
    font-weight: bold;
    font-size: 13px;
    border-radius: 9px;
    background: transparent;
}
QLabel#infoBadge:hover {
    color: #cba6f7;
    background: rgba(137,180,250,0.18);
}
"""
