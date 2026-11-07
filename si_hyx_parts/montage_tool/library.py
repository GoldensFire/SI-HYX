# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Каталог планов исходников: index, search, shot-sheet, characters.
Public namespace: montage_tool.

SQLite (по умолчанию ~/.cache/si-hyx-montage/index/library.sqlite) и
миниатюры в кэше. Файл переиндексируется, только если изменились размер или
время правки (или версия индекса); перенесённый файл узнаётся по хэшу
(размер + первые и последние 4 МБ). Один файл — этапами, каждая модель
грузится на свой этап и выгружается (память общая с видеокартой):
отпечаток звука (опенинг и эндинг, уже встреченные в папке, дальше не
разбираются), декод и планы (shots.py), миниатюры; затем двумя потоками —
на iGPU лица/головы/фигуры → крупность плана и теги WD, на CPU текст и
CCIP по фигурам → персонажи; потом речь;
по запросу — подписи планов локальной моделью зрения (caption_shots).
После файлов — повторы звука ≥ 60 с между файлами (chromaprint) →
опенинг/эндинг (такие планы по умолчанию не ищутся) и кластеры персонажей
по папкам (имена, данные characters --rename, переходят к новому кластеру
по большинству). Процесс идёт с пониженным приоритетом и под общим замком
моделей (chiptune.gate.model_slot)."""
import collections
import hashlib
import json
import sqlite3
import threading
import time

import numpy as np

import montage_tool as _api
from si_hyx_parts.montage_tool import analysis as _an
from si_hyx_parts.montage_tool import shots as _shots
from si_hyx_parts.montage_tool import vision as _vision

INDEX_VERSION = 2
VIDEO_EXT = (".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts", ".m2ts", ".wmv", ".flv")
OPED_MIN_S = 60.0
FP_ITEM_S = 4096 / 3 / 11025          # шаг отпечатка chromaprint (11025 Гц, окно 4096, ⅔ перекрытие)
SCALES = ("closeup", "medium", "wide", "none")
THUMB_W = 320
_HASH_CHUNK = 4 << 20
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE, size INTEGER, mtime REAL, hash TEXT,
    duration REAL, fps REAL, width INTEGER, height INTEGER, frames INTEGER,
    version INTEGER, indexed_at TEXT, timing TEXT);
CREATE TABLE IF NOT EXISTS shots(
    id INTEGER PRIMARY KEY, file_id INTEGER, idx INTEGER, kind TEXT, f0 INTEGER, f1 INTEGER,
    t0 REAL, t1 REAL, motion REAL, motion_peak REAL, camera REAL, object REAL,
    dup_ratio REAL, static INTEGER, brightness REAL, saturation REAL, colors TEXT,
    accents TEXT, faces INTEGER, heads INTEGER, persons INTEGER, scale TEXT,
    face_frac REAL, rating TEXT, text TEXT, has_text INTEGER, hardsub INTEGER,
    speech REAL, oped TEXT, keyframes TEXT, description TEXT, gemini TEXT, caption TEXT);
CREATE INDEX IF NOT EXISTS shots_file ON shots(file_id);
CREATE TABLE IF NOT EXISTS shot_tags(shot_id INTEGER, tag TEXT, score REAL, cat INTEGER);
CREATE INDEX IF NOT EXISTS shot_tags_tag ON shot_tags(tag);
CREATE INDEX IF NOT EXISTS shot_tags_shot ON shot_tags(shot_id);
CREATE TABLE IF NOT EXISTS crops(
    id INTEGER PRIMARY KEY, shot_id INTEGER, box TEXT, feat BLOB, char_id INTEGER);
CREATE INDEX IF NOT EXISTS crops_shot ON crops(shot_id);
CREATE TABLE IF NOT EXISTS characters(id INTEGER PRIMARY KEY, name TEXT, size INTEGER);
CREATE TABLE IF NOT EXISTS prints(file_id INTEGER PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS oped(file_id INTEGER, t0 REAL, t1 REAL, kind TEXT, other INTEGER);
CREATE TABLE IF NOT EXISTS speech_lines(
    id INTEGER PRIMARY KEY, file_id INTEGER, t0 REAL, t1 REAL, text TEXT, words TEXT,
    model TEXT);
CREATE INDEX IF NOT EXISTS speech_lines_file ON speech_lines(file_id);
"""


# ── База ─────────────────────────────────────────────────────────────────────
def default_db():
    return _api.os.path.join(_api.cache_dir("index"), "library.sqlite")


def connect(db=None):
    path = str(db or default_db())
    d = _api.os.path.dirname(_api.os.path.abspath(path))
    _api.os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(_SCHEMA)
    if "caption" not in {r[1] for r in con.execute("PRAGMA table_info(shots)")}:
        con.execute("ALTER TABLE shots ADD COLUMN caption TEXT")   # каталог до подписей
    return con


def file_hash(path, size):
    """sha256(размер + первые и последние 4 МБ) — узнать перенесённый файл."""
    h = hashlib.sha256(str(size).encode("ascii"))
    with open(path, "rb") as f:
        h.update(f.read(_HASH_CHUNK))
        if size > 2 * _HASH_CHUNK:
            f.seek(size - _HASH_CHUNK)
            h.update(f.read(_HASH_CHUNK))
    return h.hexdigest()


def list_media(target):
    target = _api.os.path.abspath(str(target))
    if _api.os.path.isfile(target):
        return [target]
    if not _api.os.path.isdir(target):
        raise _api.ToolError("missing_files", f"нет файла или папки: {target}")
    out = []
    for root, _dirs, names in _api.os.walk(target):
        for n in names:
            if n.lower().endswith(VIDEO_EXT):
                out.append(_api.os.path.join(root, n))
    return sorted(out)


def _low_priority():
    """Процесс индекса и его ffmpeg — с пониженным приоритетом (Windows)."""
    if _api.os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except (OSError, AttributeError):
        pass


# ── Один файл ────────────────────────────────────────────────────────────────
def _sample_index(t, t0, t1, count):
    """Номер JPEG (4 в секунду) для времени t внутри [t0, t1)."""
    k = int(round(t * _shots.SAMPLE_FPS))
    lo = int(np.ceil(t0 * _shots.SAMPLE_FPS))
    hi = int(np.floor((t1 - 1e-6) * _shots.SAMPLE_FPS))
    if lo <= hi:
        k = min(max(k, lo), hi)
    return min(max(0, k), max(0, count - 1))


def _scale_of(faces, heads, persons, H):
    """Крупность плана по самой большой голове/лицу и фигуре."""
    def tallest(boxes):
        return max(((b[3] - b[1]) / H for b in boxes), default=0.0)

    head = max(tallest(heads), tallest(faces) * 1.25)
    if head >= 0.32:
        return "closeup", head
    if head >= 0.12:
        return "medium", head
    if heads or faces or persons:
        return "wide", head
    return "none", 0.0


