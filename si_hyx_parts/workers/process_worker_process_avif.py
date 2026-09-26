# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: process_avif. Public namespace: workers."""
import workers as _api


def process_avif(self, item, cb):
    path = item['path']
    base, ext = _api.os.path.splitext(path)

    # Пропускаем файлы, которые сами являются результатом предыдущей конвертации
    if _api.os.path.basename(base).endswith("_Сжатый"):
        self.log.emit(f"Пропущен уже обработанный файл: {_api.os.path.basename(path)}")
        cb(100, "Пропущен")
        return path
    out_dir = self._out_dir_for(path)
    av = self.settings.get('avif', {})
    adim = av.get('adim', 0) or 0
    aspd = av.get('aspd', 0)
    raw_name = _api.os.path.basename(base)
    sanitized = self._sanitize_name(raw_name)
    if sanitized != raw_name:
        self.log.emit(f"Имя переименовано (AI-бренд): «{raw_name}» → «{sanitized}»")
    suffix = "" if av.get('overwrite_src') else "_Сжатый"
    out_name = sanitized + suffix + ".avif"
    out = _api.os.path.join(out_dir, out_name)

    # Выбранный пользователем формат: png/jpg/ico обрабатываем через Pillow
    # (без ffmpeg), avif/webp — основной конвейер ниже.
    img_fmt = (av.get('img_fmt') or 'avif').lower()
    if img_fmt in ('png', 'jpg', 'jpeg', 'ico', 'webp'):
        self.log.emit(f"Формат изображения: {img_fmt.upper()}")
        return self._convert_simple_image(item, path, out_dir, sanitized, adim, av, img_fmt, cb)

    tried_tmp_files = []
    # rot_tmp_file — входной файл после EXIF-поворота, не проба: чистится
    # только когда он точно больше не понадобится как -i для ffmpeg.
    path, rot_tmp_file, orig_w, orig_h = self._avif_prepare_input(path)

    if orig_w * orig_h > 8500000:
        if aspd < 6: aspd = 6

    # Ужимание: макс. сторона + отдельные лимиты ширины/высоты (самый строгий).
    awidth = av.get('awidth', 0) or 0
    aheight = av.get('aheight', 0) or 0
    vf = None
    _tgt = self._target_dims(orig_w, orig_h, adim, awidth, aheight)
    if _tgt:
        vf = f"scale={_tgt[0]}:{_tgt[1]}"
    elif (adim and adim > 0) and not (orig_w and orig_h):
        # Размер исходника не удалось определить — падаем на выражение по макс. стороне.
        vf = f"scale=if(gt(iw\\,ih)\\,{adim}\\,-2):if(gt(ih\\,iw)\\,{adim}\\,-2)"

    has_alpha = self._source_has_alpha(path)
    pix_fmt_avif = self._avif_pix_fmt(has_alpha, av.get('chroma', '420'))

    # Если есть альфа — удаляем старый .avif чтобы не оставалось двух файлов
    if has_alpha and _api.os.path.exists(out):
        try: _api.os.remove(out)
        except Exception: pass

    def _cleanup(files):
        """Удаляет временные файлы; безопасно игнорирует ошибки."""
        for t in list(files):
            try:
                if _api.os.path.exists(t): _api.os.remove(t)
            except Exception: pass

    def _cleanup_final(files):
        """Как _cleanup, но также удаляет входной rot_*.png — вызывать
            только там, где ffmpeg больше не будет читать path (конец функции)."""
        _cleanup(files)
        if rot_tmp_file:
            try:
                if _api.os.path.exists(rot_tmp_file): _api.os.remove(rot_tmp_file)
            except Exception: pass

    # Прозрачность теперь идёт в AVIF (а не принудительно в WebP, как раньше):
    # альфу выносим в отдельный gray-поток (alphaextract) и муксим avif-
    # муксером — прямой `-pix_fmt yuva420p` libaom в этой сборке альфу молча
    # теряет. Команду собирает _encode_to при has_alpha=True. WebP оставлен
    # как РЕЗЕРВ — на случай, если конкретная сборка ffmpeg альфу не закодирует.
    def _alpha_webp_fallback():
        self.log.emit("AVIF с альфой не удался → резерв: WebP (RGBA)")
        cb(0, "Конвертация картинки")

        def _on_pass_a(n, total):
            cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

        with _api.Image.open(path) as im:
            if _api.ImageOps: im = _api.ImageOps.exif_transpose(im)
            im = im.convert('RGBA')
            _tgt_a = self._target_dims(im.width, im.height, adim,
                                       av.get('awidth', 0) or 0, av.get('aheight', 0) or 0)
            if _tgt_a:
                im = im.resize(_tgt_a, _api.Image.LANCZOS)

            out_webp = _api.os.path.splitext(out)[0] + ".webp"
            limit_kb_l = int(av.get('limit', 0) or 0)

            if limit_kb_l > 0:
                def _save_webp_a(q):
                    t = _api.os.path.join(_api.TEMP_DIR, f"wp_{_api.uuid.uuid4().hex}.webp")
                    im.save(t, format="WEBP", quality=q, lossless=False)
                    return t
                chosen_quality = self._search_quality_under_limit(
                    _save_webp_a, limit_kb_l, av.get('fit_passes', 4), q_lo=10, q_hi=85,
                    on_pass=_on_pass_a)
                im.save(out_webp, format="WEBP", quality=chosen_quality, lossless=False)
            else:
                cb(50, "Конвертация картинки")
                im.save(out_webp, format="WEBP", quality=85, lossless=False)

        cb(100, "Конвертация картинки")
        size_new = _api.os.path.getsize(out_webp)
        self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
        _cleanup_final(tried_tmp_files)
        if _api.os.path.exists(out) and out != out_webp:
            try: _api.os.remove(out)
            except Exception: pass
        return out_webp

    if 'libaom-av1' not in _api.detect_ffmpeg_encoders():
        raise Exception("libaom-av1 не доступен в вашей сборке ffmpeg — AVIF перекодирование настроено работать ТОЛЬКО через libaom (libaom-av1).")
    limit_kb = int(av.get('limit', 0) or 0)

    if has_alpha:
        self.log.emit("Альфа-канал обнаружен → AVIF с прозрачностью (alphaextract, libaom-av1, tune=IQ)")
    else:
        self.log.emit("AVIF: libaom-av1, tune=IQ, 10-бит")

    # Подбор под лимит — несколько проб (подборов). Прогресс масштабируем в
    # долю текущей пробы: во время пробы n из total процент не превышает
    # n/total*100, статус — «Конвертация картинки n/total».
    _limit_on = bool(limit_kb and limit_kb > 0)
    total_passes = max(1, min(8, int(av.get('fit_passes', 4)))) if _limit_on else 1
    pass_state = {'n': 0}

    def _pass_cb(pct, _label=None):
        total = total_passes
        nn = min(pass_state['n'], total) or 1
        overall = int(((nn - 1) + pct / 100.0) / total * 100) if total > 0 else pct
        overall = max(0, min(100, overall))
        if total > 1:
            cb(overall, f"Конвертация картинки {nn}/{total}")
        else:
            cb(overall, "Конвертация картинки")

    def _encode_to(tmp_out, crf_val, vf_override=None):
        pass_state['n'] += 1
        cmd = self._avif_encode_cmd(
            path, tmp_out, crf_val,
            vf_override if vf_override is not None else vf,
            has_alpha, pix_fmt_avif, aspd)
        orig_size = _api.os.path.getsize(path) if _api.os.path.exists(path) else 1
        est_seconds = max(1, int(orig_size / 400_000))

        def _try(c):
            try:
                self.run_ffmpeg_capture(c, est_seconds, _pass_cb, cancel_check=lambda: item["iid"] in self.removed_ids)
                return True, None
            except _api.subprocess.CalledProcessError as e:
                return False, (e.stderr[:4000] if hasattr(e, 'stderr') else str(e))
            except Exception as e:
                return False, str(e)

        ok, err = _try(cmd)
        if ok:
            return True, None
        # `-usage allintra` знают только сборки с libaom 3.2+. Если ffmpeg
        # взят из системного PATH и оказался старым, повторяем без него —
        # так же, как это делает avif_fit._run для генератора паков.
        plain = _api.strip_allintra(cmd)
        if plain != cmd:
            ok2, err2 = _try(plain)
            if ok2:
                self.log.emit("ffmpeg не знает -usage allintra — кодирую без него")
                return True, None
            return False, err2 or err
        return False, err

    if not limit_kb or limit_kb <= 0:
        tmp = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}.avif")
        try:
            ok, err = _encode_to(tmp, int(av.get('cq', 30)))
            if not ok:
                if _api.os.path.exists(tmp):
                    try: _api.os.remove(tmp)
                    except Exception: pass
                if has_alpha and _api.Image:
                    return _alpha_webp_fallback()
                raise Exception(f"AVIF conversion failed: {err}")
            if _api.os.path.exists(out):
                try: _api.os.remove(out)
                except Exception: pass
            _api.shutil.move(tmp, out)
            size_new = _api.os.path.getsize(out)
            self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
            return out
        finally:
            if _api.os.path.exists(tmp):
                try: _api.os.remove(tmp)
                except Exception: pass
            _cleanup_final(tried_tmp_files)

    best_tmp = None
    best_size_kb = -1
    size63_kb = None  # база для оценки даунскейла, если ни один CQ не влезет

    try:
        iterations = 0
        max_iterations = max(1, min(8, int(av.get('fit_passes', 4))))

        def _probe(crf_val):
            t = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}_{crf_val}.avif")
            tried_tmp_files.append(t)
            ok, err = _encode_to(t, crf_val)
            if not ok:
                if _api.os.path.exists(t):
                    try: _api.os.remove(t)
                    except Exception: pass
                raise Exception(f"AVIF conversion failed: {err}")
            return t, max(1, _api.os.path.getsize(t) // 1024)

        def _discard(t):
            try:
                if _api.os.path.exists(t):
                    _api.os.remove(t)
                    tried_tmp_files.remove(t)
            except Exception: pass

        def _consider(t, s):
            nonlocal best_tmp, best_size_kb
            if s > best_size_kb:
                if best_tmp and best_tmp != t and _api.os.path.exists(best_tmp):
                    try: _api.os.remove(best_tmp)
                    except Exception: pass
                best_tmp, best_size_kb = t, s
            else:
                _discard(t)

        # Разведка: сразу пробуем оба полюса диапазона — CQ=0 (макс.
        # качество) и CQ=63 (мин.) — вместо удвоения шага от 0. Обрыв
        # размера у AV1 (tune=iq) не всегда у самых низких CQ (для
        # мультяшных/плоских картинок — да, но для детальных фото может
        # лежать и в середине-верху диапазона, см. в памяти
        # avif-fit-passes-binary-search-depth) — раньше удвоение шага
        # (0→1→3→7→…) в таких случаях за отведённый бюджет ни разу не
        # приближалось к реальному обрыву и скатывалось на CQ=63 почти
        # без разбора. Зная оба конца сразу, дальше сужаем вилку
        # log-интерполяцией (log(size) у AV1 примерно линеен по CQ) с
        # небольшим смещением цели НИЖЕ реального лимита — на гладкой
        # кривой (без резкого обрыва) интерполяция к самому лимиту почти
        # всегда чуть промахивается ВЫШЕ него, и проход теряется впустую;
        # смещение забирает этот запас заранее.
        tmp0, size0_kb = _probe(0)
        iterations += 1
        if size0_kb <= limit_kb:
            _consider(tmp0, size0_kb)
        else:
            bad_crf, bad_size = 0, size0_kb
            good_crf, good_size = None, None
            if iterations < max_iterations:
                t63, s63 = _probe(63)
                iterations += 1
                size63_kb = s63
                if s63 <= limit_kb:
                    good_crf, good_size = 63, s63
                    _consider(t63, s63)
                else:
                    _discard(t63)
                    bad_crf, bad_size = 63, s63

            if good_crf is not None:
                _TARGET_BIAS = 0.9
                while good_crf - bad_crf > 1 and iterations < max_iterations:
                    if bad_size == good_size:
                        mid = (bad_crf + good_crf) // 2
                    else:
                        lt = _api.math.log(max(1, limit_kb * _TARGET_BIAS))
                        lo, hi = _api.math.log(bad_size), _api.math.log(good_size)
                        frac = max(0.0, min(1.0, (lo - lt) / (lo - hi)))
                        mid = int(round(bad_crf + frac * (good_crf - bad_crf)))
                        mid = max(bad_crf + 1, min(good_crf - 1, mid))
                    t, s = _probe(mid)
                    iterations += 1
                    if s <= limit_kb:
                        good_crf, good_size = mid, s
                        _consider(t, s)
                    else:
                        _discard(t)
                        bad_crf, bad_size = mid, s

        if best_tmp and _api.os.path.exists(best_tmp):
            if _api.os.path.exists(out):
                try: _api.os.remove(out)
                except Exception: pass
            _api.shutil.move(best_tmp, out)
            size_new = _api.os.path.getsize(out)
            _cleanup_final(tried_tmp_files)
            self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
            return out

        if not orig_w or not orig_h:
            try:
                if _api.Image:
                    with _api.Image.open(path) as im: orig_w, orig_h = im.size
            except Exception: pass

        if size63_kb is None:
            # Разведка не успела дойти до CQ=63 в рамках бюджета проходов
            # (шаг удвоения обогнал бюджет) — добираем эту пробу отдельно.
            # Если CQ=63 САМ укладывается в лимит — это и есть готовый
            # ответ в полном разрешении: раньше этот результат выбрасывали
            # и всё равно шли на даунскейл (который не был нужен и терял
            # разрешение без причины — approx_ratio клампится к 1.0, но
            # target_pixels всё равно * 0.98 срезает ~1% стороны).
            t63, size63_kb = _probe(63)
            if size63_kb <= limit_kb:
                _consider(t63, size63_kb)
            else:
                _discard(t63)

        if best_tmp and _api.os.path.exists(best_tmp):
            if _api.os.path.exists(out):
                try: _api.os.remove(out)
                except Exception: pass
            _api.shutil.move(best_tmp, out)
            size_new = _api.os.path.getsize(out)
            _cleanup_final(tried_tmp_files)
            self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
            return out

        if not orig_w or not orig_h:
            _cleanup(tried_tmp_files)
            raise Exception("Не удалось получить размеры изображения для downscale.")

        new_max_side = self._avif_downscale_side(orig_w, orig_h, size63_kb, limit_kb)

        down_attempt = 0
        max_down_attempts = 5
        current_side = new_max_side
        while down_attempt < max_down_attempts:
            vf_down = f"scale=if(gt(iw\\,ih)\\,{current_side}\\,-2):if(gt(ih\\,iw)\\,{current_side}\\,-2)"
            tmp_down = _api.os.path.join(_api.TEMP_DIR, f"avif_{_api.uuid.uuid4().hex}_down{down_attempt}.avif")
            tried_tmp_files.append(tmp_down)
            ok, err = _encode_to(tmp_down, 63, vf_override=vf_down)
            if not ok:
                if _api.os.path.exists(tmp_down):
                    try: _api.os.remove(tmp_down)
                    except Exception: pass
                raise Exception(f"AVIF conversion failed during downscale attempt: {err}")
            size_kb = max(1, _api.os.path.getsize(tmp_down) // 1024)
            if size_kb <= limit_kb:
                if _api.os.path.exists(out):
                    try: _api.os.remove(out)
                    except Exception: pass
                _api.shutil.move(tmp_down, out)
                size_new = _api.os.path.getsize(out)
                _cleanup_final(tried_tmp_files)
                self.update_item_sig.emit(item['iid'], _api.human_size(size_new), "-")
                return out
            else:
                try:
                    if _api.os.path.exists(tmp_down):
                        _api.os.remove(tmp_down)
                        tried_tmp_files.remove(tmp_down)
                except Exception: pass
                current_side = max(16, int(current_side * 0.85))
                down_attempt += 1

        _cleanup(tried_tmp_files)
        raise Exception("Не удалось достичь указанного лимита AVIF.")

    except _api.subprocess.CalledProcessError as e:
        stderr_tail = e.stderr if hasattr(e, 'stderr') else ''
        _cleanup(tried_tmp_files)
        if _api.os.path.exists(out):
            try:
                _api.os.remove(out)
                self.log.emit(f"Удалён повреждённый AVIF: {out}")
            except Exception: pass
        if has_alpha and _api.Image:
            return _alpha_webp_fallback()
        if rot_tmp_file:
            try:
                if _api.os.path.exists(rot_tmp_file): _api.os.remove(rot_tmp_file)
            except Exception: pass
        raise Exception(f"AVIF conversion failed: {stderr_tail[:4000]}")
    except Exception:
        _cleanup(tried_tmp_files)
        if _api.os.path.exists(out):
            try:
                _api.os.remove(out)
                self.log.emit(f"Удалён повреждённый AVIF: {out}")
            except Exception: pass
        if has_alpha and _api.Image:
            return _alpha_webp_fallback()
        if rot_tmp_file:
            try:
                if _api.os.path.exists(rot_tmp_file): _api.os.remove(rot_tmp_file)
            except Exception: pass
        raise
