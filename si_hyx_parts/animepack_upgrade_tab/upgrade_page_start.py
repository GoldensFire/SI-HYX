# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_UpgradePage: start. Public namespace: animepack_upgrade_tab."""
from __future__ import annotations
import animepack_upgrade_tab as _api


def start(self):
    if self._task is not None:
        return
    if not self._siq or not _api.os.path.isfile(self._siq):
        _api.msgbox_warning(self, "Нечего апгрейдить",
                       "Сначала выберите .siq — кнопкой «Выбрать .siq…» "
                       "или перетащив файл на вкладку.")
        return
    settings = self.collect()
    problems = settings.validate()
    if problems:
        _api.msgbox_warning(self, "Так не получится", "\n\n".join(problems))
        return

    if self.main is not None and hasattr(self.main, "clear_global_result"):
        self.main.clear_global_result()

    self.table.setRowCount(0)
    self._last_pack = ""
    self.btn_open.setEnabled(False)
    self.btn_start.setEnabled(False)
    self.btn_stop.setEnabled(True)
    self._started_at = _api.time.monotonic()
    self._progress(0, "Читаю пак…")
    self.log(f"Апгрейд «{_api.os.path.basename(self._siq)}»: "
             + ", ".join(self._what_for(settings)))

    task = _api._UpgradeTask(self._siq, settings)
    task.signals.log.connect(self.log)
    task.signals.progress.connect(self._on_progress)
    task.signals.finished.connect(self._on_finished)
    task.signals.failed.connect(self._on_failed)
    self._task = task
    self._pool.start(task)

@staticmethod
def _what_for(settings) -> list[str]:
    what = []
    if settings.strip_specials:
        what.append("убираю спецвопросы")
    if settings.add_titles:
        what.append(f"дописываю варианты названий "
                    f"({settings.source_name})")
    if settings.strip_repeated_text:
        what.append("убираю повторяющийся текст тем")
    if settings.merge_text_audio:
        what.append("включаю текст перед отрывком одновременно со звуком")
    if settings.drop_empty_questions:
        what.append("удаляю пустые вопросы")
    if settings.compress_images:
        what.append(f"сжимаю картинки тяжелее {settings.image_min_mb:g} МБ")
    if settings.compress_audio:
        what.append(f"перекодирую аудио тяжелее {settings.audio_min_mb:g} МБ"
                    f" в opus {settings.audio_kbps} кбит"
                    + (" с нормализацией" if settings.audio_norm else ""))
    if settings.compress_video:
        what.append(f"перекодирую видео тяжелее {settings.video_min_mb:g} МБ"
                    + (" (и всё не в AV1)" if settings.video_non_av1 else "")
                    + f" в av1 crf {settings.video_crf}")
    if settings.drop_unused:
        what.append("удаляю неиспользуемые файлы")
    return what or ["ничего не делаю"]

def stop(self):
    if self._task is not None:
        self._task.stop()
        self._progress(0, "Останавливаюсь…")
        self.btn_stop.setEnabled(False)

def _progress(self, pct: int, text: str) -> None:
    """Своей полосы у вкладки нет — пишем в общую, внизу окна."""
    if self.main is None or not hasattr(self.main, "update_global_progress"):
        return
    try:
        self.main.update_global_progress(max(0, min(100, int(pct))), text)
    except Exception:
        pass

def _on_progress(self, done: int, total: int, msg: str):
    total = max(1, total)
    self._progress(int(done * 100 / total), msg or f"{done}/{total}")

def _finish_ui(self):
    self._task = None
    self.btn_start.setEnabled(True)
    self.btn_stop.setEnabled(False)

def _on_failed(self, err: str):
    self._finish_ui()
    self._progress(0, "Не получилось")
    self.log(f"Ошибка: {err}")
    _api.msgbox_critical(self, "Апгрейд не удался", err)

def _on_finished(self, result):
    self._finish_ui()
    self._fill_table(result)
    if result.cancelled:
        self._progress(0, "Остановлено")
        self.log("Апгрейд остановлен, файл не записан — исходный пак цел.")
        return
    spent = _api.fmt_elapsed(getattr(result, "elapsed", 0.0))
    self._last_pack = result.path
    self.btn_open.setEnabled(bool(result.path))
    if self.main is not None and hasattr(self.main, "set_global_result"):
        self.main.set_global_result(result.path)
    self._progress(100, f"Готово за {spent}: "
                        f"{_api.os.path.basename(result.path)}")
    # Три примера с каждой функции — прямо в лог, следом за итогом.
    for line in _api.example_lines(result, limit=3):
        self.log(line)
    self.log(f"Пак сохранён за {spent}: {result.path}")
    if not result.total:
        _api.msgbox_information(
            self, "Менять было нечего",
            "Ни спецвопросов, ни опознанных названий аниме, ни тяжёлых "
            "картинок в паке не нашлось — постеры и написание названий "
            "тоже правились не по чему. Копия всё равно сохранена:\n\n"
            + result.path)
