# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InfoWorker. Public namespace: workers."""
import workers as _api
from .download_network import is_network_error, network_hint
from .download_process import stop_process


class InfoWorker(_api.QThread):
    # duration, thumbnail, доступные языки субтитров, доступные языки аудиодорожек
    success = _api.pyqtSignal(int, str, list, list)
    error = _api.pyqtSignal(str)

    def __init__(self, url, proxy=""):
        super().__init__()
        self.url = url
        self.proxy = (proxy or "").strip()
        self.cancelled = False
        self._proc = None

    def cancel(self):
        self.cancelled = True
        stop_process(self._proc)

    @staticmethod
    def _parse_sub_langs(raw: str) -> list:
        """Языки РУЧНЫХ субтитров из JSON-поля subtitles (%(subtitles)j).
        Автосубтитры (automatic_captions) намеренно не берём — у YouTube там
        сотни авто-переводов, которые засорили бы список."""
        try:
            data = _api.json.loads(raw)
            if isinstance(data, dict):
                return sorted(k for k in data.keys() if k and k != "live_chat")
        except Exception:
            pass
        return []

    @staticmethod
    def _parse_audio_langs(raw: str) -> list:
        """Различные языки аудиодорожек из JSON-поля formats. Берём форматы с
        аудио (acodec != none) и непустым language."""
        try:
            formats = _api.json.loads(raw)
            if not isinstance(formats, list):
                return []
            langs = []
            for f in formats:
                if not isinstance(f, dict):
                    continue
                if (f.get("acodec") or "none") == "none":
                    continue
                lang = f.get("language")
                if lang and lang not in ("none", "NA") and lang not in langs:
                    langs.append(lang)
            return sorted(langs)
        except Exception:
            return []

    def run(self):
        base = _api.ytdlp_base_cmd()
        if not base:
            self.error.emit("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")
            return
        try:
            cmd = base + [
                "--encoding", "utf-8",
                "--no-playlist", "--no-warnings", "--skip-download",
                "--socket-timeout", "15", "--no-check-certificate",
                "--extractor-retries", "2", "--retry-sleep", "1",
                # Каждая строка с префиксом-маркером — парсим по нему, не по позиции
                # (JSON-строки могут быть длинными). subtitles/formats нужны, чтобы
                # заполнить списки «Суб.»/«Язык» реально доступными дорожками.
                "--print", "@@DT@@%(duration)s\t%(thumbnail)s",
                "--print", "@@SB@@%(subtitles)j",
                "--print", "@@FM@@%(formats)j",
            ]
            c_path = _api.get_cookies_path(self.url)
            if _api.os.path.exists(c_path):
                cmd += ["--cookies", c_path]
            if self.proxy:
                cmd += ["--proxy", self.proxy]
            if _api.host_matches(self.url, 'youtube.com', 'youtu.be'):
                cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]
            if _api.host_matches(self.url, 'bilibili.com', 'b23.tv'):
                cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", _api.USER_AGENT]
            cmd += [self.url]

            # TikTok отдаёт challenge-страницу без данных в ~50-80% запусков
            # («rehydration» ЛИБО «Unexpected response»), НЕЗАВИСИМО от UA/cookies;
            # сбой не-retryable внутри yt-dlp, но НОВЫЙ процесс снова имеет шанс —
            # перезапускаем процесс до 12 раз (только TikTok). Иначе превью/метаданные
            # так же мигали бы ошибкой.
            is_tt = _api.host_matches(self.url, 'tiktok.com')
            max_tries = 12 if is_tt else 2
            duration, thumb = 0, ""
            sub_langs, audio_langs = [], []
            for attempt in range(max_tries):
                if self.cancelled: return
                self._proc = _api.subprocess.Popen(
                    cmd, stdout=_api.subprocess.PIPE, stderr=_api.subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=_api.CREATE_NO_WINDOW, env=_api.subprocess_env())
                if self.cancelled:
                    stop_process(self._proc)
                    self._proc.communicate(timeout=5)
                    return
                try:
                    out, err = self._proc.communicate(timeout=60)
                except _api.subprocess.TimeoutExpired:
                    stop_process(self._proc)
                    out, err = self._proc.communicate(timeout=5)
                    err = "Таймаут запроса информации (60 сек.).\n" + (err or "")
                if self.cancelled: return

                for line in (out or "").splitlines():
                    if line.startswith("@@DT@@"):
                        payload = line[len("@@DT@@"):]
                        d, _, t = payload.partition("\t")
                        try: duration = int(float(d)) if d and d != "NA" else 0
                        except Exception: duration = 0
                        thumb = "" if t.strip() in ("", "NA") else t.strip()
                    elif line.startswith("@@SB@@"):
                        sub_langs = self._parse_sub_langs(line[len("@@SB@@"):])
                    elif line.startswith("@@FM@@"):
                        audio_langs = self._parse_audio_langs(line[len("@@FM@@"):])
                if duration or thumb or sub_langs or audio_langs:
                    break
                # Пусто. Повторяем на ЛЮБОЙ флапающей ошибке извлечения TikTok
                # (rehydration / universal data / unexpected response).
                low = (err or "").lower()
                flaky_tiktok = is_tt and any(token in low for token in (
                    "rehydration", "universal data", "unexpected response"))
                if not (attempt + 1 < max_tries
                        and (flaky_tiktok or is_network_error(err))):
                    break
                for _ in range(20):
                    if self.cancelled: return
                    _api.time.sleep(0.1)

            if duration or thumb or sub_langs or audio_langs:
                self.success.emit(duration, thumb, sub_langs, audio_langs)
            else:
                detail = (err or "").strip()[-1500:]
                message = "Не удалось извлечь информацию."
                if detail:
                    message += "\n" + detail
                if is_network_error(detail):
                    message += "\n" + network_hint()
                self.error.emit(message)
        except _api.subprocess.TimeoutExpired:
            stop_process(self._proc)
            if not self.cancelled:
                self.error.emit("Таймаут запроса информации. " + network_hint())
        except Exception as e:
            if not self.cancelled:
                self.error.emit(str(e))

InfoWorker.__module__ = _api.__name__
_api.InfoWorker = InfoWorker
