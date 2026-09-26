# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _ensure_ext_audio_player. Public namespace: edit_tab."""
import edit_tab as _api


def _ensure_ext_audio_player(self):
    if self._ext_audio_player is None:
        self._ext_audio_player = _api.QMediaPlayer()
        self._ext_audio_output = _api.QAudioOutput()
        self._ext_audio_player.setAudioOutput(self._ext_audio_output)
        self._ext_audio_player.mediaStatusChanged.connect(
            self._on_ext_audio_status)
    return self._ext_audio_player

def _set_external_audio(self, path):
    if not path or not _api.os.path.exists(path):
        return
    p = self._ensure_ext_audio_player()
    try:
        self.audio_output.setMuted(True)   # глушим звук видео
    except Exception:
        pass
    try:
        self._ext_audio_output.setVolume(self.vol_slider.value() / 100.0)
    except Exception:
        pass
    self._ext_audio_active = True
    p.setSource(_api.QUrl.fromLocalFile(str(path)))

    # Точную синхронизацию делаем по событию загрузки (_on_ext_audio_status).

def _on_ext_audio_status(self, status):
    if not self._ext_audio_active or self._ext_audio_player is None:
        return
    if status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                  _api.QMediaPlayer.MediaStatus.BufferedMedia):
        try:
            self._ext_audio_player.setPosition(self.player.position())
            if (self.player.playbackState()
                    == _api.QMediaPlayer.PlaybackState.PlayingState):
                self._ext_audio_player.play()
            else:
                self._ext_audio_player.pause()
        except Exception:
            pass

def _ext_audio_seek(self, ms):
    if self._ext_audio_active and self._ext_audio_player is not None:
        try:
            self._ext_audio_player.setPosition(int(max(0, ms)))
        except Exception:
            pass

def _ext_audio_set_state(self, playing):
    if not self._ext_audio_active or self._ext_audio_player is None:
        return
    try:
        self._ext_audio_player.setPosition(self.player.position())
        if playing:
            self._ext_audio_player.play()
        else:
            self._ext_audio_player.pause()
    except Exception:
        pass

def _clear_external_audio(self):
    if not getattr(self, "_ext_audio_active", False):
        return
    self._ext_audio_active = False
    p = self._ext_audio_player
    if p is not None:
        try: p.pause()
        except Exception: pass
        try: p.setSource(_api.QUrl())
        except Exception: pass
    try:
        self.audio_output.setMuted(False)
    except Exception:
        pass
