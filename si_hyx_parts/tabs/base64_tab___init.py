# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Base64Tab: __init__. Public namespace: tabs."""
import tabs as _api


def __init__(self, main_window):
    super(_api.Base64Tab, self).__init__()
    self.main = main_window
    self._stop_flag = _api.threading.Event()
    self._sig_done.connect(self._on_done)
    self._sig_error.connect(self._on_error)
    self._sig_progress.connect(self.progress_update)
    self._current_path = ""
    self._html_paths = []      # все загруженные HTML — кнопка маскирует ВСЕ
    self._build_ui()

def progress_update(self, pct: int):
    self.progress.setValue(pct)

def add_paths(self, paths):
    """Принимает один или несколько файлов. HTML-файлы запоминаются целиком —
        кнопка «Замаскировать HTML» маскирует ВСЕ загруженные HTML; прочий файл
        (один) сразу кодируется в base64."""
    self._route_paths(paths)

@staticmethod
def _is_html(p):
    return _api.os.path.splitext(p)[1].lower() in (".html", ".htm")

def _route_paths(self, paths):
    paths = [p for p in (paths or []) if p]
    if not paths:
        return
    html = [p for p in paths if self._is_html(p)]
    # Запоминаем ВЕСЬ список HTML: кнопка маскировки обработает их пакетно.
    # Раньше при дропе нескольких файлов маскировка запускалась сразу, а
    # кнопка потом обрабатывала только текущий (первый) файл — остальные
    # выглядели «скопированными как есть». Теперь единый триггер — кнопка.
    self._html_paths = html
    if html:
        self._set_path(html[0])
        if len(html) > 1:
            self.lbl_size.setText(_api.status_html('fa5s.layer-group',
                f"Загружено HTML: {len(html)} — нажмите «Замаскировать HTML»", '#89b4fa'))
    else:
        self._set_path(paths[0])

