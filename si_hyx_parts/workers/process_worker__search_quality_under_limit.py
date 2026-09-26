# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _search_quality_under_limit. Public namespace: workers."""
import workers as _api


def _search_quality_under_limit(self, save_to_tmp, limit_kb, passes, q_lo=10, q_hi=95,
                                on_pass=None):
    """Бинарный поиск макс. quality (q_lo..q_hi), при котором размер файла ≤ limit_kb.
        save_to_tmp(q) -> путь к временному файлу (удаляется здесь же).
        passes — число проб (1..8). on_pass(n, total) — колбэк прогресса подбора
        (n — номер текущей пробы 1..total). Возвращает выбранное quality:
        максимальное влезающее, а если ничего не влезло — q_lo (минимальный размер)."""
    passes = max(1, min(8, int(passes or 4)))
    lo, hi = int(q_lo), int(q_hi)
    chosen, found, n = q_lo, False, 0
    while lo <= hi and n < passes:
        n += 1
        if on_pass:
            try: on_pass(n, passes)
            except Exception: pass
        mid = (lo + hi) // 2
        tmp = save_to_tmp(mid)
        try:
            fits = (_api.os.path.getsize(tmp) // 1024) <= limit_kb
        finally:
            try: _api.os.remove(tmp)
            except Exception: pass
        if fits:
            chosen, found, lo = mid, True, mid + 1
        else:
            hi = mid - 1
    return chosen if found else q_lo

def _convert_simple_image(self, item, src_path, out_dir, sanitized, adim, av, fmt, cb):
    """Конвертация изображения в png / jpg / ico / webp через Pillow (без ffmpeg).
        Учитывает лимит разрешения (adim) и для jpg/webp — лимит размера файла.
        """
    if not _api.Image:
        raise Exception("Pillow (PIL) не установлен — конвертация в этот формат недоступна.")
    fmt = fmt.lower()
    ext = {'jpeg': 'jpg', 'jpg': 'jpg', 'png': 'png', 'ico': 'ico', 'webp': 'webp'}.get(fmt, fmt)
    suffix = "" if av.get('overwrite_src') else "_Сжатый"
    out_path = _api.os.path.join(out_dir, f"{sanitized}{suffix}.{ext}")

    # Прогресс подбора качества под лимит: во время прохода n из total процент
    # не превышает n/total*100 (реалистично отражает, что подбор ещё не закончен).
    def _on_pass(n, total):
        cb(int((n - 1) / total * 100), f"Конвертация картинки {n}/{total}")

    cb(0, "Конвертация картинки")

    with _api.Image.open(src_path) as im:
        if _api.ImageOps:
            im = _api.ImageOps.exif_transpose(im)
        had_alpha = im.mode in ('RGBA', 'LA', 'PA', 'La', 'RGBa') or \
                    (im.mode == 'P' and 'transparency' in im.info)
        # JPEG не поддерживает альфу
        if ext == 'jpg':
            im = im.convert('RGB')
        elif ext == 'ico':
            im = im.convert('RGBA')
        elif ext == 'webp':  # WebP умеет прозрачность — сохраняем альфу, если была
            im = im.convert('RGBA') if had_alpha else im.convert('RGB')
        else:  # png
            im = im.convert('RGBA') if im.mode in ('RGBA', 'LA', 'P', 'PA') else im.convert('RGB')

        # Лимит разрешения; для ICO жёсткий потолок 256px
        awidth = av.get('awidth', 0) or 0
        aheight = av.get('aheight', 0) or 0
        if ext == 'ico':
            cap = min(256, adim) if (adim and adim > 0) else 256
            if max(im.width, im.height) > cap:
                sc = cap / max(im.width, im.height)
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), _api.Image.LANCZOS)
        else:
            tgt = self._target_dims(im.width, im.height, adim, awidth, aheight)
            if tgt:
                im = im.resize(tgt, _api.Image.LANCZOS)

        limit_kb = int(av.get('limit', 0) or 0) if av.get('limit_on', True) else 0
        if limit_kb <= 0:
            cb(55, "Конвертация картинки")

        if ext == 'ico':
            # Иконки квадратные — добавляем прозрачные поля, если нужно
            side = max(im.width, im.height)
            if im.width != im.height:
                canvas = _api.Image.new("RGBA", (side, side), (0, 0, 0, 0))
                canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
                im = canvas
            cand = [16, 24, 32, 48, 64, 128, 256]
            sizes = [(s, s) for s in cand if s <= side] or [(side, side)]
            im.save(out_path, format='ICO', sizes=sizes)
        elif ext in ('jpg', 'webp', 'png'):
            # Лимит размера: сначала подбор качества, а если даже минимальное
            # качество не влезает — ужимаем разрешение и подбираем снова
            # (в AVIF-ветке это давно есть, а здесь раньше не было, и лимит
            # на jpg/webp/png по факту не соблюдался). PNG без потерь —
            # для него единственный рычаг именно разрешение.
            def _mk_tmp(img, q, _ext=ext):
                t = _api.os.path.join(_api.TEMP_DIR, f"{_ext}_{_api.uuid.uuid4().hex}.{_ext}")
                if _ext == 'jpg':
                    img.save(t, format='JPEG', quality=q, optimize=True)
                elif _ext == 'webp':
                    img.save(t, format='WEBP', quality=q, method=6)
                else:
                    img.save(t, format='PNG', optimize=True)
                return t

            def _final_save(img, q, _ext=ext):
                if _ext == 'jpg':
                    img.save(out_path, format='JPEG', quality=q, optimize=True)
                elif _ext == 'webp':
                    img.save(out_path, format='WEBP', quality=q, method=6)
                else:
                    img.save(out_path, format='PNG', optimize=True)

            if limit_kb <= 0:
                _final_save(im, {'jpg': 92, 'webp': 90}.get(ext, 0))
            else:
                q_lo, q_hi = 10, 95
                passes = av.get('fit_passes', 4)
                cur = im
                saved = False
                for attempt in range(6):
                    if ext == 'png':
                        chosen = 0
                    else:
                        chosen = self._search_quality_under_limit(
                            lambda q, _im=cur: _mk_tmp(_im, q), limit_kb, passes,
                            q_lo=q_lo, q_hi=q_hi,
                            on_pass=_on_pass if attempt == 0 else None)
                    t = _mk_tmp(cur, chosen)
                    try:
                        size_kb = max(1, _api.os.path.getsize(t) // 1024)
                    finally:
                        try: _api.os.remove(t)
                        except Exception: pass
                    if size_kb <= limit_kb:
                        _final_save(cur, chosen)
                        saved = True
                        break
                    # Не влезли даже на минимальном качестве → уменьшаем сторону.
                    if attempt == 0:
                        side = self._avif_downscale_side(cur.width, cur.height,
                                                         size_kb, limit_kb)
                    else:
                        side = int(max(cur.width, cur.height) * 0.85)
                    side = max(16, min(side, max(cur.width, cur.height) - 1))
                    sc = side / max(cur.width, cur.height)
                    cur = cur.resize((max(1, int(cur.width * sc)),
                                      max(1, int(cur.height * sc))), _api.Image.LANCZOS)
                    self.log.emit(
                        f"{ext.upper()}: лимит {limit_kb} КБ не достигнут "
                        f"({size_kb} КБ) → уменьшаю до {cur.width}x{cur.height}")
                if not saved:
                    _final_save(cur, q_lo if ext != 'png' else 0)

    cb(100, "Конвертация картинки")
    try:
        self.update_item_sig.emit(item['iid'], _api.human_size(_api.os.path.getsize(out_path)), "-")
    except Exception:
        pass
    return out_path
