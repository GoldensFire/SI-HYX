# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpWorker: _find_recent_output. Public namespace: workers."""
import workers as _api


def _find_recent_output(self, out_dir):
    """Фолбэк, когда yt-dlp не напечатал итоговый путь. Берём ТОЛЬКО
        медиафайл, изменённый в ходе ЭТОГО задания (mtime ≥ старта задания, не
        отдельной попытки — иначе файл с ранней попытки «пропадает» при повторах),
        чтобы не подхватить чужой файл из папки (напр. .siq)."""
    try:
        floor = getattr(self, "_job_start_ts", None)
        if floor is None:
            floor = getattr(self, "_dl_start_ts", 0)
        floor -= 2
        cands = [
            _api.os.path.join(out_dir, fn) for fn in _api.os.listdir(out_dir)
            if _api.os.path.isfile(_api.os.path.join(out_dir, fn))
            and fn.lower().endswith(self._MEDIA_EXTS)
            and _api.os.path.getmtime(_api.os.path.join(out_dir, fn)) >= floor
        ]
        if cands:
            return max(cands, key=_api.os.path.getmtime)
    except Exception:
        pass
    return ""

def _emit_hints(self, err_msg):
    low = err_msg.lower()
    if ("10054" in err_msg or "connection aborted" in low
            or "connection reset" in low or "connectionreseterror" in low):
        self.log_sig.emit("СОВЕТ: Соединение принудительно разорвано (10054). Обычно это "
                          "блокировка/замедление YouTube провайдером.")
        self.log_sig.emit("  Попробуйте: включить VPN, либо повторить позже. Ретраи уже "
                          "увеличены, но против DPI-блокировки помогает только VPN/прокси.")
        return
    if "Sign in to confirm" in err_msg or "not a bot" in err_msg:
        self.log_sig.emit("СОВЕТ: YouTube требует «не бот» — куки без данных входа.")
        self.log_sig.emit("  Экспортируйте куки залогиненного YouTube (нужны LOGIN_INFO, __Secure-1PSID, SID, SAPISID).")

# Добавить ПЕРЕД блоком: elif "Forbidden" in err_msg or "403" in err_msg:
    elif ("tiktok" in low and (
            "status code 0" in low or
            "failed to parse json" in low or
            "video not available" in low)):
        self.log_sig.emit(
            "СОВЕТ (TikTok status 0 / JSONDecodeError): сервер TikTok оборвал соединение "
            "до отправки ответа — это TLS-fingerprint или rate-limit блокировка."
        )
        self.log_sig.emit(
            "  Варианты решения:\n"
            "  1) Обновите cookies_tiktok.txt — авторизованные куки снижают агрессивность "
            "rate-limit (нужны sessionid, tt_csrf_token, ttwid).\n"
            "  2) Включите VPN/прокси — смена IP часто снимает бан по rate-limit.\n"
            "  3) Обновите yt-dlp: pip install -U yt-dlp  (экстрактор TikTok меняется часто)."
        )

    elif ("tiktok" in low and ("unexpected response" in low
                               or "rehydration" in low or "universal data" in low)):
        self.log_sig.emit(
            "СОВЕТ: TikTok временно ограничил запросы (anti-bot/throttling) — это НЕ "
            "ошибка программы, а защита сайта после частых обращений.")
        self.log_sig.emit(
            "  Подождите 2–5 минут и повторите — после паузы обычно качается с "
            "1–2 попытки. Ускорить помогает VPN/смена IP. Долбить подряд не нужно: "
            "это только продлевает ограничение.")
    elif "Forbidden" in err_msg or "403" in err_msg:
        u = self.c.get("url", "")
        if _api.host_matches(u, "tiktok.com"):
            self.log_sig.emit("СОВЕТ: 403 на TikTok. Удалите/переименуйте cookies_tiktok.txt.")
        elif _api.host_matches(u, "fbcdn.net", "instagram.com", "cdninstagram.com"):
            self.log_sig.emit("СОВЕТ: 403 на Instagram CDN. Ссылка устарела — откройте видео заново.")
        else:
            self.log_sig.emit("СОВЕТ: 403 Forbidden. Возможно, нужны куки или ссылка устарела.")
    elif "412" in err_msg or "Precondition Failed" in err_msg:
        u = self.c.get("url", "")
        if _api.host_matches(u, "bilibili.com", "b23.tv"):
            self.log_sig.emit("СОВЕТ: 412 на BiliBili — их анти-бот (риск-контроль) режет playurl для гостей.")
            self.log_sig.emit("  Нужны cookies залогиненного аккаунта (SESSDATA). Войдите на bilibili.com в браузере, "
                              "экспортируйте cookies.txt и укажите его в поле «Cookies» (или положите cookies_bilibili.txt в папку настроек).")
        else:
            self.log_sig.emit("СОВЕТ: 412 Precondition Failed — сайт отклонил запрос. Часто помогают cookies залогиненного аккаунта.")