def _build_ui(self):
    root = _api.QVBoxLayout(self)
    root.setContentsMargins(12, 12, 12, 12)
    root.setSpacing(10)

    # ── Верхний блок: миниатюра + кнопки ────────────────────────────────
    top = _api.QHBoxLayout()

    # Миниатюра — принимает дроп
    self.lbl_thumb = _api.QLabel()
    self.lbl_thumb.setFixedSize(120, 90)
    self.lbl_thumb.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
    self.lbl_thumb.setStyleSheet(
        "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; color:#6c7086; font-size:11px;")
    self.lbl_thumb.setText("нет\nфайла")
    top.addWidget(self.lbl_thumb)

    top.addSpacing(12)

    # Правая колонка: имя файла + кнопки
    right = _api.QVBoxLayout()
    self.lbl_fname = _api.QLabel("Файл не выбран")
    self.lbl_fname.setStyleSheet("color:#cdd6f4; font-size:12px;")
    self.lbl_fname.setWordWrap(True)
    right.addWidget(self.lbl_fname)

    self.lbl_hint = _api.QLabel(_api.status_html('fa5s.lightbulb',
        "Перетащите файл (или сразу несколько HTML) из любой "
        "вкладки или с рабочего стола", '#6c7086', 11))
    self.lbl_hint.setStyleSheet("color:#6c7086; font-size:10px;")
    right.addWidget(self.lbl_hint)
    right.addStretch()

    btn_row = _api.QHBoxLayout()
    btn_browse = _api._icon_btn("Выбрать файл", 'fa5s.folder-open')
    btn_browse.clicked.connect(self._browse)

    # Кнопка «Кодировать» убрана: файлы кодируются автоматически при
    # добавлении (drag&drop / «Выбрать файл»).
    self.btn_stop = _api._icon_btn("Очистить", 'fa5s.trash')
    self.btn_stop.setFixedHeight(32)
    self.btn_stop.setEnabled(True)
    self.btn_stop.clicked.connect(self._clear_result)

    btn_row.addWidget(btn_browse)
    btn_row.addWidget(self.btn_stop)
    right.addLayout(btn_row)

    # ── Маскировка HTML под VK (скрытие JS) ─────────────────────────────
    mask_row = _api.QHBoxLayout()
    self.btn_mask_file = _api._icon_btn("Замаскировать HTML (JavaScript) для VK", 'fa5s.mask')
    self.btn_mask_file.setFixedHeight(32)
    self.btn_mask_file.setToolTip("Прячет JavaScript, чтобы обойти запрет VK.\n"
                                  "Если загружено несколько HTML — маскирует все.")
    self.btn_mask_file.clicked.connect(self._mask_html_action)

    self.btn_mask_folder = _api._icon_btn("Замаскировать все HTML (JavaScript) в папке для VK", 'fa5s.mask')
    self.btn_mask_folder.setFixedHeight(32)
    self.btn_mask_folder.setToolTip(
        "Пакетно обрабатывает все .html в выбранной папке.\n"
        "Оригиналы не трогаются — результат в подпапке encoded\\")
    self.btn_mask_folder.clicked.connect(self._mask_folder_html)

    mask_row.addWidget(self.btn_mask_file)
    mask_row.addWidget(self.btn_mask_folder)
    right.addLayout(mask_row)

    # Галочка: переименовывать ли выходной HTML (добавлять суффикс _base).
    # Включена — поведение как раньше (<имя>_base.html).
    # Выключена — файл на выходе сохраняет оригинальное имя (<имя>.html).
    self.chk_rename_html = _api.QCheckBox("Переименовывать выходной HTML (суффикс _base)")
    self.chk_rename_html.setChecked(True)
    self.chk_rename_html.setToolTip(
        "Включено: результат маскировки называется <имя>_base.html.\n"
        "Выключено: выходной HTML сохраняет оригинальное имя <имя>.html.")
    right.addWidget(self.chk_rename_html)

    # Лёгкий режим маскировки: прячет только сам движок (скрипты с логикой)
    # одним непрерывным base64-блобом через (0,eval), а разметку/картинки/
    # конфиги оставляет как есть. Файл на выходе меньше (+33% лишь на коде,
    # а не +34% на весь документ). Выключено — прежний надёжный алгоритм.
    self.chk_lite_mask = _api.QCheckBox("Лёгкий режим (меньше размер)")
    self.chk_lite_mask.setChecked(False)
    self.chk_lite_mask.setToolTip(
        "Включено: прячется только код движка одним base64-блобом (0,eval); "
        "разметка, картинки и скрипты-данные остаются как есть — выходной файл "
        "заметно меньше. Рассчитано на игры с одним движком.\n"
        "Выключено: прежний алгоритм (кодирует весь <body>) — надёжнее для "
        "сложных много-скриптовых страниц.")
    right.addWidget(self.chk_lite_mask)

    top.addLayout(right, 1)
    root.addLayout(top)

    # ── Прогресс-бар ─────────────────────────────────────────────────────
    self.progress = _api.QProgressBar()
    self.progress.setRange(0, 100)
    self.progress.setValue(0)
    self.progress.setFixedHeight(8)
    self.progress.hide()
    root.addWidget(self.progress)

    # ── Результат ─────────────────────────────────────────────────────────
    grp_out = _api.QGroupBox("Результат (Base64)")
    vl = _api.QVBoxLayout(grp_out)

    self.txt_out = _api.QPlainTextEdit()
    self.txt_out.setReadOnly(True)
    self.txt_out.setPlaceholderText("Здесь появится Base64-строка после кодирования…")
    self.txt_out.setFont(_api.QFont("Courier New", 9))
    self.txt_out.setMinimumHeight(80)
    self.txt_out.setMaximumHeight(260)
    vl.addWidget(self.txt_out)

    # Сохранять ли результат в <имя>_base64.txt рядом с файлом.
    # По умолчанию ВЫКЛ — base64 копируется в буфер и показан в поле,
    # лишний .txt на диск не пишется.
    self.chk_make_txt = _api.QCheckBox("Создавать .txt файл")
    self.chk_make_txt.setChecked(False)
    self.chk_make_txt.setToolTip(
        "Включено: рядом с файлом сохраняется <имя>_base64.txt.\n"
        "Выключено: результат только в этом поле и в буфере обмена.")
    vl.addWidget(self.chk_make_txt)

    h_btns = _api.QHBoxLayout()
    self.lbl_size = _api.QLabel("")
    self.lbl_size.setStyleSheet("color:#6c7086; font-size:11px;")
    btn_copy = _api._icon_btn("Копировать", 'fa5s.copy')
    btn_copy.setFixedWidth(130)
    btn_copy.clicked.connect(self._copy)
    h_btns.addWidget(self.lbl_size)
    h_btns.addStretch()
    h_btns.addWidget(btn_copy)
    vl.addLayout(h_btns)

    root.addWidget(grp_out, 1)
    self.setAcceptDrops(True)

# ── Drag & drop ───────────────────────────────────────────────────────────
def dragEnterEvent(self, e):
    if e.mimeData().hasUrls(): e.acceptProposedAction()

def dragMoveEvent(self, e):
    if e.mimeData().hasUrls(): e.acceptProposedAction()

def dropEvent(self, e):
    urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
    if urls: self._route_paths(urls)

