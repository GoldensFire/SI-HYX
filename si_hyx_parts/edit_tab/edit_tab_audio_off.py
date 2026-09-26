# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: пункт «Нет» в списке аудиодорожек — звук выключен.

В превью плеер отцепляется от вывода звука (скраб-звук тоже молчит), а
при экспорте в команды ffmpeg добавляется -an: результат без звука.
Public namespace: edit_tab."""
import edit_tab as _api

AUDIO_OFF_LABEL = "Нет"


def _audio_is_off(self) -> bool:
    return bool(getattr(self, "audio_disabled", False))


def _set_audio_disabled(self, on: bool) -> None:
    """Включает/выключает звук превью по пункту «Нет»."""
    on = bool(on)
    if _audio_is_off(self) == on:
        return
    self.audio_disabled = on
    try:
        self.player.setAudioOutput(None if on else self.audio_output)
    except Exception:
        pass


def _add_audio_off_entry(self) -> None:
    """Пункт «Нет» в конце списка дорожек (если звук у файла вообще есть)."""
    if not self._audio_entries:
        return
    self.cmb_audio.addItem(_api.get_icon('fa5s.volume-mute'), AUDIO_OFF_LABEL)
    self._audio_entries.append(('none', None))


def _external_audio_insert_at(self) -> int:
    """Куда вставить новый файл озвучки: перед пунктом «Нет»."""
    for i, (kind, _ref) in enumerate(self._audio_entries):
        if kind == 'none':
            return i
    return len(self._audio_entries)


def drop_audio(cmd: list, out: str) -> list:
    """Команда ffmpeg без звука на выходе: -an прямо перед путём вывода."""
    if cmd and cmd[-1] == out and "-an" not in cmd:
        cmd = cmd[:-1] + ["-an", out]
    return cmd