def _colors(rgb, k=4):
    """Доминирующие цвета: k-средних по уменьшенному кадру → [[#rrggbb, доля]]."""
    import cv2
    small = cv2.resize(rgb, (64, 36), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)
    _c, labels, centers = cv2.kmeans(small, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k) / len(labels)
    order = np.argsort(-counts)
    return [["#%02x%02x%02x" % tuple(int(v) for v in centers[i]), round(float(counts[i]), 3)]
            for i in order]


def _text_info(rows, W, H):
    """Текст на кадре: надёжные строки (оценка ≥ 0,8, ≥ 2 символов, не выше
    половины кадра — крупный титул тоже текст); хардсаб — строки в нижней
    четверти высотой 3–12 % кадра."""
    good = [(b, t, s) for b, t, s in rows
            if s >= 0.8 and len(t.strip()) >= 2 and (b[3] - b[1]) < 0.5 * H]
    hard = any(b[1] > 0.72 * H and 0.03 * H <= (b[3] - b[1]) <= 0.12 * H
               and (b[2] - b[0]) > 0.12 * W for b, _t, _s in good)
    return " ".join(t.strip() for _b, t, _s in good)[:500], bool(good), hard


def _chromaprint(path):
    """Отпечаток звука файла (uint32 на каждые ~0,124 с) — muxer chromaprint ffmpeg."""
    raw = _an._run_bytes([_api.FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-vn", "-sn",
                          "-ac", "1", "-f", "chromaprint", "-fp_format", "raw", "-"], timeout=1800)
    return np.frombuffer(raw[: len(raw) // 4 * 4], dtype="<u4")


def _known_oped(con, path, fpr):
    """Куски файла, чей звук ≥ 60 с повторяет уже размеченный файл той же
    папки (опенинг и эндинг серии): [(t0, t1)] в секундах. Такие планы не
    разбираются — их по умолчанию не ищут, а у каждой серии они те же."""
    if len(fpr) < 50:
        return []
    folder = _api.os.path.dirname(path)
    out = []
    for r in con.execute("SELECT f.path, p.data FROM prints p JOIN files f ON f.id=p.file_id"):
        if r["path"] == path or _api.os.path.dirname(r["path"]) != folder:
            continue
        for a0, a1, _b0, _b1 in match_runs(fpr, np.frombuffer(r["data"], "<u4")):
            if not any(min(a1, t1) - max(a0, t0) > 0 for t0, t1 in out):
                out.append((a0, a1))
    return sorted(out)


def _oped_kind(t0, t1, ranges, duration):
    """op/ed, если план больше чем наполовину внутри куска ranges, иначе ""."""
    for a, b in ranges:
        if min(t1, b) - max(t0, a) > 0.5 * (t1 - t0):
            return "op" if (a + b) / 2 < 0.5 * (duration or 1) else "ed"
    return ""


def _speech(path, shots_t):
    """Доля речи в каждом плане (speech_sync.speech_activity, как analyze)."""
    try:
        x = _an.file_audio(path)
    except _api.ToolError:
        return [0.0] * len(shots_t)
    if not len(x):
        return [0.0] * len(shots_t)
    act = _an._chunked(_an.speech_sync.speech_activity, x)
    db = _an._frame_db(x)
    n = min(len(act), len(db))
    talk = (_an._moving_mean(act[:n], 30) > 0.25) & (db[:n] > _an.SILENCE_DB)
    out = []
    for t0, t1 in shots_t:
        a, b = int(t0 * 100), max(int(t0 * 100) + 1, int(t1 * 100))
        seg = talk[a:min(b, n)]
        out.append(round(float(seg.mean()), 3) if len(seg) else 0.0)
    return out


class _Lane(threading.Thread):
    """Этап файла своим потоком рядом с основным; fn(quit) бросает работу,
    когда quit поднят. result() — секунды этапа; ошибка потока — там же."""

    def __init__(self, fn):
        super().__init__(daemon=True)
        self.fn, self.error, self.seconds = fn, None, 0.0
        self.quit = threading.Event()

    def run(self):
        t = time.monotonic()
        try:
            self.fn(self.quit)
        except Exception as e:           # noqa: BLE001 — отдаётся в result()
            self.error = e
        self.seconds = round(time.monotonic() - t, 2)

    def result(self):
        self.join()
        if self.error is not None:
            raise self.error
        return self.seconds


def _index_file(con, path, st, fhash, ctl, tagger_kind, timing, gpu=True):
    import cv2
    tmp_root = _api.cache_dir("index", "tmp")
    tmp = _api.tempfile.mkdtemp(prefix="f", dir=tmp_root)
    thumbs = _api.cache_dir("index", "thumbs", fhash[:16])
    clock = [time.monotonic()]

    def lap(name):
        now = time.monotonic()
        timing[name] = round(now - clock[0], 2)
        clock[0] = now

    try:
        # Отпечаток звука — первым (секунды): по нему опенинг и эндинг серии
        # известны до разбора кадров, их планы дальше не разбираются.
        ctl.stage("fingerprint")
        try:
            fpr = _chromaprint(path)
        except _api.ToolError:
            fpr = np.zeros(0, "<u4")
        oped_ranges = _known_oped(con, path, fpr)
        lap("fingerprint")
        fp = _shots.FramePass(path, tmp, ctl, _api.os.path.join(tmp, "scdet.txt"))
        ctl.stage("decode", path=path, frames=fp.frames_est)
        stats = _shots.FrameStats(fp.frames_est)
        # TransNetV2 — в своём потоке по мере декода (onnxruntime отпускает GIL).
        tn_model = _api.asset("shots/transnetv2.onnx", ctl)
        # Хвост окон после декода — ещё и на CPU, он к этому времени свободен.
        tns = _shots.TransNetStream(stats, _vision.session(tn_model, threads=6, dml=gpu, worker=True),
                                    ctl, tail=lambda: _vision.session(tn_model, threads=6, dml=False))
        tns.start()
        try:
            for i, frame in enumerate(fp):
                stats.add(frame)
                if i % 2000 == 1999:
                    ctl.stage("decode", frame=i + 1, frames=fp.frames_est)
        finally:
            lap("decode")
            ctl.stage("shots", frames=stats.n)
            p1, p2, skipped, windows = tns.finish()
        tn, cols = stats.arrays()
        scd = _shots.read_scdet(_api.os.path.join(tmp, "scdet.txt"))
        shots, flashes = _shots.find_shots(p1, p2, scd, tn, cols["luma"])
        timing["transnet_windows"] = [windows - skipped, windows]
        lap("transnet")
        samples = sorted(f for f in _api.os.listdir(tmp) if f.endswith(".jpg"))
        count = len(samples)
        fps = fp.fps
        rows = []
        for i, (a, b, kind) in enumerate(shots):
            t0, t1 = a / fps, (b + 1) / fps
            L = t1 - t0
            feat = _shots.shot_features(a, b, fps, cols, flashes, fp.lo_w)
            keys = [_sample_index(t, t0, t1, count) for t in (t0 + 0.15 * L, t0 + 0.5 * L,
                                                               t1 - 0.15 * L)]
            rows.append(dict(feat, idx=i, kind=kind, f0=a, f1=b, t0=round(t0, 4), t1=round(t1, 4),
                             keys=keys, mid=_api.os.path.join(tmp, f"{keys[1]:06d}.jpg"),
                             oped=_oped_kind(t0, t1, oped_ranges, fp.duration)))
        timing["oped_shots"] = sum(1 for r in rows if r["oped"])
        # Миниатюры 320 px: три ключевых кадра плана.
        for r in rows:
            paths = []
            for n_, k in enumerate(r["keys"]):
                src = _api.os.path.join(tmp, f"{k:06d}.jpg")
                dst = _api.os.path.join(thumbs, f"{r['idx']:05d}_{n_}.jpg")
                img = cv2.imread(src)
                if img is not None:
                    h = max(2, round(img.shape[0] * THUMB_W / img.shape[1]))
                    cv2.imwrite(dst, cv2.resize(img, (THUMB_W, h), interpolation=cv2.INTER_AREA),
                                [cv2.IMWRITE_JPEG_QUALITY, 85])
                    paths.append(dst)
            r["keyframes"] = paths
        lap("thumbs")

        def mids():
            """Средние кадры планов вне опенинга и эндинга."""
            for r in rows:
                if r["oped"]:
                    continue
                img = cv2.imread(r["mid"])
                yield r, (cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img is not None else None)

        # Почти тот же средний кадр, что у прошлого плана серии (диалог
        # «восьмёркой»: A-B-A-B), — его теги, текст и персонажи не считаются
        # заново, а копируются (twin): тегам ~0,8 с и CCIP ~0,4 с на кадр.
        sigs = [None] * len(rows)           # опенинг и эндинг в близнецы не идут
        H = W = 0
        for r, img in mids():
            if img is None:
                continue
            H, W = img.shape[:2]
            g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (32, 18),
                           interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
            g -= g.mean()
            sigs[r["idx"]] = g / (np.linalg.norm(g) + 1e-6)
        for i, r in enumerate(rows):
            r["twin"] = None
            if sigs[i] is None:
                continue
            for j in range(i - 1, max(-1, i - 40), -1):
                if sigs[j] is not None and rows[j]["twin"] is None and float(sigs[i] @ sigs[j]) > 0.97:
                    r["twin"] = j
                    break

        # Теги — из общей очереди планов: полоса тегов (на iGPU, если есть
        # обработчик DirectML) берёт по пачке, а основной поток, кончив свои
        # этапы, помогает ей на CPU, чтобы не ждать.
        to_tag = [r for r in rows if r["twin"] is None and not r["oped"]]
        taken = [0]
        take_lock = threading.Lock()
        detected = threading.Event()

        def detect_shots(quit_, worker):
            """Лица, головы и фигуры средних кадров, затем крупность и цвета."""
            for kind in ("face", "head", "person"):
                ctl.stage("detect", model=kind)
                d = _vision.Detector(kind, ctl, worker=worker)
                for r, img in mids():
                    if quit_.is_set():
                        return
                    ctl.check()
                    r[kind] = d.detect(img) if img is not None else []
                if isinstance(d.sess, _vision.WorkerSession):
                    d.sess.close()
                del d
            for r, img in mids():
                if img is None:
                    r.update(scale="none", face_frac=0.0, colors=[])
                    continue
                r["scale"], r["face_frac"] = _scale_of(r["face"], r["head"], r["person"], H)
                r["colors"] = _colors(img)
            detected.set()

        def tag_shots(quit_, worker=gpu):
            tg = _vision.Tagger(tagger_kind, ctl, worker=worker)
            while not quit_.is_set():
                ctl.check()
                with take_lock:
                    part = to_tag[taken[0]:taken[0] + tg.step]
                    taken[0] += len(part)
                if not part:
                    return
                imgs = [(r, cv2.imread(r["mid"])) for r in part]
                imgs = [(r, cv2.cvtColor(img, cv2.COLOR_BGR2RGB)) for r, img in imgs if img is not None]
                for (r, _img), res in zip(imgs, tg.tag_batch([img for _r, img in imgs])):
                    r["general"], r["chars"], r["rating"] = res

        def gpu_lane(quit_):
            # С видеокартой полоса сначала гонит детекторы на iGPU, а процессор
            # тем временем читает текст; без неё детекторы — в основном потоке.
            if gpu:
                detect_shots(quit_, True)
                timing["detect_gpu"] = round(time.monotonic() - lane_t0, 2)
            if not quit_.is_set():
                ctl.stage("tags", model=tagger_kind)
                tag_shots(quit_)

        def ocr_shots():
            ctl.stage("ocr")
            ocr = _vision.OCR()
            for r, img in mids():
                ctl.check()
                if img is None:
                    r.update(text="", has_text=False, hardsub=False)
                    continue
                if r["twin"] is None:
                    r["text"], r["has_text"], r["hardsub"] = _text_info(ocr.read(img), W, H)
            del ocr
            lap("ocr")

        # Теги WD (треть времени файла) — своим потоком рядом с CCIP и текстом:
        # те от тегов не зависят, а onnxruntime отпускает GIL. Замер Gate 07
        # (411 планов): теги на iGPU параллельно с CPU — файл 492 с против 1129
        # по очереди на CPU. Арслан 17 (438 планов): детекторы, CCIP и OCR на
        # CPU шли 7 мин, теги на iGPU кончали на 3 мин раньше — поэтому
        # детекторы ушли в полосу видеокарты, а процессор начинает с текста.
        lane_t0 = time.monotonic()
        tags_lane = _Lane(gpu_lane)
        tags_lane.start()
        try:
            if gpu:
                ocr_shots()
                while not detected.wait(0.2):
                    ctl.check()
                    if not tags_lane.is_alive():
                        tags_lane.result()           # ошибка полосы — здесь
                        raise _api.ToolError("internal", "детекторы не завершились")
                lap("detect_wait")
            else:
                detect_shots(threading.Event(), False)
                lap("detect")
            ctl.stage("characters")
            ccip = _vision.CCIP(ctl)
            crops = []
            for r, img in mids():
                if img is None or r["twin"] is not None:
                    continue
                # Персонажи — по главной фигуре; вторая — если не меньше 60 % первой
                # (CCIP ~0,4 с на фигуру на CPU).
                boxes = sorted(r["person"], key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))[:2]
                if len(boxes) == 2 and ((boxes[1][2] - boxes[1][0]) * (boxes[1][3] - boxes[1][1])
                                        < 0.6 * (boxes[0][2] - boxes[0][0]) * (boxes[0][3] - boxes[0][1])):
                    boxes = boxes[:1]
                if not boxes:                     # без фигуры — голова с плечами
                    boxes = [(max(0, b[0] - 0.4 * (b[2] - b[0])), b[1],
                              min(W, b[2] + 0.4 * (b[2] - b[0])), min(H, b[3] + 1.2 * (b[3] - b[1])), b[4])
                             for b in sorted(r["head"], key=lambda b: -(b[3] - b[1]))[:2]]
                for b in boxes:
                    x0, y0, x1, y1 = (int(v) for v in b[:4])
                    if y1 - y0 >= 48 and x1 - x0 >= 24:
                        crops.append((r["idx"], [x0, y0, x1, y1], img[y0:y1, x0:x1]))
            feats = ccip.features([c for _i, _b, c in crops]) if crops else np.zeros((0, 768), np.float32)
            del ccip
            own = collections.defaultdict(list)
            for k, (i, b, _c) in enumerate(crops):
                own[i].append((b, k))
            for r in rows:                        # близнецу — фигуры его образца
                if r["twin"] is not None:
                    for b, k in own.get(rows[r["twin"]]["idx"], []):
                        crops.append((r["idx"], b, None))
                        feats = np.concatenate([feats, feats[k:k + 1]])
            lap("ccip")
            if not gpu:
                ocr_shots()
            if tags_lane.is_alive() and len(to_tag) - taken[0] > 8:
                ctl.stage("tags", model=tagger_kind, helper="cpu")
                tag_shots(tags_lane.quit, worker=False)
                lap("tags_cpu")
        except BaseException:
            tags_lane.quit.set()
            tags_lane.join()
            raise
        timing["tags"] = tags_lane.result()
        lap("tags_wait")
        for r in rows:
            if r["twin"] is not None:
                src = rows[r["twin"]]
                for k in ("general", "chars", "rating", "text", "has_text", "hardsub"):
                    if k in src:
                        r[k] = src[k]
        timing["twins"] = sum(1 for r in rows if r["twin"] is not None)
        ctl.stage("speech")
        speech = _speech(path, [(r["t0"], r["t1"]) for r in rows])
        lap("speech")
        # Запись — одной транзакцией.
        old = con.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        with con:
            if old:
                _drop_file(con, old["id"])
            cur = con.execute(
                "INSERT INTO files(path,size,mtime,hash,duration,fps,width,height,frames,version,"
                "indexed_at,timing) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (path, st.st_size, st.st_mtime, fhash, fp.duration, fps, fp.w, fp.h, len(tn),
                 INDEX_VERSION, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(timing)))
            fid = cur.lastrowid
            ids = {}
            for r, sp in zip(rows, speech):
                cur = con.execute(
                    "INSERT INTO shots(file_id,idx,kind,f0,f1,t0,t1,motion,motion_peak,camera,object,"
                    "dup_ratio,static,brightness,saturation,colors,accents,faces,heads,persons,scale,"
                    "face_frac,rating,text,has_text,hardsub,speech,oped,keyframes,description,gemini)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fid, r["idx"], r["kind"], r["f0"], r["f1"], r["t0"], r["t1"], r["motion"],
                     r["motion_peak"], r["camera"], r["object"], r["dup_ratio"], int(r["static"]),
                     r["brightness"], r["saturation"], json.dumps(r.get("colors", [])),
                     json.dumps(r["accents"]), len(r.get("face", [])), len(r.get("head", [])),
                     len(r.get("person", [])), r.get("scale", "none"), round(r.get("face_frac", 0.0), 3),
                     r.get("rating", ""), r.get("text", ""), int(r.get("has_text", False)),
                     int(r.get("hardsub", False)), sp, r["oped"], json.dumps(r["keyframes"]), "", ""))
                ids[r["idx"]] = cur.lastrowid
                tags = [(ids[r["idx"]], t, s, 0) for t, s in r.get("general", {}).items()]
                tags += [(ids[r["idx"]], t, s, 4) for t, s in r.get("chars", {}).items()]
                con.executemany("INSERT INTO shot_tags(shot_id,tag,score,cat) VALUES(?,?,?,?)", tags)
            con.executemany("INSERT INTO crops(shot_id,box,feat,char_id) VALUES(?,?,?,NULL)",
                            [(ids[i], json.dumps(b), feats[k].astype(np.float16).tobytes())
                             for k, (i, b, _c) in enumerate(crops)])
            con.execute("INSERT OR REPLACE INTO prints(file_id,data) VALUES(?,?)", (fid, fpr.tobytes()))
        return {"path": path, "status": "indexed", "file_id": fid, "shots": len(rows),
                "transitions": sum(1 for r in rows if r["kind"] == "transition"),
                "flashes": len(flashes), "crops": len(crops), "timing": timing}
    finally:
        _api.shutil.rmtree(tmp, ignore_errors=True)


