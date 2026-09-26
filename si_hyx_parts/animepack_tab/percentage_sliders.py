"""One percentage slider per enabled question type."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider


class PercentageSliders:
    def build_rows(self):
        self.setMinimumHeight(0)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.rows = {}
        self.sliders = {}
        self.row_labels = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for key in self.KEYS:
            row = QWidget()
            box = QVBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            label = QLabel()
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.wheelEvent = lambda event: event.ignore()
            slider.valueChanged.connect(lambda value, k=key: self.move_share(k, value))
            box.addWidget(label)
            box.addWidget(slider)
            layout.addWidget(row)
            self.rows[key], self.sliders[key], self.row_labels[key] = row, slider, label
        self.sync_rows()

    def sync_rows(self):
        if not hasattr(self, "rows"):
            return
        for key, row in self.rows.items():
            row.setVisible(key in self._keys)
            value = self.shares()[key]
            self.row_labels[key].setText(f"{self.LABELS[key]} — {value}%")
            self.sliders[key].blockSignals(True)
            self.sliders[key].setValue(value)
            self.sliders[key].blockSignals(False)
            self.sliders[key].setEnabled(len(self._keys) > 1)

    def move_share(self, key, value):
        others = [k for k in self._keys if k != key]
        if not others:
            return
        total = sum(self._vals.get(k, 0) for k in others)
        weights = {k: self._vals.get(k, 0) if total else 1 for k in others}
        total = sum(weights.values())
        left = 100 - value
        vals = {k: left * weights[k] // total for k in others}
        for k in sorted(others, key=lambda k: -(left * weights[k] % total))[:left - sum(vals.values())]:
            vals[k] += 1
        vals[key] = value
        self._vals.update(vals)
        self.sync_rows()
        self.changed.emit()

    def _sync_height(self):
        self.sync_rows()

    def paintEvent(self, event):
        pass

    def mousePressEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def sizeHint(self):
        return QWidget.sizeHint(self)
