# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: create_subtitles. Public namespace: edit_tab."""
import edit_tab as _api


def create_subtitles(self):
    """«Создать субтитры»: диалог с репликами (текст+тайминг) и позицией на
        экране. Если в Монтаже сейчас выбрана дорожка субтитров (cmb_subs) —
        сразу редактируем ЕЁ (без лишнего диалога-выбора — раньше он всплывал
        каждый раз и раздражал); если ничего не выбрано — начинаем с чистого
        листа. Результат — новый .ass, добавляется как внешняя дорожка (та же
        логика, что и для отредактированного файла в edit_subtitles)."""
    if not self.actual_source_file and not getattr(self, "is_still_image", False):
        _api.msgbox_information(self, "Субтитры", "Сначала откройте видео.")
        return
    # Пока пересобирается прокси (смена качества предпросмотра), self.filepath
    # на мгновение указывает на уже удалённый временный файл (см.
    # _on_pb_quality_changed) — второй плеер диалога открыл бы то, чего нет.
    if self.proxy_thread and self.proxy_thread.isRunning():
        _api.msgbox_information(self, "Субтитры",
                           "Дождитесь подготовки превью и повторите.")
        return
    cues_arg = None
    idx = self.cmb_subs.currentIndex()
    if 0 < idx <= len(self._sub_entries):
        kind, ref = self._sub_entries[idx - 1]
        if kind != 'more':
            srt = self._extract_srt_for_entry(kind, ref)
            cues_arg = _api._parse_srt(srt) if srt else None
            if not cues_arg:
                _api.msgbox_warning(
                    self, "Субтитры",
                    "Не удалось получить текст этой дорожки для "
                    "редактирования (возможно, это субтитры-картинки).")
                return
    # Диапазон — ровно та обрезка, что выделена в Монтаже (current_in/
    # current_out), а не всё видео целиком: превью/таймлайн диалога
    # показывают только его.
    range_start = self.current_in
    range_end = self.current_out if self.current_out > range_start else None
    start_hint = range_start
    try:
        pos = self._ui_time_s()
        if range_end is not None:
            start_hint = max(range_start, min(pos, range_end))
        else:
            start_hint = max(range_start, pos)
    except Exception:
        pass
    # self.filepath — РЕАЛЬНО проигрываемый файл (== actual_source_file, либо
    # H.264-прокси для AV1/пониженного качества, см. create_proxy_for_preview) —
    # тот же путь, что и в основном плеере Монтажа. Диалог держит СВОЙ, второй
    # независимый QMediaPlayer (см. _SubtitlePreview) — если скормить ему сырой
    # AV1-исходник напрямую, QtMultimedia молча не отдаёт ни одного кадра
    # (ровно то, ради чего в самом Монтаже и строится прокси).
    source_path = (self.filepath or self.actual_source_file
                   or getattr(self, "still_image_path", None))
    partial_proxy = bool(getattr(self, "is_proxy_active", False)
                         and getattr(self, "_proxy_partial", False))
    # Звук превью — та же дорожка, что выбрана в Монтаже (cmb_audio), а не
    # дефолтная первая дорожка файла (была жалоба на именно это).
    audio_track_index, audio_ext_path = None, None
    ext_path = getattr(self, "selected_audio_ext_path", None)
    if ext_path:
        audio_ext_path = ext_path
    else:
        aidx = self.cmb_audio.currentIndex()
        if 0 <= aidx < len(self._audio_entries):
            kind, ref = self._audio_entries[aidx]
            if kind == 'emb':
                audio_track_index = ref
    dlg = _api.SubtitleCreatorDialog(source_path=source_path, cues=cues_arg,
                                start_hint=start_hint,
                                range_start=range_start, range_end=range_end,
                                ignore_media_duration=partial_proxy,
                                default_style=getattr(self, '_last_subtitle_style', None),
                                audio_track_index=audio_track_index,
                                audio_ext_path=audio_ext_path,
                                parent=self)
    # Диалог декодирует ТОТ ЖЕ файл вторым, независимым QMediaPlayer — на
    # некоторых GPU аппаратный декодер (d3d11va/dxva2, см. video_hw_decode)
    # держит лимит одновременных сессий на кодек, и второй сеанс тогда
    # молча не получает ни одного видеокадра (аудио/позиция при этом
    # тикают нормально — подтверждено логом watchdog'а: NoError, позиция и
    # BufferedMedia в порядке, а кадра нет). stop() освобождает декодер
    # плеера Монтажа на время диалога, не трогая источник/дорожки —
    # позиция и воспроизведение восстанавливаются простым seek()'ом после.
    was_playing = self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
    resume_pos_ms = self.player.position()
    self.player.stop()
    try:
        result = dlg.exec()
    finally:
        try:
            self.player.setPosition(resume_pos_ms)
            if was_playing:
                self.player.play()
        except Exception:
            pass
    if result != _api.QDialog.DialogCode.Accepted:
        return
    # Запоминаем стиль (шрифт/размер/цвет/…), которым закончил работу
    # пользователь — следующее открытие «Создать субтитры» стартует с него
    # (см. default_style выше и save_settings/load_settings).
    try:
        self._last_subtitle_style = dlg.last_style()
        self.save_settings()
    except Exception:
        pass
    cues = dlg.cues()
    if not cues:
        return
    ass_text = _api._cues_to_ass(cues)
    try:
        _api.os.makedirs(_api.CONFIG_DIR, exist_ok=True)
        base = self.actual_source_file.stem if self.actual_source_file else "subs"
        path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_created.ass")
        n = 1
        while _api.os.path.exists(path) and _api.os.path.normpath(path) not in self._sub_ext:
            path = _api.os.path.join(_api.CONFIG_DIR, f"{base}_created_{n}.ass"); n += 1
        with open(path, 'w', encoding='utf-8') as f:
            f.write(ass_text)
    except Exception as e:
        _api.msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
        return
    self._add_external_sub(_api.os.path.normpath(path))

def _add_external_audio(self, path):
    target = ('ext', path)
    if path not in self._audio_ext:
        self._audio_ext.append(path)
        self._loading_tracks = True
        # Убираем плейсхолдер «— нет —», если до этого дорожек не было.
        if not self._audio_entries:
            self.cmb_audio.clear()
        # Новый файл встаёт перед пунктом «Нет».
        at = self._external_audio_insert_at()
        self._audio_entries.insert(at, target)
        self.cmb_audio.insertItem(at, _api.get_icon('fa5s.file'), _api.os.path.basename(path))
        if all(kind != 'none' for kind, _ref in self._audio_entries):
            self._add_audio_off_entry()
        self.cmb_audio.setEnabled(len(self._audio_entries) > 1)
        self._loading_tracks = False
    try:
        idx = self._audio_entries.index(target)
    except ValueError:
        return
    if self.cmb_audio.currentIndex() == idx:
        self.on_audio_track_changed(idx)
    else:
        self.cmb_audio.setCurrentIndex(idx)