def _drop_file(con, fid):
    con.execute("DELETE FROM shot_tags WHERE shot_id IN (SELECT id FROM shots WHERE file_id=?)", (fid,))
    con.execute("DELETE FROM crops WHERE shot_id IN (SELECT id FROM shots WHERE file_id=?)", (fid,))
    con.execute("DELETE FROM shots WHERE file_id=?", (fid,))
    con.execute("DELETE FROM prints WHERE file_id=?", (fid,))
    con.execute("DELETE FROM oped WHERE file_id=? OR other=?", (fid, fid))
    con.execute("DELETE FROM speech_lines WHERE file_id=?", (fid,))
    con.execute("DELETE FROM files WHERE id=?", (fid,))


# ── Персонажи ────────────────────────────────────────────────────────────────
CHAR_LINK = 0.15                       # средняя разница CCIP внутри кластера
CHAR_MIN = 3                           # меньше фигур — не персонаж
CHAR_GROUP_MAX = 10000                 # фигур на одну кластеризацию: пары — 0,4 ГБ и копия у scipy


def _char_labels(ccip, feats, ctl):
    """Кластеры фигур одной группы: средняя связь (UPGMA) по разнице CCIP с
    порогом CHAR_LINK. DBSCAN из ccip_cluster.json сцеплял всё: на кадрах
    серии у фигуры сотни соседей ближе eps, и цепочка собирала 98 % фигур
    библиотеки (и Zipang с Арсланом) в одного «персонажа»; средняя связь
    цепочек не строит. Метки 0…; мелкие кластеры — -1."""
    from scipy.cluster.hierarchy import fcluster, linkage
    n = len(feats)
    if n < CHAR_MIN:
        return np.full(n, -1, int)
    cond = np.empty(n * (n - 1) // 2, np.float64)    # пары i<j построчно, как у scipy
    step = 1024
    for i in range(0, n, step):
        ctl.check()
        a = feats[i:i + step]
        rows = np.full((len(a), n), np.inf, np.float32)
        for j in range(i, n, step):
            b = feats[j:j + step]
            rows[:, j:j + len(b)] = ccip.differences(a) if j == i else ccip.differences(a, b)
        for k in range(len(a)):
            r = i + k
            start = r * n - r * (r + 1) // 2
            cond[start:start + n - r - 1] = rows[k, r + 1:]
    labels = fcluster(linkage(cond, "average"), CHAR_LINK, criterion="distance") - 1
    sizes = np.bincount(labels)
    keep = {lab: k for k, lab in enumerate(np.flatnonzero(sizes >= CHAR_MIN))}
    return np.array([keep.get(lab, -1) for lab in labels], int)


def recluster_characters(con, ctl=None):
    """Кластеры CCIP по фигурам библиотеки — отдельно для каждой папки
    (серии одного тайтла): между тайтлами персонажи не сливаются, а пар
    не n² на всю библиотеку. Имя старого кластера переходит к новому, где
    оказалось большинство его фигур."""
    ctl = ctl or _api.NO_CONTROL
    rows = con.execute("SELECT k.id, k.feat, k.char_id, f.path FROM crops k "
                       "JOIN shots s ON s.id=k.shot_id JOIN files f ON f.id=s.file_id "
                       "WHERE COALESCE(s.oped,'')='' ORDER BY f.path, k.id").fetchall()
    if not rows:
        return 0
    ctl.stage("characters", crops=len(rows))
    feats = np.stack([np.frombuffer(r["feat"], np.float16).astype(np.float32) for r in rows])
    ccip = _vision.CCIP(ctl)
    groups = collections.defaultdict(list)
    for k, r in enumerate(rows):
        groups[_api.os.path.dirname(r["path"])].append(k)
    labels = np.full(len(rows), -1, int)
    base = 0
    for idx in groups.values():
        for p in range(0, len(idx), CHAR_GROUP_MAX):          # очень длинная папка — частями
            part = np.array(idx[p:p + CHAR_GROUP_MAX])
            lab = _char_labels(ccip, feats[part], ctl)
            labels[part[lab >= 0]] = lab[lab >= 0] + base
            base += int(lab.max()) + 1 if (lab >= 0).any() else 0
    del ccip
    names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM characters")}
    votes_of = collections.defaultdict(collections.Counter)
    for r, l_ in zip(rows, labels):
        if l_ >= 0 and r["char_id"] is not None:
            votes_of[int(l_)][r["char_id"]] += 1
    sizes = collections.Counter(int(l_) for l_ in labels if l_ >= 0)
    new_ids, taken = {}, set()
    for lab, _n in sizes.most_common():
        pick = next((o for o, _n in votes_of[lab].most_common() if o not in taken), None)
        new_ids[lab] = pick
        if pick is not None:
            taken.add(pick)
    next_id = max([0] + list(names) + [v for v in new_ids.values() if v is not None]) + 1
    for lab in new_ids:
        if new_ids[lab] is None:
            new_ids[lab] = next_id
            next_id += 1
    with con:
        con.execute("DELETE FROM characters")
        for lab, cid in new_ids.items():
            con.execute("INSERT INTO characters(id,name,size) VALUES(?,?,?)",
                        (cid, names.get(cid) or "", sizes[lab]))
        con.execute("UPDATE crops SET char_id=NULL")       # фигуры опенингов — без персонажа
        con.executemany("UPDATE crops SET char_id=? WHERE id=?",
                        [(new_ids.get(int(l_)) if l_ >= 0 else None, r["id"])
                         for r, l_ in zip(rows, labels)])
    return len(new_ids)


def rename_character(con, cid, name):
    with con:
        n = con.execute("UPDATE characters SET name=? WHERE id=?", (str(name)[:80], int(cid))).rowcount
    if not n:
        raise _api.ToolError("usage", f"нет персонажа {cid}")


# ── Опенинг и эндинг ─────────────────────────────────────────────────────────
def _popcount(x):
    return np.unpackbits(x.view(np.uint8).reshape(-1, 4), axis=1).sum(axis=1)


def match_runs(a, b, min_s=OPED_MIN_S):
    """Общие куски отпечатков a и b длиннее min_s: [(a0, a1, b0, b1)] в
    секундах. Сдвиги — голосованием точных совпадений, кусок — где разница
    битов (среднее по ~2 с) меньше 10 из 32."""
    if len(a) < 50 or len(b) < 50:
        return []
    pos = collections.defaultdict(list)
    for j, v in enumerate(b.tolist()):
        if v and len(pos[v]) < 8:
            pos[v].append(j)
    votes = collections.Counter()
    for i, v in enumerate(a.tolist()):
        for j in pos.get(v, ()):
            votes[j - i] += 1
    need = int(min_s / FP_ITEM_S)
    out = []
    for off, cnt in votes.most_common(6):
        if cnt < 30:
            break
        i0, i1 = max(0, -off), min(len(a), len(b) - off)
        if i1 - i0 < need:
            continue
        err = _popcount(a[i0:i1] ^ b[i0 + off:i1 + off]).astype(np.float32)
        good = _an._moving_mean(err, 16) < 10.0
        for s, e in _an._runs(good, need, max_gap=8):
            ta0, ta1 = (i0 + s) * FP_ITEM_S, (i0 + e) * FP_ITEM_S
            if not any(abs(ta0 - x[0]) < 5 for x in out):
                out.append((round(ta0, 2), round(ta1, 2), round(ta0 + off * FP_ITEM_S, 2),
                            round(ta1 + off * FP_ITEM_S, 2)))
    return out


def detect_oped(con, ctl=None, file_ids=None):
    """Повторы звука ≥ 60 с между файлами → таблица oped и метка планов
    (op — в первой половине файла, ed — во второй)."""
    ctl = ctl or _api.NO_CONTROL
    prints = {r["file_id"]: np.frombuffer(r["data"], "<u4") for r in
              con.execute("SELECT file_id, data FROM prints")}
    dur = {r["id"]: r["duration"] for r in con.execute("SELECT id, duration FROM files")}
    todo = sorted(file_ids or prints)
    ctl.stage("oped", files=len(prints))
    found = collections.defaultdict(list)
    done = set()
    for fa in todo:
        for fb in prints:
            if fa == fb or (fb, fa) in done:
                continue
            done.add((fa, fb))
            for a0, a1, b0, b1 in match_runs(prints[fa], prints[fb]):
                found[fa].append((a0, a1, fb))
                found[fb].append((b0, b1, fa))
    with con:
        for fid in set(found) | set(todo):
            con.execute("DELETE FROM oped WHERE file_id=?", (fid,))
            con.execute("UPDATE shots SET oped='' WHERE file_id=?", (fid,))
            for t0, t1, other in found.get(fid, []):
                kind = "op" if (t0 + t1) / 2 < 0.5 * (dur.get(fid) or 1) else "ed"
                con.execute("INSERT INTO oped(file_id,t0,t1,kind,other) VALUES(?,?,?,?,?)",
                            (fid, t0, t1, kind, other))
                con.execute("UPDATE shots SET oped=? WHERE file_id=? AND "
                            "MIN(t1, ?) - MAX(t0, ?) > 0.5 * (t1 - t0)", (kind, fid, t1, t0))
    return {fid: [(a, b) for a, b, _o in v] for fid, v in found.items()}


# ── Описания сцен (Gemini, необязательно) ────────────────────────────────────
_SCENES_SCHEMA = {
    "type": "object",
    "properties": {"scenes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "MM:SS"},
            "end": {"type": "string", "description": "MM:SS"},
            "description": {"type": "string"},
            "characters": {"type": "array", "items": {"type": "string"}},
            "emotion": {"type": "string"},
            "action": {"type": "string"}},
        "required": ["start", "end", "description"]}}},
    "required": ["scenes"]}
