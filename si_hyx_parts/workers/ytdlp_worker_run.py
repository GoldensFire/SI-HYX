# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""YtdlpWorker: run. Public namespace: workers."""
import workers as _api
from .download_result import verified_download


def run(self):
    iid = self.c.get('iid', '')
    self._iid = iid
    # Старт ВСЕГО задания (а не отдельной попытки): по нему ищем итоговый файл,
    # чтобы найти его, даже если он скачался на ранней попытке, а @@PATH@@ не
    # пришёл (mtime-порог переживает повторы).
    self._job_start_ts = _api.time.time()
    self.progress_sig.emit(iid, 0.0, "Подготовка...")
    try:
        raw_url = self.c.get('url', '')

        # Прямые CDN-ссылки (Instagram fbcdn.net и др.) — по RAW URL, до clean_url
        if _api.is_direct_cdn_video(raw_url):
            out_dir = self.c.get('outdir', '.') or '.'
            self.log_sig.emit("Определена прямая CDN-ссылка, скачиваю без yt-dlp...")
            self.progress_sig.emit(iid, 1.0, "Загрузка CDN...")
            out_path = _api.download_cdn_direct(raw_url, out_dir, log_fn=self.log_sig.emit)
            self.progress_sig.emit(iid, 100.0, "Готово")
            self.finished_sig.emit(iid, "Готово", "", out_path)
            return

        base = _api.ytdlp_base_cmd()
        if not base:
            raise Exception("yt-dlp не найден. Положите yt-dlp.exe в папку bin рядом с программой.")

        url = _api.clean_url(raw_url)
        if url != raw_url: self.log_sig.emit(f"Ссылка очищена: {raw_url} -> {url}")

        out_dir = self.c.get('outdir', '.') or '.'
        is_audio_only = self.c.get('audio_only', False)
        merge = self.c.get('merge') or 'mp4'
        proxy = (self.c.get('proxy') or '').strip()

        # Встроенный плеер Kodik (animego и др. — yt-dlp их не поддерживает):
        # резолвим страницу в прямой m3u8 и качаем уже его.
        kodik = {}
        if not is_audio_only and _api.is_embed_candidate(url):
            want_h = self._height_from_fmt(self.c.get('fmt', ''))
            ep = self.c.get('kodik_episode')
            ep = int(ep) if ep else None
            tr = self.c.get('kodik_translation', '')
            # Резолв Kodik/animego бывает флапающим (AJAX-плеер или сам
            # Kodik временно не отвечает) — как и с TikTok, повтор почти
            # всегда лечит: до 3 попыток с короткой паузой перед сдачей.
            KODIK_MAX = 3
            for kodik_try in range(1, KODIK_MAX + 1):
                try:
                    kodik = _api.resolve_kodik(url, want_height=want_h, proxy=proxy,
                                          episode=ep, translation=tr,
                                          log_fn=self.log_sig.emit)
                except Exception as e:
                    self.log_sig.emit(f"Kodik resolve error: {e}")
                    kodik = {}
                if kodik or not self.is_running:
                    break
                if kodik_try < KODIK_MAX:
                    self.log_sig.emit(
                        f"Kodik: пустой ответ — повтор {kodik_try}/{KODIK_MAX}…")
                    self._sleep_interruptible(1.5)
        if kodik:
            self.log_sig.emit(f"Встроенный плеер Kodik → качаю {kodik['height']}p (m3u8)")
            url = kodik['url']
        elif _api.is_animego_site(url):
            # Аниме-сайт без полученного Kodik-плеера: yt-dlp его не качает.
            # Не имитируем «скачивание» (раньше падало в generic → Unsupported
            # URL), а сразу честно сообщаем об ошибке.
            raise Exception("Не удалось получить видео с аниме-сайта: Kodik-плеер не отдал ссылку. "
                            "Проверьте выбор серии/озвучки или повторите позже.")

        outtmpl = _api.os.path.join(out_dir, '%(title)s.%(ext)s')

        # download-sections — уникальное имя на каждый отрезок
        section_arg = None
        self._section_dur = None   # длительность отрезка → % прогресса ffmpeg
        start_s = self.c.get('start_s')
        end_s = self.c.get('end_s')
        source_duration = self.c.get('source_duration')
        if source_duration and not start_s and end_s and end_s >= source_duration:
            end_s = None
            self.c['end_s'] = None
        if start_s is not None or end_s is not None:
            s_val = int(start_s) if start_s else 0
            e_val = int(end_s) if (end_s and end_s > s_val) else None
            if (s_val and s_val > 0) or e_val:
                section_arg = f"*{s_val}-{e_val if e_val else 'inf'}"
                if e_val:
                    self._section_dur = float(e_val - s_val)
                s_tag = f"{s_val}s"
                e_tag = f"{e_val}s" if e_val else "end"
                outtmpl = _api.os.path.join(out_dir, f'%(title)s [{s_tag}-{e_tag}].%(ext)s')

        # Для Kodik имя из URL-страницы (иначе yt-dlp возьмёт «720.mp4:hls:manifest»).
        # raw_url — это страница АНИМЕ, одна на все серии, поэтому без номера
        # серии в имени все серии тайтла бьются в один файл: первая скачивается,
        # а любая следующая видит «уже скачано» и молча выходит без файла
        # (rc=0, файла нет — выглядело как случайный сбой скачивания).
        if kodik:
            from urllib.parse import urlparse as _urlparse
            slug = _api.os.path.splitext(_api.os.path.basename(_urlparse(raw_url).path))[0] or "video"
            ep_tag = f" - {ep} серия" if ep else ""
            outtmpl = _api.os.path.join(out_dir, f"{slug}{ep_tag} [{kodik['height']}p].%(ext)s")

        cmd = base + [
            "--newline", "--no-playlist", "--no-mtime", "--progress",
            "--socket-timeout", "30", "--no-check-certificate", "--windows-filenames",
            # Устойчивость к обрывам соединения (DPI/блокировки провайдера, ошибка 10054)
            "--retries", "10", "--fragment-retries", "20",
            "--extractor-retries", "5", "--retry-sleep", "3",
            "-o", outtmpl,
            "--progress-template",
            "download:@@@%(progress._percent_str)s|%(progress._speed_str)s|"
            "%(progress._eta_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s",
            "--no-simulate",
            # ВАЖНО: --print НЕЯВНО включает --quiet. Из-за этого yt-dlp молчал
            # обо всём, кроме наших @@-строк: ни «[youtube] Extracting URL», ни
            # «[download] Destination», ни WARNING, ни «has already been
            # downloaded». Когда загрузка срывалась без ошибки (rc=0, но файла
            # нет), в лог уходило «вывод пуст — процесс оборвался без единой
            # строки лога» — причина терялась целиком. --no-quiet возвращает
            # обычный вывод; строки прогресса им НЕ дублируются (их формат
            # задан --progress-template).
            "--no-quiet",
            "--print", "before_dl:@@META@@%(thumbnail)s\t%(width)s\t%(height)s\t%(abr)s",
            "--print", "before_dl:@@CHECK@@%(duration)s\t%(vcodec)s\t%(acodec)s",
            "--print", "after_move:@@PATH@@%(filepath)s",
        ]
        if self.c.get('overwrite'):
            cmd += ["--force-overwrites"]

        # Указываем yt-dlp на наш ffmpeg (bundled в bin/) — иначе отдельный
        # процесс yt-dlp не найдёт ffmpeg для склейки/извлечения аудио.
        # ВАЖНО: для нарезки отрезка (--download-sections) подсовываем ОТДЕЛЬНЫЙ
        # ffmpeg 7.x (bin/ffmpeg7) — основной 8.x ломает нарезку (см. FFMPEG7_DIR
        # в config.py и yt-dlp #16546: битый/audio-only отрезок). Для обычных
        # загрузок остаётся основной ffmpeg.
        ffloc = None
        if section_arg and _api.FFMPEG7_DIR:
            ffloc = _api.FFMPEG7_DIR
        elif _api.os.path.isabs(_api.FFMPEG) and _api.os.path.isfile(_api.FFMPEG):
            ffloc = _api.os.path.dirname(_api.FFMPEG)
        if ffloc:
            cmd += ["--ffmpeg-location", ffloc]
            if section_arg and _api.FFMPEG7_DIR:
                self.log_sig.emit("Отрезок: использую ffmpeg 7.x для нарезки (bin/ffmpeg7).")
            elif section_arg:
                self.log_sig.emit("ВНИМАНИЕ: ffmpeg 7.x (bin/ffmpeg7) не найден — "
                                  "нарезка отрезка на ffmpeg 8.x может дать битый файл.")

        # Прокси (если задан в настройках вкладки загрузок)
        if proxy:
            cmd += ["--proxy", proxy]

        # Kodik m3u8 требует Referer на домен плеера
        if kodik and kodik.get('referer'):
            cmd += ["--add-header", f"Referer:{kodik['referer']}"]
            # CDN Kodik троттлит КАЖДОЕ соединение (одиночный поток даёт
            # десятки KiB/s) — сегменты HLS качаем параллельно, а не по
            # одному, иначе загрузка ползёт часами. Прошлый сбой на 32
            # был из-за коллизии имён файлов (см. outtmpl ниже), не из-за
            # числа потоков.
            cmd += ["--concurrent-fragments", "32"]

        if is_audio_only:
            # ТОЛЬКО аудио: берём ЧИСТЫЙ аудиопоток (vcodec=none) — иначе на сайтах
            # без отдельной аудиодорожки fallback `best` тащит ВИДЕО. `--audio-format
            # best` сохраняет исходный кодек (m4a→m4a, opus→opus идут БЕЗ
            # перекодирования: быстрее, без потерь, меньше размер) и не упирается в
            # баг самоперемещения 'X.m4a'->'X.m4a' при совпадении форматов.
            cmd += ["-f", "bestaudio[vcodec=none]/bestaudio/best",
                    "-x", "--audio-format", "best", "--audio-quality", "0"]
        elif kodik:
            # одиночный m3u8 — берём лучшее из манифеста (качество уже выбрано)
            cmd += ["-f", "best", "--merge-output-format", merge]
        else:
            cmd += ["-f", self.c.get('fmt') or "bestvideo+bestaudio/best",
                    "--merge-output-format", merge]

        # Константы заданы здесь, чтобы _inject_tiktok_headers знал, какой UA и
        # какие заголовки добавлять в запасном Desktop-режиме (см. ниже).
        _is_tiktok = _api.host_matches(url, 'tiktok.com')
        _TIKTOK_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
        _TIKTOK_EXTRA_HEADERS = {
            "Accept-Language:en-US,en;q=0.9",
            "Referer:https://www.tiktok.com/",
            "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            'sec-ch-ua:"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "sec-ch-ua-mobile:?0",
            'sec-ch-ua-platform:"Windows"',
        }

        if _is_tiktok:
            # TikTok качаем НАТИВНЫМ экстрактором yt-dlp: его JS challenge-solver
            # сам выставляет нужный UA/заголовки и решает challenge. Навязанный
            # Chrome-UA ЛОМАЛ этот путь → «Unable to extract universal data for
            # rehydration» (воспроизведено: с нашим UA — ошибка, без него — успех).
            # Поэтому Desktop-UA здесь НЕ добавляем — он остаётся ЗАПАСНЫМ
            # вариантом ниже (если нативный путь упрётся в TLS-фингерпринт:
            # пустой ответ → status 0 / JSONDecodeError). api_hostname (Mobile
            # API) тоже не трогаем — без подписей X-Gorgon/X-Khronos он даёт RST.
            self.log_sig.emit("TikTok обнаружен: нативный экстрактор yt-dlp (JS challenge-solver)...")

        if _api.host_matches(url, 'youtube.com', 'youtu.be'):
            self.log_sig.emit("YouTube: клиенты default + web_safari (n-challenge через Deno)...")
            if not _api.deno_available():
                self.log_sig.emit("ВНИМАНИЕ: Deno не найден — YouTube может отдать только 360p. Положите deno.exe в bin.")
            cmd += ["--extractor-args", "youtube:player_client=default,web_safari"]

        if _api.host_matches(url, 'bilibili.com', 'b23.tv'):
            self.log_sig.emit("BiliBili обнаружен: добавляю Referer + User-Agent (фикс HTTP 412 Precondition Failed).")
            cmd += ["--referer", "https://www.bilibili.com/", "--user-agent", _api.USER_AGENT]

        # Куки: domain-specific имеет приоритет над общим UI-полем
        ui_cookie = self.c.get('cookie_path', '').strip()
        c_path = _api.get_cookies_path(url)
        chosen_cookie = None
        if _api.os.path.exists(c_path) and c_path != _api.COOKIE_PATHS['default']:
            chosen_cookie = c_path
            self.log_sig.emit(f"OK: Cookies для {url[:40]}... -> {c_path}")
        elif ui_cookie and _api.os.path.exists(ui_cookie) and _api._cookie_matches_domain(ui_cookie, url):
            chosen_cookie = ui_cookie
            self.log_sig.emit(f"OK: Cookies из настроек: {ui_cookie}")
        elif ui_cookie and _api.os.path.exists(ui_cookie) and not _api._cookie_matches_domain(ui_cookie, url):
            self.log_sig.emit(f"Предупреждение: куки из настроек не подходят для {url[:40]} (пропущены)")
            if _api.os.path.exists(_api.COOKIE_PATHS['default']):
                chosen_cookie = _api.COOKIE_PATHS['default']
                self.log_sig.emit(f"OK: Используем общие cookies: {_api.COOKIE_PATHS['default']}")
        elif _api.os.path.exists(_api.COOKIE_PATHS['default']):
            chosen_cookie = _api.COOKIE_PATHS['default']
            self.log_sig.emit(f"OK: Используем общие cookies: {_api.COOKIE_PATHS['default']}")
        if chosen_cookie:
            cmd += ["--cookies", chosen_cookie]

        if self.c.get('sub_lang') and self.c['sub_lang'] != 'Выкл':
            cmd += ["--write-subs", "--sub-langs",
                    "all" if self.c['sub_lang'] == 'all' else self.c['sub_lang']]

        if section_arg:
            cmd += ["--download-sections", section_arg]
            # _i applies to BOTH remote inputs. EOF reconnection is deliberately
            # omitted: a normally completed finite video must stop at EOF.
            cmd += ["--downloader-args", "ffmpeg_i:-reconnect 1 -reconnect_streamed 1 "
                    "-reconnect_on_network_error 1 -reconnect_delay_max 5 "
                    "-reconnect_on_http_error 408,429,500,502,503,504 -rw_timeout 30000000",
                    "--downloader-args", "ffmpeg_o:-xerror"]
            # Force KF → точный рез с перекодированием в точках; иначе быстрый
            # рез копированием (по ближайшим ключевым кадрам).
            if not is_audio_only and self.c.get('force_kf'):
                cmd += ["--force-keyframes-at-cuts"]

        cmd += [url]

        rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(cmd, iid, is_audio_only)

        # ── TikTok: ДОБИВАЕМСЯ файла повторами процесса ─────────────────────
        # JS-challenge у TikTok НЕСТАБИЛЕН: каждый запуск НЕЗАВИСИМО от UA и
        # cookies (замеры: успех ~50%, в плохие минуты ~17%) либо отдаёт данные,
        # либо страницу-заглушку → «Unable to extract universal data for
        # rehydration» ЛИБО «Unexpected response from webpage request». Внутри
        # одного yt-dlp это НЕ-retryable (--extractor-retries не помогает: сбой
        # «липнет» к процессу — подтверждено), но КАЖДЫЙ НОВЫЙ процесс снова
        # имеет шанс. Встречается и «успех без файла» (rc=0, но after_move/@@PATH@@
        # не пришёл или CDN отдал пусто) — его тоже лечит новый процесс. Поэтому
        # крутим до 20 раз, ПОКА не получим реальный файл. Сбой — на ЭКСТРАКЦИИ
        # (до загрузки): попытки быстрые (~3с) и без .part-файлов.
        def _tt_flaky(lines):
            j = " ".join(lines or []).lower()
            return ("rehydration" in j or "universal data" in j
                    or "unexpected response" in j)
        # Пустой ответ из-за TLS-фингерпринта (status 0 / JSONDecodeError) — это
        # НЕ флапающий challenge; его лечит ТОЛЬКО Desktop-режим (ниже).
        def _tt_tls_block(lines):
            j = " ".join(lines or []).lower()
            return ("status code 0" in j or "failed to parse json" in j
                    or "jsondecodeerror" in j or "expecting value" in j)

        def _resolved():
            """Готовый файл этой загрузки: путь из @@PATH@@, иначе свежий
                медиафайл задания (если @@PATH@@ не пришёл, но файл реально скачан).
                Поиск скоупится по mtime ≥ старта задания — чужой .siq не подхватится."""
            if rc not in (0, None):
                return ""
            if out_fullpath and _api.os.path.exists(out_fullpath):
                return out_fullpath
            if rc in (0, None):
                return self._find_recent_output(out_dir)
            return ""

        TT_MAX = 20
        tt_try = 0
        # Повторяем, ПОКА нет готового файла И сбой лечится повтором: флапающий
        # challenge ЛИБО «успех без файла» (rc=0/None, но файла нет).
        while (_is_tiktok and self.is_running and not _resolved()
               and (_tt_flaky(tail) or rc in (0, None)) and tt_try < TT_MAX):
            tt_try += 1
            self.log_sig.emit(
                f"TikTok: нестабильный ответ сервера — повтор {tt_try}/{TT_MAX}…")
            # pct=0 → строка показывает прогресс повторов, но размер/таскбар не
            # выглядят как идущая загрузка (это всё ещё извлечение).
            self.progress_sig.emit(iid, 0.0, f"Повтор {tt_try}/{TT_MAX}…")
            # Бэкофф: первые попытки — без пауз (обычную флапу ловим быстро),
            # дальше короткая пауза. Учащённый долбёж только продлевает
            # троттлинг TikTok; пауза даёт ограничению «остыть».
            if tt_try > 3:
                self._sleep_interruptible(2.0)
                if not self.is_running:
                    break
            rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(
                cmd, iid, is_audio_only)

        # Desktop Browser (Chrome 125 UA + браузерные заголовки) — ТОЛЬКО для
        # TLS-блокировки. Для флапающего challenge он ВРЕДЕН: навязанный Chrome-UA
        # ломает challenge и даёт HTTP 403 (воспроизведено), поэтому на _tt_flaky
        # его НЕ запускаем.
        if (_is_tiktok and self.is_running and not _resolved()
                and _tt_tls_block(tail) and not _tt_flaky(tail)):
            self.log_sig.emit(
                "TikTok fallback: режим Desktop Browser (Chrome 125 / Windows 11)…")
            cmd_fallback = self._inject_tiktok_headers(
                cmd, _TIKTOK_UA, _TIKTOK_EXTRA_HEADERS)
            rc, out_fullpath, clean_res_str, tail = self._exec_ytdlp(
                cmd_fallback, iid, is_audio_only)

        out_fullpath, clean_res_str = verified_download(
            self, cmd, iid, is_audio_only,
            (rc, out_fullpath, clean_res_str, tail))

        try: self._cleanup_partials(out_dir, out_fullpath)
        except Exception: pass
        self.progress_sig.emit(iid, 100.0, "Готово")
        self.finished_sig.emit(iid, "Готово", clean_res_str or "", out_fullpath)

    except Exception as e:
        err_msg = str(e)
        if "остановлена пользователем" in err_msg:
            self.error_sig.emit(iid, "Остановлено")
            self.log_sig.emit("Загрузка отменена.")
        else:
            self.error_sig.emit(iid, err_msg[:200])
            self.log_sig.emit(f"Ошибка: {err_msg}")
        self._emit_hints(err_msg)
