# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# tools/bench_video_path.py — измеряет цену РАЗНЫХ способов вывести кадр на
# экран. Нужен, чтобы про «Монтаж тормозит» говорили цифрами, а не на глаз:
# запускается ДО правки и ПОСЛЕ, и сравниваются две таблицы.
#
# Зачем вообще отдельный стенд. Главная метрика тут не «сколько всего ЦП съел
# процесс», а СКОЛЬКО ВРЕМЕНИ ЗАНЯТ GUI-ПОТОК: пока он конвертирует кадр,
# он не обрабатывает мышь, не двигает плейхед и не перерисовывает волну —
# именно это пользователь и называет «лагает». Поэтому меряется отдельно
# время GUI-потока (time.thread_time) и всего процесса (time.process_time).
#
# Что меряется (по одному режиму на запуск — иначе режимы мешают друг другу,
# поэтому «прогнать все» запускает этот же файл подпроцессами):
#
#   canvas             — текущий путь «Монтажа»: QVideoSink → frame.toImage()
#                        → QPainter.drawImage, всё в GUI-потоке (VideoCanvas).
#   canvas_thr         — то же, но QVideoSink живёт в рабочем потоке: toImage
#                        уходит с GUI-потока, на отрисовку приезжает готовый
#                        QImage.
#   canvas_thr_scaled  — то же плюс уменьшение кадра до ширины виджета ТАМ ЖЕ,
#                        в рабочем потоке (на GUI едет маленькая картинка).
#   vwidget            — QVideoWidget: кадр не ходит через ЦП вовсе. Быстро,
#                        НО поверх него не рисуются дочерние виджеты-оверлеи
#                        (видео композитится последним) — как эталон скорости
#                        полезен, как готовое решение для «Монтажа» — нет.
#   qml                — QQuickWidget + QML VideoOutput: столь же дёшево, и
#                        оверлеи (субтитры, рамка кропа, накладки) живут в той
#                        же сцене, поэтому рисуются поверх кадра корректно.
#   montage            — НАСТОЯЩИЙ холст вкладки (edit_tab_widgets.VideoCanvas)
#                        со всей его обвязкой: свой QVideoSink между плеером и
#                        сценой (пин кадра, граница OUT, часы кадра) и слой
#                        оверлеев. Это и есть «как стало» — режимы выше меряют
#                        голые способы вывода, а этот — то, что реально работает
#                        во вкладке. «Нарисовано» тут считается по кадрам сцены
#                        Quick (afterRendering), а не по paintEvent'ам виджета.
#
# Использование:
#   python tools/bench_video_path.py video.mp4                  # все режимы
#   python tools/bench_video_path.py video.mp4 --mode qml       # один режим
#   python tools/bench_video_path.py video.mp4 --seconds 12     # дольше мерить
#
# Окно на время замера открывается настоящее (без окна Qt не создаёт
# графический конвейер, и цифры получаются не те).
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

MODES = ("canvas", "canvas_thr", "canvas_thr_scaled", "vwidget", "qml", "montage")

# Прогрев: первые секунды после старта плеера уходят на открытие файла и
# раскрутку декодера — в измерение они попадать не должны.
WARMUP_S = 2.5

# Размер окна замера. Фиксирован намеренно: цена drawImage зависит от размера
# приёмника, и «до/после» обязаны мериться на одной геометрии.
WIN_W, WIN_H = 1100, 640