_SCENES_PROMPT = (
    "This is an anime episode. List all its scenes in order, without gaps, from 00:00 to "
    "the end. For each scene give start and end as MM:SS (use the timestamps of the video), "
    "a one- or two-sentence English description (who, where, what happens, notable visuals), "
    "the characters on screen (names if you know them, otherwise a short description), the "
    "dominant emotion (one English word) and the main action (a few English words). "
    "Mark the opening and ending songs as scenes with description 'opening' or 'ending'.")


def _mmss(text):
    parts = str(text).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def describe_scenes(con, file_id, ctl=None, model="", client=None):
    """Сцены файла по видео — один запрос Gemini (ключ пользователя, учёт
    QuotaBoard в клиенте): прокси 360p 1 кадр/с с моно-звуком → File API →
    часть video с processing static fps 1 и resolution low (~100 токенов на
    секунду) → сцены по JSON-схеме → описание каждому плану по наибольшему
    перекрытию (shots.description, полный ответ сцены — shots.gemini)."""
    import gemini_api
    import gemini_files
    ctl = ctl or _api.NO_CONTROL
    f = con.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    if f is None:
        raise _api.ToolError("usage", f"нет файла {file_id}")
    key = _api.gemini_key()
    if not key and client is None:
        raise _api.ToolError("gemini_no_key", "нет ключа Gemini (GEMINI_API_KEY или настройки)")
    tmp = _api.tempfile.mkdtemp(prefix="sihyx_scenes_")
    name = ""
    try:
        proxy = _api.os.path.join(tmp, "proxy.mp4")
        ctl.stage("gemini", what="proxy", path=f["path"])
        rgb = _api.hdr_tonemap.tonemap_filter(f["path"], _api.escape_filter_path)
        vf = "fps=1,scale=-2:360" + ("," + rgb if rgb else "")
        _an._run_bytes([_api.FFMPEG, "-v", "error", "-nostdin", "-y", "-i", f["path"], "-map", "0:v:0",
                        "-map", "0:a:0?", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "32", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k", "-ac", "1",
                        "-movflags", "+faststart", proxy], timeout=3600)
        ctl.stage("gemini", what="upload", size=_api.os.path.getsize(proxy))
        try:
            info = gemini_files.upload_file(key, proxy, "video/mp4", stopped=ctl.stop)
            name = info["name"]
            gemini_files.wait_active(key, name, stopped=ctl.stop)
        except gemini_api.GeminiError as e:
            raise _api.ToolError("gemini_failed", str(e)) from e
        ctl.stage("gemini", what="scenes", model=model or gemini_api.DEFAULT_MODEL)
        client = client or gemini_api.GeminiClient(key, model=model or gemini_api.DEFAULT_MODEL,
                                                   stopped=ctl.stop)
        parts = [{"type": "video", "uri": info["uri"], "mime_type": "video/mp4",
                  "processing": {"type": "static", "fps": 1}, "resolution": "low"},
                 {"type": "text", "text": _SCENES_PROMPT}]
        try:
            ans = client.generate_json(parts, _SCENES_SCHEMA)
        except Exception as e:           # GeminiError и сеть — ответом JSON
            n_ = type(e).__name__
            raise _api.ToolError("gemini_quota" if "Quota" in n_ else "gemini_failed",
                                 f"{n_}: {e}") from e
    finally:
        if name:
            gemini_files.delete_file(key, name)
        _api.shutil.rmtree(tmp, ignore_errors=True)
    scenes = []
    for sc in (ans or {}).get("scenes", []):
        if not isinstance(sc, dict):
            continue
        a, b = _mmss(sc.get("start")), _mmss(sc.get("end"))
        if a is None or b is None or b <= a:
            continue
        scenes.append(dict(sc, t0=a, t1=b))
    if not scenes:
        raise _api.ToolError("gemini_failed", "Gemini не вернул сцен")
    rows = con.execute("SELECT id, t0, t1 FROM shots WHERE file_id=?", (file_id,)).fetchall()
    with con:
        for r in rows:
            best = max(scenes, key=lambda s: min(r["t1"], s["t1"]) - max(r["t0"], s["t0"]))
            if min(r["t1"], best["t1"]) - max(r["t0"], best["t0"]) <= 0:
                continue
            extra = "; ".join(x for x in (best.get("emotion"), best.get("action")) if x)
            desc = best["description"] + (f" [{extra}]" if extra else "")
            if best.get("characters"):
                desc += " — " + ", ".join(map(str, best["characters"]))
            con.execute("UPDATE shots SET description=?, gemini=? WHERE id=?",
                        (desc[:1000], json.dumps(best, ensure_ascii=False), r["id"]))
    return len(scenes)


