# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _fmt_eta. Public namespace: workers."""
import workers as _api


def _fmt_eta(self, fraction, start):
    """Строка ETA по доле выполнения (0..1) и времени старта."""
    fraction = min(1.0, max(0.0, fraction))
    elapsed = _api.time.time() - start
    if fraction >= 1.0:
        return "00:00:00"
    if elapsed < 1.0 or fraction <= 0.0:
        return "..."
    rem = max(0, elapsed * (1.0 / fraction - 1.0))
    rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
    return f"{rh:02}:{rm:02}:{rs:02}"

def _fmt_eta_rate(self, fraction, anchor_t, anchor_frac):
    """ETA по скорости в ОКНЕ [anchor_t, anchor_frac] → сейчас. В отличие от
        _fmt_eta, не привязана к общему старту: при двухпроходном кодировании
        Pass 1 (анализ) проходит почти мгновенно и доводит долю до ~50% за
        секунды; линейная оценка от старта принимала бы это за «всё быстро» и
        затем во время медленного Pass 2 ETA постоянно росла. Переякоривая окно
        на начало текущего прохода, оцениваем остаток по реальной скорости
        именно этого прохода. При anchor_frac=0 и anchor_t=start идентична
        _fmt_eta (обратная совместимость для однопроходных задач)."""
    fraction = min(1.0, max(0.0, fraction))
    if fraction >= 1.0:
        return "00:00:00"
    dt = _api.time.time() - anchor_t
    df = fraction - anchor_frac
    if dt < 1.0 or df <= 1e-6:
        return "..."
    rem = max(0, (1.0 - fraction) * dt / df)
    rh = int(rem // 3600); rm = int((rem % 3600) // 60); rs = int(rem % 60)
    return f"{rh:02}:{rm:02}:{rs:02}"

def _guess_out_path(self, item, path):
    """Восстанавливает путь к выходному файлу (для кнопки «Открыть»).

        Страховка на случай, если process_media не вернула путь: основной путь —
        её собственный (см. _process_one)."""
    try:
        sv2 = self.settings.get('video', {})
        sa2 = self.settings.get('audio', {})
        crf2 = sv2.get('crf', 35); spd2 = sv2.get('speed', 100)
        ve2 = sv2.get('enabled', True)
        base2, ext2 = _api.os.path.splitext(path)
        out_dir2 = self._out_dir_for(path)
        vcodec2 = _api.get_video_codec(path)
        # Аудио-режим Монтажа гасит видео так же, как в process_media —
        # иначе угадка ждала бы .mp4 там, где на диске .opus.
        is_vid2 = (vcodec2 is not None) and not bool(item.get('audio_only'))
        out_ext2 = ".mp4" if is_vid2 else ".opus"
        sfx2 = ""
        if is_vid2 and ve2: sfx2 += f"_crf{crf2}_speed{spd2}"
        if sa2.get('norm'): sfx2 += "_norm"
        if sa2.get('fade'): sfx2 += "_fade"
        out_name2 = self._sanitize_name(_api.os.path.basename(base2))
        guessed = _api.os.path.join(out_dir2, out_name2 + sfx2 + out_ext2)
        if _api.os.path.exists(guessed): item['out_path'] = guessed
    except Exception: pass

def _overwrite_source_if_needed(self, item, out_path):
    """Если включено «Перезаписывать исходник» — удаляет оригинальный файл,
        оставляя только сжатую версию. При совпадении путей (тот же формат)
        файл уже перезаписан на месте — удалять нечего."""
    av = self.settings.get('avif', {})
    if not av.get('overwrite_src'):
        return
    src = item.get('path')
    if not (out_path and src):
        return
    try:
        if (_api.os.path.exists(out_path) and _api.os.path.exists(src)
                and _api.os.path.abspath(out_path) != _api.os.path.abspath(src)):
            _api.os.remove(src)
            self.log.emit(f"Исходник удалён (перезапись): {_api.os.path.basename(src)}")
    except Exception as e:
        self.log.emit(f"Не удалось удалить исходник: {e}")

def _total_now(self) -> int:
    """Текущее известное число файлов: уже завершённые + ещё не
        завершённые в очереди. self.queue — живой список MediaTab.items,
        поэтому файлы, доброшенные во время обработки, автоматически
        увеличивают знаменатель прогресса."""
    with self._prog_lock:
        done = self._done_count
    pending = sum(1 for it in list(self.queue) if not it.get('is_done', False))
    return max(1, done + pending)

def _process_item(self, item, smooth, start, weight=1):
    """Обрабатывает один элемент очереди.
        smooth=True — глобальный прогресс плавно отражает прогресс файла
        (видео/аудио идут по одному). smooth=False — прогресс по факту
        завершения (изображения идут параллельно через QThreadPool).
        weight — вклад в счётчик «занятых потоков ЦП»: видео = все ядра
        (один ffmpeg/SVT-AV1 грузит весь ЦП), изображение = 1."""
    if self.stop_flag:
        return
    iid = item['iid']; path = item['path']
    self.status.emit(iid, "Обработка.", "proc")
    self._inc_active(weight)
    max_frac_seen = [0.0]
    last_label = [None]
    # Окно для ETA по скорости текущего прохода: [время, доля]. По умолчанию
    # совпадает с общим стартом (тогда оценка идентична старой _fmt_eta), но
    # при смене прохода (Pass 1 → Pass 2) переякоривается на текущий момент,
    # чтобы быстрый Pass 1 не занижал оценку и ETA во время Pass 2 не «росла».
    eta_anchor = [start, 0.0]

    def item_prog(pct, pass_label=None, eta_sec=None):
        try:
            if not smooth:
                # Параллельная обработка изображений: НЕ шлём частые % -сигналы
                # из множества потоков, но статус («Конвертация картинки N/X»)
                # обновляем при смене подписи — это редкое событие (раз в проход),
                # потоки/сигналы Qt безопасны.
                if pass_label and pass_label != last_label[0]:
                    last_label[0] = pass_label
                    self.status.emit(iid, pass_label, "proc")
                return
            if pass_label and "Pass 1" in pass_label:
                display_pct = int(pct * 0.5)
            elif pass_label and "Pass 2" in pass_label:
                display_pct = int(50 + pct * 0.5)
            else:
                display_pct = pct
            self.progress.emit(iid, display_pct)
            label_changed = bool(pass_label) and pass_label != last_label[0]
            if label_changed and pct < 100:
                last_label[0] = pass_label
                self.status.emit(iid, pass_label, "proc")
            with self._prog_lock:
                base = self._done_count
            fraction = (base + display_pct / 100.0) / self._total_now()
            fraction = max(min(1.0, fraction), max_frac_seen[0])
            max_frac_seen[0] = fraction
            # Новый проход → переякориваем окно ETA на «здесь и сейчас».
            if label_changed:
                eta_anchor[0] = _api.time.time()
                eta_anchor[1] = fraction
            gl_pct = int(min(100, fraction * 100))
            label = pass_label if pass_label else "Processing"
            # Если активный шаг дал реальное ETA (адаптивный калькулятор по
            # кадрам/сложности) — показываем его; иначе старая оценка по доле
            # глобального прогресса (для шагов без покадрового парсинга).
            if eta_sec is not None:
                eta_str = _api.RealETACalculator.fmt(eta_sec)
            else:
                eta_str = self._fmt_eta_rate(fraction, eta_anchor[0], eta_anchor[1])
            self.global_progress.emit(gl_pct, f"{label} ETA: {eta_str}")
        except Exception:
            pass

    try:
        out_path = None
        if item.get('type') == 'IMG':
            out_path = self.process_avif(item, item_prog)
            self._overwrite_source_if_needed(item, out_path)
        else:
            # Путь берём У САМОЙ process_media (она его и собрала), а не
            # угадываем по настройкам: угадывание не знало ни про аудио-режим
            # («(Аудио) Перекодировать настройками «Обработки»» даёт .opus, а
            # угадка ждала .mp4 с crf-суффиксом), ни про смену контейнера под
            # альфу (.webm). Промах = пустой out_path, и Монтаж честно
            # ругался «Обработка не создала результат», хотя файл лежал рядом.
            out_path = self.process_media(item, item_prog)
        item['is_done'] = True
        if out_path:
            item['out_path'] = out_path
        else:
            self._guess_out_path(item, path)
        self.status.emit(iid, "Готово", "done")
        self.progress.emit(iid, 100)
    except Exception as e:
        tb = str(e)
        if "StoppedByUser" in tb:
            self.log.emit(f"Остановка {_api.os.path.basename(path)} выполнена.")
            self.status.emit(iid, "Остановлено", "err")
        else:
            self.log.emit(f"Ошибка {_api.os.path.basename(path)}: {tb}")
            self.status.emit(iid, "Ошибка", "err")
        item['is_done'] = True
    finally:
        self._dec_active(weight)
        with self._prog_lock:
            self._done_count += 1
            done = self._done_count
        total = self._total_now()
        frac = done / total
        self.global_progress.emit(int(min(100, frac * 100)),
                                  f"Готово {done}/{total} ETA: {self._fmt_eta(frac, start)}")

def run(self):
    start = _api.time.time()
    self._done_count = 0
    self._prog_lock = _api.threading.Lock()
    self._processed_ids = set()   # iid'ы, уже отправленные в работу за этот запуск
    self._logged_cpu_msg = False

    cpu = max(1, _api.cpu_thread_count())

    # Обрабатываем очередь по схеме «продюсер-потребитель»: постоянно
    # заглядываем в живой список self.queue, поэтому файлы, доброшенные во
    # время обработки, тут же уходят в работу. Картинки кодируются параллельно
    # в ОБЩЕМ пуле (cpu потоков) и НЕ блокируют диспетчеризацию через
    # waitForDone — доброшенные картинки сразу занимают свободные потоки
    # (просьба пользователя), не дожидаясь конца текущей пачки.
    while not self.stop_flag:
        pending = [it for it in list(self.queue)
                   if not it.get('is_done', False)
                   and it.get('iid') not in self._processed_ids]
        images = [it for it in pending if it.get('type') == 'IMG']
        others = [it for it in pending if it.get('type') != 'IMG']

        # Видео/аудио идут по одному файлу, но кодировщик SVT-AV1 сам нагружает
        # ВСЕ логические ядра ЦП → счётчик показывает занятые потоки ЦП. Перед
        # видео дожидаемся ранее запущенных картинок, иначе они дрались бы за ЦП.
        if others:
            if (self._img_pool is not None
                    and self._img_pool.activeThreadCount() > 0):
                self._img_pool.waitForDone()
            self._max_threads = cpu
            if not self._logged_cpu_msg:
                self.log.emit("Кодирование видео/аудио: SVT-AV1.")
                self._logged_cpu_msg = True
            for it in others:
                if self.stop_flag:
                    break
                self._processed_ids.add(it.get('iid'))
                self._process_item(it, True, start, weight=cpu)
            continue

        if images:
            # Одиночный кадр CPU не насыщает → шлём картинки в общий пул на cpu
            # потоков. Знаменатель счётчика — всегда ВСЕ логические потоки ЦП
            # машины (cpu), чтобы «занято/всего» не скакало по ходу обработки.
            if self._img_pool is None:
                self._img_pool = _api.QThreadPool()
                self._img_pool.setMaxThreadCount(cpu)
                if cpu > 1:
                    self.log.emit(
                        f"Параллельная обработка изображений: до {cpu} потоков")
            self._max_threads = cpu
            for itm in images:
                if self.stop_flag:
                    break
                self._processed_ids.add(itm.get('iid'))
                self._img_pool.start(_api._ImgRunnable(self, itm, start))
            # НЕ ждём waitForDone — короткая пауза, чтобы подхватить доброшенные
            # файлы и занять ими свободные потоки, не крутя цикл вхолостую.
            _api.time.sleep(0.08)
            continue

        # Новых задач нет. Если картинки ещё кодируются — ждём и снова
        # перечитываем очередь (вдруг доросли новые); иначе очередь пуста.
        if (self._img_pool is not None
                and self._img_pool.activeThreadCount() > 0):
            _api.time.sleep(0.1)
            continue
        break

    if self._img_pool is not None:
        self._img_pool.waitForDone()

    self.active_threads.emit(0, 0)
    self.finished_all.emit()
    self.global_progress.emit(100, "Готово")