# ─────────────────────────────────────────────────────────────────────────────
# Дочерний процесс: один режим, результат — JSON в файл
# ─────────────────────────────────────────────────────────────────────────────
def _run_one(mode, src, seconds, out_path):
    """Меряет один режим и кладёт результат JSON-ом в out_path.

    Результат пишется в ФАЙЛ, а не в stdout: ffmpeg-бэкенд QtMultimedia сыплет
    в консоль баннер и предупреждения декодера, и разобрать stdout надёжно не
    выходит."""
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from PyQt6.QtCore import (Qt, QThread, QObject, QTimer, QUrl, pyqtSignal)
    from PyQt6.QtGui import QColor, QImage, QPainter
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    stats = {"delivered": 0, "painted": 0, "conv": [], "paint": []}

    class Canvas(QWidget):
        """Приёмник кадра-картинки — как VideoCanvas, только без всего лишнего."""

        def __init__(self):
            super().__init__()
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            self.img = None

        def set_img(self, img):
            self.img = img
            self.update()

        def paintEvent(self, ev):
            t0 = time.perf_counter()
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#1e1e2e"))
            if self.img is not None and not self.img.isNull():
                # Без сглаживания — ровно как VideoCanvas во время
                # воспроизведения (см. VideoCanvas.set_playing).
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                p.drawImage(self.rect(), self.img)
            p.end()
            stats["paint"].append((time.perf_counter() - t0) * 1000.0)
            stats["painted"] += 1

    class Converter(QObject):
        """frame.toImage() — то, что в текущем «Монтаже» делается в GUI-потоке."""

        ready = pyqtSignal(QImage)

        def __init__(self, target_w=0):
            super().__init__()
            self.target_w = int(target_w or 0)

        def on_frame(self, frame):
            stats["delivered"] += 1
            t0 = time.perf_counter()
            img = frame.toImage()
            if (self.target_w and img is not None and not img.isNull()
                    and img.width() > self.target_w):
                img = img.scaledToWidth(self.target_w,
                                        Qt.TransformationMode.FastTransformation)
            stats["conv"].append((time.perf_counter() - t0) * 1000.0)
            self.ready.emit(img)

    app = QApplication(sys.argv[:1])
    win = QWidget()
    win.setWindowTitle(f"bench_video_path — {mode}")
    win.resize(WIN_W, WIN_H)
    lay = QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)

    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setVolume(0.0)          # замер, а не прослушивание
    player.setAudioOutput(audio)
    keep = []                     # ссылки, чтобы объекты не собрал GC
    worker = None

    if mode.startswith("canvas"):
        canvas = Canvas()
        lay.addWidget(canvas)
        sink = QVideoSink()
        conv = Converter(WIN_W if mode.endswith("_scaled") else 0)
        if mode == "canvas":
            sink.videoFrameChanged.connect(conv.on_frame)
            conv.ready.connect(canvas.set_img)
        else:
            worker = QThread()
            sink.moveToThread(worker)
            conv.moveToThread(worker)
            sink.videoFrameChanged.connect(conv.on_frame)
            conv.ready.connect(canvas.set_img,
                               Qt.ConnectionType.QueuedConnection)
            worker.start()
        player.setVideoSink(sink)
        keep += [canvas, sink, conv]
    elif mode == "vwidget":
        from PyQt6.QtMultimediaWidgets import QVideoWidget
        vw = QVideoWidget()
        lay.addWidget(vw)
        player.setVideoOutput(vw)
        # Кадры считаем через тот же сток, что рисует виджет: сам он ничего
        # в ЦП не отдаёт, но пересчёт кадров нужен для сравнимости таблицы.
        vw.videoSink().videoFrameChanged.connect(
            lambda _f: stats.__setitem__("delivered", stats["delivered"] + 1))
        keep.append(vw)
    elif mode == "qml":
        from PyQt6.QtQuickWidgets import QQuickWidget
        qml_src = (
            "import QtQuick\n"
            "import QtMultimedia\n"
            "Item {\n"
            "    property alias sink: vo.videoSink\n"
            "    VideoOutput { id: vo; anchors.fill: parent;\n"
            "                  fillMode: VideoOutput.PreserveAspectFit }\n"
            "}\n")
        qml_file = os.path.join(tempfile.gettempdir(),
                                f"sihyx_bench_{os.getpid()}.qml")
        with open(qml_file, "w", encoding="utf-8") as fh:
            fh.write(qml_src)
        quick = QQuickWidget()
        quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick.setSource(QUrl.fromLocalFile(qml_file))
        lay.addWidget(quick)
        errors = [e.toString() for e in quick.errors()]
        root = quick.rootObject()
        sink = root.property("sink") if root is not None else None
        if sink is None:
            _write(out_path, {"mode": mode, "error":
                              "QML VideoOutput не поднялся: "
                              + ("; ".join(errors) or "нет rootObject")})
            return 1
        player.setVideoSink(sink)
        sink.videoFrameChanged.connect(
            lambda _f: stats.__setitem__("delivered", stats["delivered"] + 1))
        keep += [quick, sink]
    elif mode == "montage":
        # Импортируем поздно и внутри режима: модуль тянет за собой половину
        # приложения, и остальным режимам это ни к чему.
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import edit_tab_widgets
        canvas = edit_tab_widgets.VideoCanvas()
        lay.addWidget(canvas)
        player.setVideoSink(canvas.videoSink())
        canvas.videoSink().videoFrameChanged.connect(
            lambda _f: stats.__setitem__("delivered", stats["delivered"] + 1))
        quick = getattr(canvas, "_quick", None)
        qwin = quick.quickWindow() if quick is not None else None
        if qwin is not None:
            # Кадр сцены = кадр на экране. У ЦП-холста ту же роль играет
            # paintEvent, поэтому колонки таблицы сравнимы.
            qwin.afterRendering.connect(
                lambda: stats.__setitem__("painted", stats["painted"] + 1))
        keep.append(canvas)
    else:
        _write(out_path, {"mode": mode, "error": f"неизвестный режим {mode}"})
        return 2

    win.show()
    player.setSource(QUrl.fromLocalFile(os.path.abspath(src)))
    QTimer.singleShot(400, player.play)

    marks = {}

    def start_measure():
        marks["cpu"] = time.process_time()
        marks["gui"] = time.thread_time()
        marks["wall"] = time.perf_counter()
        stats["delivered"] = 0
        stats["painted"] = 0
        stats["conv"].clear()
        stats["paint"].clear()

    def finish():
        result = {"mode": mode}
        try:
            wall = time.perf_counter() - marks["wall"]
            result.update({
                "wall_s": round(wall, 2),
                "delivered_fps": round(stats["delivered"] / wall, 1),
                "painted_fps": round(stats["painted"] / wall, 1),
                "cpu_pct": round((time.process_time() - marks["cpu"]) / wall * 100, 1),
                "gui_pct": round((time.thread_time() - marks["gui"]) / wall * 100, 1),
                "conv_ms": (round(statistics.median(stats["conv"]), 2)
                            if stats["conv"] else None),
                "paint_ms": (round(statistics.median(stats["paint"]), 2)
                             if stats["paint"] else None),
            })
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        _write(out_path, result)
        # Дальше процесс не разбирается по-хорошему, а просто убивается, и это
        # намеренно: player.stop() при QVideoSink, живущем в рабочем потоке,
        # блокируется намертво (замер режимов canvas_thr* просто не завершался).
        # Цифры уже на диске, аккуратное закрытие стенду не нужно.
        os._exit(0)

    QTimer.singleShot(int(WARMUP_S * 1000), start_measure)
    QTimer.singleShot(int((WARMUP_S + seconds) * 1000), finish)
    app.exec()
    return 0


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# Родительский процесс: гоняет режимы по очереди и печатает таблицу
# ─────────────────────────────────────────────────────────────────────────────
def _spawn(mode, src, seconds):
    """Прогоняет режим отдельным процессом. Отдельным — потому что Qt держит
    выбранный графический конвейер на весь процесс: два режима в одном запуске
    мерили бы друг друга."""
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="sihyx_bench_")
    os.close(fd)
    cmd = [sys.executable, os.path.abspath(__file__), src,
           "--mode", mode, "--seconds", str(seconds), "--_out", out_path]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=seconds + 90, encoding="utf-8")
        with open(out_path, encoding="utf-8") as fh:
            return json.load(fh)
    except subprocess.TimeoutExpired:
        return {"mode": mode, "error": "таймаут"}
    except (OSError, ValueError) as exc:
        return {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _print_table(rows):
    head = (f"{'режим':<18} {'достав.':>8} {'нарис.':>8} {'ЦП всего':>9} "
            f"{'GUI-поток':>10} {'toImage':>9} {'paint':>8}")
    print()
    print(head)
    print("-" * len(head))
    for r in rows:
        if r.get("error"):
            print(f"{r['mode']:<18} ОШИБКА: {r['error']}")
            continue
        conv = f"{r['conv_ms']:.2f}" if r.get("conv_ms") is not None else "—"
        paint = f"{r['paint_ms']:.2f}" if r.get("paint_ms") is not None else "—"
        print(f"{r['mode']:<18} {r['delivered_fps']:>7.1f}  "
              f"{r['painted_fps']:>7.1f}  {r['cpu_pct']:>8.1f}% "
              f"{r['gui_pct']:>9.1f}% {conv:>8}  {paint:>7} ")
    print()
    print("достав./нарис. — кадров в секунду доставлено плеером / нарисовано на экране")
    print("ЦП всего — время процессора процессом, % от ОДНОГО ядра")
    print("GUI-поток — сколько времени занят главный поток; это и есть «лагает»")
    print("toImage/paint — медиана на кадр, мс (у GPU-путей кадр через ЦП не идёт)")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Замер цены разных способов вывести видеокадр на экран.")
    ap.add_argument("video", help="видеофайл для замера (лучше 1080p60)")
    ap.add_argument("--mode", choices=MODES, default=None,
                    help="один режим; без него прогоняются все по очереди")
    ap.add_argument("--seconds", type=float, default=8.0,
                    help="длительность замера после прогрева (по умолчанию 8)")
    ap.add_argument("--_out", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not os.path.exists(args.video):
        print(f"Файла нет: {args.video}")
        return 1

    if args._out:                       # запущены как дочерний процесс
        return _run_one(args.mode, args.video, args.seconds, args._out)

    modes = [args.mode] if args.mode else list(MODES)
    print(f"Файл: {args.video}")
    print(f"Окно: {WIN_W}x{WIN_H}, прогрев {WARMUP_S} с, замер {args.seconds} с "
          f"на режим ({len(modes)} шт.)")
    rows = []
    for mode in modes:
        print(f"  … {mode}", flush=True)
        rows.append(_spawn(mode, args.video, args.seconds))
    _print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