# ── Подписи планов локальной моделью ─────────────────────────────────────────
# Средняя миниатюра плана (320 px, ~110 токенов подсказки у Qwen3.5-2B):
# замер на Vega 7 — ~3 с на план с текстом на видеокарте (gpu_layers 99:
# подсказка с картинкой считается быстрее, чем на процессоре); лента из трёх
# кадров — 4–6 с, подписи не лучше. Подпись — одна фраза по-английски (как
# теги WD), её находит search --query словами, без картинок.
CAPTION_PROMPT = ("One anime frame. In one English sentence of at most 20 words say who is "
                  "shown (look, clothes), what they do and where, and the mood. No names.")
CAPTION_TOKENS = 48
CAPTION_GPU_LAYERS = 99
# Слоты сервера (-np): несколько ответов за шаг генерации. Замер на Vega 7:
# серия Арслана одна на iGPU — 2,3 с на план при -np 1, 2,05 с при 4 (упор
# не в генерацию, а в картинку и подсказку: подпись в 12 слов вместо 20 —
# лишь −13 %, текст на CPU — вдвое медленнее). Рядом с разметкой на
# DirectML план подписывался 17 с — поэтому подписи идут после разметки
# файла, а не одновременно с разметкой следующего.
CAPTION_PARALLEL = 4