# ── Вспомогательные ──────────────────────────────────────────────────────
def _browse(self):
    # Строим фильтры: популярные группы + «Все файлы»
    media   = "Медиафайлы (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v *.ts *.3gp *.mp3 *.opus *.wav *.flac *.ogg *.aac *.m4a *.wma *.aiff)"
    images  = "Изображения (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.tiff *.avif *.heic *.heif *.ico *.svg)"
    model3d = "3D / Игровые ассеты (*.glb *.gltf *.obj *.fbx *.dae *.3ds *.stl *.ply *.blend *.usdz *.usd *.abc *.pak *.vpk *.bsp *.mdl *.vtf *.prefab *.asset)"
    docs    = "Документы (*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt *.rtf *.odt *.csv *.md *.json *.xml *.yaml *.yml *.toml)"
    fonts   = "Шрифты (*.ttf *.otf *.woff *.woff2 *.eot)"
    archives= "Архивы (*.zip *.rar *.7z *.tar *.gz *.bz2 *.xz *.zst)"
    other   = "Прочее (*.bin *.dat *.db *.sqlite *.iso *.img *.dmg)"
    html    = "HTML (*.html *.htm)"
    all_f   = "Все файлы (*)"
    flt = ";;".join([media, images, model3d, docs, fonts, archives, html, other, all_f])
    # Можно выбрать несколько файлов: несколько HTML маскируются разом.
    paths, _ = _api.QFileDialog.getOpenFileNames(self, "Выбрать файл(ы) для кодирования в Base64", "", flt)
    if paths: self._route_paths(paths)

def _set_path(self, path):
    self._current_path = path
    self.lbl_fname.setText(_api.os.path.basename(path))
    self.lbl_hint.hide()
    self.txt_out.clear()
    self.lbl_size.setText("")
    self._load_thumb(path)
    # HTML-файлы предназначены для маскировки под VK, а не для обычного
    # base64: НЕ запускаем авто-кодирование (никаких .txt и дампа base64 в
    # GUI) — пользователь жмёт «🎭 Замаскировать HTML (JavaScript) для VK».
    if _api.os.path.splitext(path)[1].lower() in (".html", ".htm"):
        self.lbl_size.setText("HTML готов — нажмите «Замаскировать HTML (JavaScript) для VK»")
    else:
        # Для прочих файлов — авто-кодирование сразу после выбора
        _api.QTimer.singleShot(80, self._start_encode)

def _load_thumb(self, path):
    ext = _api.os.path.splitext(path)[1].lower()
    icon_val = self._ICON_MAP.get(ext, 'fa5s.box')  # fa5s.box — для неизвестных

    # Изображения — показываем превью
    img_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp',
                '.tiff', '.tif', '.avif', '.heic', '.heif', '.ico'}
    if ext in img_exts:
        pix = _api.QPixmap()
        if _api.Image:
            try:
                with _api.Image.open(path) as im:
                    if _api.ImageOps: im = _api.ImageOps.exif_transpose(im)
                    im.thumbnail((240, 180))
                    bio = _api.io.BytesIO()
                    im.convert("RGBA").save(bio, "PNG")
                    pix.loadFromData(_api.QByteArray(bio.getvalue()))
            except Exception:
                pass
        if pix.isNull():
            pix = _api.QPixmap(path)
        if not pix.isNull():
            self.lbl_thumb.setPixmap(
                pix.scaled(120, 90, _api.Qt.AspectRatioMode.KeepAspectRatio,
                           _api.Qt.TransformationMode.SmoothTransformation))
            return

    # Видео — пытаемся вытащить кадр через ffmpeg
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv',
                  '.m4v', '.ts', '.mts', '.m2ts', '.vob', '.ogv', '.3gp',
                  '.3g2', '.divx', '.f4v', '.mxf', '.rm', '.rmvb'}
    if ext in video_exts:
        pix = _api.QPixmap()
        try:
            tmp = _api.os.path.join(_api.tempfile.gettempdir(), f"ym_b64_thumb_{_api.uuid.uuid4().hex}.jpg")
            _api.subprocess.run([_api.FFMPEG, "-y", "-i", path, "-vframes", "1", "-q:v", "5", tmp],
                           stdout=_api.subprocess.DEVNULL, stderr=_api.subprocess.DEVNULL,
                           creationflags=_api.CREATE_NO_WINDOW, timeout=8)
            if _api.os.path.exists(tmp):
                pix = _api.QPixmap(tmp)
                try: _api.os.remove(tmp)
                except Exception: pass
        except Exception:
            pass
        if not pix.isNull():
            self.lbl_thumb.setPixmap(
                pix.scaled(120, 90, _api.Qt.AspectRatioMode.KeepAspectRatio,
                           _api.Qt.TransformationMode.SmoothTransformation))
            return

    # Для всего остального — большой векторный значок типа файла + расширение.
    icon_name = icon_val if icon_val else 'fa5s.box'
    ext_upper = ext.upper().lstrip('.') if ext else '??'
    self.lbl_thumb.setText(
        f"{_api.icon_html(icon_name, 30, '#89b4fa')}<br>{ext_upper}")
    self.lbl_thumb.setStyleSheet(
        "background:#1e1e2e; border:1px solid #45475a; border-radius:6px; "
        "color:#89b4fa; font-size:18px; qproperty-alignment: AlignCenter;")

def _copy(self):
    text = self.txt_out.toPlainText()
    if text:
        _api.QApplication.clipboard().setText(text)
        self.main.log("Base64 скопирован в буфер обмена")

# ── Маскировка HTML под VK ───────────────────────────────────────────────
@staticmethod
def _read_html(path):
    # utf-8-sig снимает возможный BOM; ошибки декодирования не роняют процесс
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return f.read()