def caption_shots(con, file_ids, ctl=None, gpu_layers=CAPTION_GPU_LAYERS, limit=None,
                  parallel=CAPTION_PARALLEL, gpu=True):
    """Подписи планов (shots.caption) без подписи у файлов file_ids: один
    запуск llama-server на все, parallel вопросов одновременно. Опенинг и
    эндинг не подписываются — их не ищут. {captions: {file_id: число},
    время на план}."""
    from concurrent.futures import ThreadPoolExecutor
    from si_hyx_parts.montage_tool import vision_local as _vl
    ctl = ctl or _api.NO_CONTROL
    todo = []
    for fid in file_ids:
        todo += con.execute("SELECT id, file_id, keyframes FROM shots WHERE file_id=? AND "
                            "kind='shot' AND COALESCE(caption,'')='' AND COALESCE(oped,'')='' "
                            "ORDER BY idx", (fid,)).fetchall()
    if limit is not None:
        todo = todo[:int(limit)]
    if not todo:
        return {"captions": {}, "seconds_per_shot": None}
    done = collections.Counter()
    t0 = time.monotonic()
    with _vl.LlamaServer(_vl.DEFAULT_LOOK_MODEL, gpu_layers, ctl, parallel=parallel, gpu=gpu) as srv:
        t_load = time.monotonic()

        def one(r):
            keys = [k for k in json.loads(r["keyframes"] or "[]") if _api.os.path.isfile(k)]
            if not keys:
                return r, ""
            url = _vl._image_url(keys[len(keys) // 2])
            text = _vl.answer_text(srv.ask(_vl.chat_body([url], CAPTION_PROMPT,
                                                         max_tokens=CAPTION_TOKENS)))
            return r, " ".join(text.split())[:300]

        # Ответы — потоками, запись — здесь (соединение SQLite одного потока).
        pool = ThreadPoolExecutor(max(1, int(parallel)))
        try:
            for k, (r, text) in enumerate(pool.map(one, todo)):
                ctl.check()
                if k % 25 == 0:
                    ctl.stage("captions", shot=k + 1, total=len(todo))
                if text:
                    with con:
                        con.execute("UPDATE shots SET caption=? WHERE id=?", (text, r["id"]))
                    done[r["file_id"]] += 1
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    n = sum(done.values())
    return {"captions": {str(k): v for k, v in done.items()}, "load_s": round(t_load - t0, 1),
            "seconds_per_shot": round((time.monotonic() - t_load) / max(1, n), 2)}


# ── Индекс ───────────────────────────────────────────────────────────────────
def index_library(target, db=None, ctl=None, force=False, tagger="vit", gemini=False,
                  gemini_model="", speech=None, captions=False,
                  caption_gpu_layers=CAPTION_GPU_LAYERS, gpu=True, recluster=True):
    """Индекс файла или папки; новые и изменённые файлы — заново. gemini —
    ещё и описания сцен (describe_scenes) у файлов, где их нет; speech —
    {model, language, python}: реплики (dialogue.transcribe_file) у файлов,
    где их нет; captions — подписи планов локальной моделью (caption_shots)
    у планов без подписи. gpu=False — без iGPU (ни DirectML, ни Vulkan
    подписей): она же рисует экран, и её не уступить приоритетом процесса —
    команда модели держит её по 0,6 с, и всё окно дёргается.
    recluster=False — без пересчёта персонажей (очередь «Разметки AMV»
    пересчитывает их один раз в конце: characters --recluster)."""
    if not gpu:
        caption_gpu_layers = 0
    ctl = ctl or _api.NO_CONTROL
    if tagger not in _vision.TAGGERS:
        raise _api.ToolError("usage", f"теггер: {', '.join(_vision.TAGGERS)}")
    files = list_media(target)
    if not files:
        raise _api.ToolError("missing_files", f"нет видео в {target}")
    _low_priority()
    con = connect(db)
    results, changed = [], []
    from chiptune.gate import model_slot
    from chiptune.notes import QualityError
    try:
        for k, path in enumerate(files):
            ctl.check()
            st = _api.os.stat(path)
            row = con.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()
            if (row and not force and row["size"] == st.st_size and abs(row["mtime"] - st.st_mtime) < 1e-3
                    and row["version"] == INDEX_VERSION):
                results.append({"path": path, "status": "unchanged", "file_id": row["id"]})
                continue
            fhash = file_hash(path, st.st_size)
            moved = con.execute("SELECT * FROM files WHERE hash=? AND version=? AND path<>?",
                                (fhash, INDEX_VERSION, path)).fetchone()
            if moved and not force and not _api.os.path.exists(moved["path"]):
                with con:
                    con.execute("UPDATE files SET path=?, mtime=? WHERE id=?",
                                (path, st.st_mtime, moved["id"]))
                results.append({"path": path, "status": "moved", "file_id": moved["id"],
                                "from": moved["path"]})
                continue
            ctl.stage("file", index=k + 1, total=len(files), path=path)
            timing = {}
            t = time.monotonic()
            with model_slot(ctl.stop):
                res = _index_file(con, path, st, fhash, ctl, tagger, timing, gpu)
            res["seconds"] = round(time.monotonic() - t, 1)
            results.append(res)
            changed.append(res["file_id"])
        out = {"db": _api.os.path.abspath(str(db or default_db())), "files": results}
        if gemini:
            out["gemini"] = {}
            for res in results:
                fid = res.get("file_id")
                if fid is None or con.execute("SELECT 1 FROM shots WHERE file_id=? AND "
                                              "COALESCE(description,'')<>'' LIMIT 1",
                                              (fid,)).fetchone():
                    continue
                try:
                    out["gemini"][str(fid)] = {"scenes": describe_scenes(con, fid, ctl, gemini_model)}
                except _api.ToolError as e:   # без ключа и квоты — каталог без описаний
                    if e.code == "cancelled":
                        raise
                    out["gemini"][str(fid)] = {"error": e.code, "message": e.message}
        if speech is not None:
            out["speech"] = {}
            for res in results:
                fid = res.get("file_id")
                if fid is None:
                    continue
                if con.execute("SELECT 1 FROM speech_lines WHERE file_id=? LIMIT 1",
                               (fid,)).fetchone():
                    continue
                try:
                    with model_slot(ctl.stop):
                        out["speech"][str(fid)] = {"lines": _api.transcribe_file(
                            con, fid, res["path"], ctl, **speech)}
                except _api.ToolError as e:  # нет обработчика — каталог без реплик
                    if e.code == "cancelled":
                        raise
                    out["speech"][str(fid)] = {"error": e.code, "message": e.message}
        if changed:                          # до подписей: опенинги и эндинги не подписываются
            out["oped"] = {str(k): v for k, v in detect_oped(con, ctl, changed).items()}
        if captions:
            ids = [res["file_id"] for res in results if res.get("file_id") is not None]
            try:
                out["captions"] = caption_shots(con, ids, ctl, caption_gpu_layers, gpu=gpu)
            except _api.ToolError as e:      # нет модели или сервер не поднялся — без подписей
                if e.code == "cancelled":
                    raise
                out["captions"] = {"error": e.code, "message": e.message}
        if changed and recluster:
            with model_slot(ctl.stop):
                out["characters"] = recluster_characters(con, ctl)
        out["totals"] = library_stats(con)
        return out
    except QualityError as e:
        raise _api.ToolError("cancelled", "отменено файлом отмены") from e
    finally:
        con.close()


def library_stats(con):
    one = con.execute("SELECT COUNT(*) n, COALESCE(SUM(duration),0) d FROM files").fetchone()
    return {"files": one["n"], "hours": round(one["d"] / 3600, 2),
            "shots": con.execute("SELECT COUNT(*) FROM shots").fetchone()[0],
            "characters": con.execute("SELECT COUNT(*) FROM characters").fetchone()[0]}


# ── Поиск ────────────────────────────────────────────────────────────────────
def _tag_name(t):
    return str(t).strip().lower().replace(" ", "_")


def _shot_dict(con, r, tags, chars, files):
    f = files[r["file_id"]]
    return {"id": r["id"], "file": f["path"], "file_id": r["file_id"], "index": r["idx"],
            "kind": r["kind"], "t0": r["t0"], "t1": r["t1"], "length": round(r["t1"] - r["t0"], 3),
            "frames": r["f1"] - r["f0"] + 1, "fps": f["fps"],
            "scale": r["scale"], "motion": r["motion"], "motion_peak": r["motion_peak"],
            "camera": r["camera"], "object": r["object"], "dup_ratio": r["dup_ratio"],
            "static": bool(r["static"]), "brightness": r["brightness"],
            "saturation": r["saturation"], "colors": json.loads(r["colors"] or "[]"),
            "accents": json.loads(r["accents"] or "[]"), "faces": r["faces"],
            "persons": r["persons"], "characters": chars,
            "tags": [t for t, _s, c in tags if c == 0][:12],
            "character_tags": [t for t, _s, c in tags if c == 4],
            "rating": r["rating"], "text": r["text"], "hardsub": bool(r["hardsub"]),
            "speech": r["speech"], "oped": r["oped"],
            "keyframes": json.loads(r["keyframes"] or "[]"), "description": r["description"],
            "caption": r["caption"]}


def search(db=None, tags_all=(), tags_any=(), tags_none=(), character="", motion_min=None,
           motion_max=None, min_len=None, max_len=None, bright_min=None, bright_max=None,
           scale=(), no_text=False, include_oped=False, include_transitions=False, file="",
           query="", static=None, limit=50, ids=()):
    """Планы по фильтрам и запросу (rapidfuzz по тегам, тексту, описанию и
    подписи)."""
    con = connect(db)
    try:
        files = {r["id"]: r for r in con.execute("SELECT id, path, fps FROM files")}
        where, args = [], []
        if ids:
            where.append(f"s.id IN ({','.join('?' * len(ids))})")
            args += [int(i) for i in ids]
        if not include_transitions and not ids:
            where.append("s.kind='shot'")
        if not include_oped and not ids:
            where.append("COALESCE(s.oped,'')=''")
        for col, lo, hi in (("s.motion", motion_min, motion_max), ("(s.t1-s.t0)", min_len, max_len),
                            ("s.brightness", bright_min, bright_max)):
            if lo is not None:
                where.append(f"{col} >= ?")
                args.append(float(lo))
            if hi is not None:
                where.append(f"{col} <= ?")
                args.append(float(hi))
        if scale:
            where.append(f"s.scale IN ({','.join('?' * len(scale))})")
            args += list(scale)
        if no_text:
            where.append("s.has_text=0 AND s.hardsub=0")
        if static is not None:
            where.append("s.static=?")
            args.append(int(bool(static)))
        if file:
            where.append("s.file_id IN (SELECT id FROM files WHERE LOWER(path) LIKE ?)")
            args.append("%" + str(file).lower() + "%")
        for t in tags_all:
            where.append("EXISTS (SELECT 1 FROM shot_tags g WHERE g.shot_id=s.id AND g.tag=?)")
            args.append(_tag_name(t))
        if tags_any:
            where.append(f"EXISTS (SELECT 1 FROM shot_tags g WHERE g.shot_id=s.id AND g.tag IN "
                         f"({','.join('?' * len(tags_any))}))")
            args += [_tag_name(t) for t in tags_any]
        for t in tags_none:
            where.append("NOT EXISTS (SELECT 1 FROM shot_tags g WHERE g.shot_id=s.id AND g.tag=?)")
            args.append(_tag_name(t))
        if character:
            c = str(character).strip()
            if c.isdigit():
                where.append("EXISTS (SELECT 1 FROM crops k WHERE k.shot_id=s.id AND k.char_id=?)")
                args.append(int(c))
            else:
                where.append("(EXISTS (SELECT 1 FROM crops k JOIN characters h ON h.id=k.char_id "
                             "WHERE k.shot_id=s.id AND LOWER(h.name)=?) OR EXISTS (SELECT 1 FROM "
                             "shot_tags g WHERE g.shot_id=s.id AND g.cat=4 AND g.tag LIKE ?))")
                args += [c.lower(), "%" + _tag_name(c) + "%"]
        sql = "SELECT s.* FROM shots s" + (" WHERE " + " AND ".join(where) if where else "")
        rows = con.execute(sql + " ORDER BY s.file_id, s.idx", args).fetchall()
        tag_rows = collections.defaultdict(list)
        char_rows = collections.defaultdict(list)
        if rows:
            idl = [r["id"] for r in rows]
            for i in range(0, len(idl), 900):
                part = idl[i:i + 900]
                q = ",".join("?" * len(part))
                for g in con.execute(f"SELECT shot_id, tag, score, cat FROM shot_tags WHERE shot_id IN "
                                     f"({q}) ORDER BY score DESC", part):
                    tag_rows[g["shot_id"]].append((g["tag"], g["score"], g["cat"]))
                for k in con.execute(f"SELECT k.shot_id, k.char_id, h.name FROM crops k LEFT JOIN "
                                     f"characters h ON h.id=k.char_id WHERE k.shot_id IN ({q}) AND "
                                     f"k.char_id IS NOT NULL", part):
                    item = {"id": k["char_id"], "name": k["name"] or ""}
                    if item not in char_rows[k["shot_id"]]:
                        char_rows[k["shot_id"]].append(item)
        out = [_shot_dict(con, r, tag_rows[r["id"]], char_rows[r["id"]], files) for r in rows]
        if query.strip():
            # Каждое слово запроса — лучшее совпадение среди слов тегов (все,
            # а не 12 показанных), надписей и описания (smiling ≈ smile, girl ≈
            # 1girl); оценка — среднее по словам.
            from rapidfuzz import fuzz
            words = [w for w in query.lower().replace("_", " ").split() if len(w) > 1]
            for s in out:
                doc = [t for t, _sc, _c in tag_rows[s["id"]]] + [s["text"] or "",
                                                                  s["description"] or "",
                                                                  s["caption"] or ""]
                toks = set(" ".join(doc).replace("_", " ").replace(",", " ").lower().split())
                best = [max((fuzz.ratio(w, t) for t in toks), default=0.0) / 100.0
                        for w in words]
                s["score"] = round(sum(best) / len(best), 3) if best else 0.0
            out = [s for s in out if s["score"] >= 0.75]
            out.sort(key=lambda s: (-s["score"], -s["length"]))
        total = len(out)
        return {"db": _api.os.path.abspath(str(db or default_db())), "total": total,
                "shots": out[:max(1, int(limit))]}
    finally:
        con.close()


def shot_sheet(found, out_png, tile_width=320, columns=0):
    """Лист найденных планов: средний ключевой кадр, под ним id, время и
    длина, крупность и движение."""
    shots = [s for s in found if s.get("keyframes")]
    if not shots:
        raise _api.ToolError("nothing_to_render", "у найденных планов нет миниатюр")
    shots = shots[:_api.SHEET_MAX]
    images = [s["keyframes"][len(s["keyframes"]) // 2] for s in shots]
    name_len = max(6, int(tile_width) // 8 - 22)      # подпись не шире плитки
    labels = [f"#{s['id']}  {s['t0']:.2f}–{s['t1']:.2f} с ({s['length']:.2f})\n"
              f"{_api.os.path.basename(s['file'])[:name_len]} · {s['scale']} · дв {s['motion']:.2f}"
              for s in shots]
    cols, rows = _api.draw_sheet(images, labels, out_png, tile_width, columns)
    return {"output": _api.os.path.abspath(str(out_png)), "columns": cols, "rows": rows,
            "shots": [s["id"] for s in shots]}
