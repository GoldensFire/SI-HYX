# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Граф ffmpeg проекта: склейка, переходы, наложения, текст и звук.
Public namespace: montage_project.

Картинка. Основная дорожка — база кадра: каждый клип — свой вход с входным
-ss на четверть кадра раньше (_seek_s), приводится к размеру и fps проекта
(fit/fill/crop) и обрезается РОВНО до своего числа кадров. Границы кусков —
по сетке кадров проекта (round(t·fps)) независимо, так что ошибка не копится,
а звук, расставленный по сэмплам, не уезжает дальше полукадра. Соседи
склеиваются concat; клип с переходом встаёт внахлёст (Project.pack), и его
кадры нахлёста сводит xfade. Пустое место — цвет фона проекта.
Верхние видеодорожки — наложения снизу вверх: кадр клипа вписывается в свой
прямоугольник (scale — доля кадра, pos_x/pos_y — центр), без полей —
прозрачно (yuva420p; opacity — lut альфы), по времени — сдвиг меток на целое
число кадров, overlay с eof_action=pass и format=yuv420 (с auto ffmpeg мог
свести весь граф к RGB). Текст проекта — ASS (subtitle_ass) поверх всего, во
времени проекта. HDR-сведение — первым в цепочке кадра исходника, вшитые
субтитры исходника — во времени исходника (как и раньше).

Звук. Каждый клип — свой вход; место и длина — в сэмплах от общей сетки
(adelay …S, atrim end_sample): конец одного клипа и начало следующего в одном
сэмпле. Нарастание и затухание клипа — afade в сэмплах самого клипа (метки
клипа на время afade — от его начала: на краю выдержки фаза та же, что и в
полной сборке); переход основной дорожки — встречные afade на нахлёсте (то же,
что acrossfade, но без склейки потоков: место каждого клипа остаётся точным).
Первым входом каждого amix — тишина на всю длину (задержанный первый вход
ломал метки). Голос (Track.role) приглушает музыку sidechaincompress
(ProjectSettings.duck). В конце — alimiter с компенсацией задержки: сумма
клипов normalize=0 могла выйти за 0 dBFS.

window=(t0, t1) — выдержка по полному проекту, а не по Project.excerpt:
переход на краю окна строится целиком (окно расширяется до его краёв и потом
срезается), затухание идёт с той же фазой."""
import hashlib
import os

import montage_project as _api

_LIMIT = 0.95                     # потолок alimiter (≈ −0.45 dBFS)
_DUCK_THRESHOLD = 0.02            # голос громче ≈ −34 dBFS прижимает музыку
# Разгон приглушения перед окном выдержки: у компрессора память (release
# 400 мс) — без разгона на краю окна звук просмотра прыгал.
_DUCK_PREROLL_S = 1.0
_TEXT_RES_Y = 288                 # холст ASS текста проекта по высоте (как у SRT)


def _fr(t, fps):
    return int(round(float(t) * fps))


class _Graph:
    """Входы и цепочки фильтров одного графа."""

    def __init__(self):
        self.inputs = []
        self.chains = []
        self._n = {}

    def label(self, prefix):
        k = self._n.get(prefix, 0)
        self._n[prefix] = k + 1
        return f"{prefix}{k}"


def _source_chain(g, c, t_a, t_b, n, rate, fit, pix_fmt, subs, tonemap):
    """Вход клипа c с времени проекта t_a по t_b и цепочка его кадров: ровно
    n кадров в размере вписывания fit, метки с нуля (без метки выхода).

    Стоп-кадр — один кадр исходника на freeze_at, продлённый tpad на всю
    длину. Реверс — кусок исходника [время на t_b, время на t_a) читается
    ровно (-t без запаса: лишние кадры после reverse оказались бы первыми)
    и разворачивается уже в размере проекта: reverse держит все кадры."""
    speed = c.play_speed
    span = t_b - t_a
    idx = len(g.inputs)
    hold = "1"
    pick = reverse = ""
    if c.frozen:
        s = c.freeze_at
        g.inputs.append(["-ss", _api._num(_api._seek_s(c, s)), "-t", "1", "-i", c.src])
        pick = "trim=end_frame=1,"
        hold = _api._num(span + 1.0)
    elif c.reverse:
        s = c.source_time(t_b)
        g.inputs.append(["-ss", _api._num(_api._seek_s(c, s)),
                         "-t", _api._num(span * speed), "-i", c.src])
        reverse = "reverse,"
    else:
        s = c.source_time(t_a)
        if c.is_image:
            g.inputs.append(["-loop", "1", "-framerate", rate, "-t", _api._num(span + 1.0),
                             "-i", c.src])
        else:
            g.inputs.append(["-ss", _api._num(_api._seek_s(c, s)),
                             "-t", _api._num(span * speed + 0.5), "-i", c.src])
    sub_vf = (subs or {}).get(_api.source_key(c.src)) if not c.is_image else None
    tone_vf = (tonemap or {}).get(_api.source_key(c.src)) if not c.is_image else None
    tone = f"{tone_vf}," if tone_vf else ""
    burn = ""
    if sub_vf:
        # Первый кадр после входного seek — кадр, на котором стоит s.
        first = _api.snap_to_frame(s, c.fps)
        burn = f"setpts=PTS-STARTPTS+{_api._num(first)}/TB,{sub_vf},"
    speed_vf = "" if abs(speed - 1.0) <= 1e-6 else f"setpts=(PTS-STARTPTS)/{_api._num(speed)},"
    # scale=iw*sar:ih — неквадратный пиксель (анаморфный DVD) в квадратный до
    # вписывания: вписывание шло по размеру в пикселях, а setsar=1 потом
    # показывал кадр 16:9 как 3:2. У квадратного пикселя фильтр кадр не трогает.
    return (f"[{idx}:v:0]{tone}{burn}{pick}setpts=PTS-STARTPTS,{speed_vf}"
            f"scale=iw*sar:ih,setsar=1,{fit}setsar=1,{reverse}"
            f"fps={rate},tpad=stop_mode=clone:stop_duration={hold},"
            f"trim=end_frame={n},setpts=PTS-STARTPTS,format={pix_fmt}")


def _span_times(c, a, b, F0, F1, fps):
    """Время проекта первого кадра куска [a, b) клипа c (кадры [F0, F1)) и
    конца куска — так, как их показала бы полная сборка."""
    t_a = c.start if a == F0 else c.start + (a - F0) / fps
    t_b = c.end if b == F1 else c.start + (b - F0) / fps
    return t_a, t_b


def _box_fit(mode, bw, bh):
    """Вписывание кадра наложения в прямоугольник bw×bh — без полей:
    вокруг клипа прозрачно, видна нижняя дорожка."""
    if mode == 'fill':
        return f"scale={bw}:{bh},"
    if mode == 'crop':
        return (f"scale={bw}:{bh}:force_original_aspect_ratio=increase:force_divisible_by=2,"
                f"crop={bw}:{bh},")
    return f"scale={bw}:{bh}:force_original_aspect_ratio=decrease:force_divisible_by=2,"


def _main_items(project, fps):
    """[(клип, F0, F1, кадров нахлёста с предыдущим)] основной дорожки."""
    main = project.main_track
    if not project.tracks[main].enabled:
        return []
    items, prev, prev_f1 = [], None, None
    for c in project.clips_on(main):
        if not c.has_video or c.length <= _api._EPS:
            continue
        f0, f1 = _fr(c.start, fps), _fr(c.end, fps)
        d = 0
        if prev is not None and f0 < prev_f1:
            if project.transition_overlap(prev, c) > 0:
                d = prev_f1 - f0
            if not d or d >= f1 - f0 or d >= prev_f1 - _fr(prev.start, fps):
                d, f0 = 0, prev_f1           # нахлёст без перехода — встык
        if f1 <= f0:
            continue
        items.append((c, f0, f1, d))
        prev, prev_f1 = c, f1
    return items


def _render_range(items, g0, g1):
    """Кадры [r0, r1), которые надо собрать для окна [g0, g1): переход на
    краю окна — целиком, иначе xfade начал бы его с нуля."""
    r0, r1 = g0, g1
    for _c, f0, _f1, d in items:
        if d and f0 < r0 < f0 + d:
            r0 = f0
        if d and f0 < r1 < f0 + d:
            r1 = f0 + d
    return r0, r1


def _join(g, seq, fps):
    """Склейка кусков базы; метка результата. Подряд без перехода — concat.
    Переход — xfade только на кадрах нахлёста: хвост предыдущего куска и
    голова следующего отделяются split + trim, сводятся и возвращаются в
    yuv420p. xfade этой сборки ffmpeg работает в yuv444p: через него весь
    поток шёл бы 4:2:0 → 4:4:4 → 4:2:0, и цветность мылилась по всему ролику
    (до 43 уровней на резких краях), а не только на переходе."""
    parts, tails = [], {}
    for i, e in enumerate(seq):
        d_in = e["d"] if e["trans"] else 0
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        d_out = nxt["d"] if nxt is not None and nxt["trans"] else 0
        n = e["b"] - e["a"]
        cuts = []
        if d_in:
            cuts.append(("head", 0, d_in))
        if n - d_in - d_out > 0:
            cuts.append(("mid", d_in, n - d_out))
        if d_out:
            cuts.append(("tail", n - d_out, n))
        if len(cuts) == 1:
            labels = {cuts[0][0]: e["label"]}
        else:
            outs = [g.label("s") for _ in cuts]
            g.chains.append(f"[{e['label']}]split={len(cuts)}" + "".join(f"[{o}]" for o in outs))
            labels = {}
            for (name, a, b), o in zip(cuts, outs):
                lab = g.label("p")
                g.chains.append(f"[{o}]trim=start_frame={a}:end_frame={b},"
                                f"setpts=PTS-STARTPTS[{lab}]")
                labels[name] = lab
        if d_in:
            x = g.label("x")
            g.chains.append(f"[{tails[i - 1]}][{labels['head']}]xfade=transition={e['trans']}:"
                            f"duration={_api._num(d_in / fps)}:offset=0,format=yuv420p[{x}]")
            parts.append(x)
        if "mid" in labels:
            parts.append(labels["mid"])
        if d_out:
            tails[i] = labels["tail"]
    if len(parts) == 1:
        return parts[0]
    lab = g.label("g")
    g.chains.append("".join(f"[{p}]" for p in parts) + f"concat=n={len(parts)}:v=1:a=0[{lab}]")
    return lab


def _video(g, project, w, h, fps, rate, bg, r0, r1, subs, tonemap, items):
    """База (основная дорожка) на кадрах [r0, r1) и наложения; метка итога."""
    settings = project.settings
    seq, cursor = [], r0

    def filler(a, b):
        lab = g.label("v")
        g.chains.append(f"color=c={bg}:s={w}x{h}:r={rate},trim=end_frame={b - a},"
                        f"setsar=1,format=yuv420p[{lab}]")
        seq.append({"label": lab, "a": a, "b": b, "trans": "", "d": 0})

    for c, f0, f1, d in items:
        a, b = max(f0, r0), min(f1, r1)
        if b <= a:
            continue
        trans = ""
        if d and a == f0 and seq and seq[-1]["b"] == f0 + d:
            trans = c.transition
        else:
            a = max(a, cursor)
            if b <= a:
                continue
            if a > cursor:
                filler(cursor, a)
        t_a, t_b = _span_times(c, a, b, f0, f1, fps)
        fit = _api.fit_chain(c.fit or settings.fit, w, h, bg)
        lab = g.label("v")
        g.chains.append(_source_chain(g, c, t_a, t_b, b - a, rate, fit, "yuv420p",
                                      subs, tonemap) + f"[{lab}]")
        seq.append({"label": lab, "a": a, "b": b, "trans": trans, "d": d if trans else 0})
        cursor = b
    if cursor < r1:
        filler(cursor, r1)
    cur = _join(g, seq, fps)
    # Наложения: верхние видеодорожки снизу вверх.
    main = project.main_track
    for ti in project.tracks_of('video'):
        if ti == main or not project.tracks[ti].enabled:
            continue
        for c in project.clips_on(ti):
            if not c.has_video or c.length <= _api._EPS or c.opacity <= 0:
                continue
            f0, f1 = _fr(c.start, fps), _fr(c.end, fps)
            a, b = max(f0, r0), min(f1, r1)
            if b <= a:
                continue
            t_a, t_b = _span_times(c, a, b, f0, f1, fps)
            bw = max(2, int(round(w * c.scale / 2.0)) * 2)
            bh = max(2, int(round(h * c.scale / 2.0)) * 2)
            fit = _box_fit(c.fit or settings.fit, bw, bh)
            alpha = f",lut=a=val*{_api._num(c.opacity)}" if c.opacity < 1.0 else ""
            lab = g.label("o")
            # Метки кадров — в долях 1/fps (их ставит fps=): сдвиг на целое
            # число кадров, без округления секунд.
            g.chains.append(_source_chain(g, c, t_a, t_b, b - a, rate, fit, "yuva420p",
                                          subs, tonemap)
                            + f"{alpha},setpts=PTS+{a - r0}[{lab}]")
            out = g.label("c")
            g.chains.append(f"[{cur}][{lab}]overlay=x=main_w*{_api._num(c.pos_x)}-overlay_w/2:"
                            f"y=main_h*{_api._num(c.pos_y)}-overlay_h/2:"
                            f"eof_action=pass:format=yuv420[{out}]")
            cur = out
    return cur


def text_cues(project, t0, t1, play_res):
    """Реплики ASS (для subtitle_ass._cues_to_ass) текста проекта,
    задевающего [t0, t1), во времени ПРОЕКТА: вшивание идёт по меткам
    проекта, и у окна анимация текста (fade, slide) в той же фазе, что и в
    полной сборке. Текст экранируется: фигурные скобки и
    переводы строк — внутри _cues_to_ass, обратная черта — здесь (\\N и \\h
    libass читает и вне скобок)."""
    import subtitle_ass
    res_x, res_y = play_res
    cues = []
    for item in project.texts:
        if item.end <= t0 or item.start >= t1:
            continue
        style = dict(subtitle_ass.DEFAULT_SUBTITLE_STYLE)
        style.update(item.style or {})
        start, end = item.start, item.end
        tags = ""
        if item.pos_x is not None and item.pos_y is not None:
            x, y = item.pos_x * res_x, item.pos_y * res_y
            align = int(style.get('align') or 2)
            if style.get('animation') == 'slide':
                dur = max(10, int(round((item.end - item.start) * 1000)))
                t = min(300, max(50, dur // 3))
                tags = (f"{{\\an{align}\\move({x - 60 * res_x / 384:.0f},{y:.0f},"
                        f"{x:.0f},{y:.0f},0,{t})}}")
            else:
                anim = subtitle_ass._animation_override_tags(
                    style.get('animation', 'none'), align, max(0.01, end - start), play_res)
                tags = f"{{\\an{align}\\pos({x:.0f},{y:.0f})}}{anim}"
        cues.append({"start": start, "end": end, "style": style,
                     "text": item.text.replace("\\", "＼"), "tags": tags})
    return cues


def _text_file(project, t0, t1, w, h):
    """Путь .ass текста проекта на [t0, t1) или None. Файл — в TEMP по
    хэшу содержимого (как таблицы lut3d у hdr_tonemap): тот же текст — тот
    же файл, удалять его после сборки не нужно."""
    import subtitle_ass
    from ffmpeg_env import TEMP_DIR
    play_res = (max(16, int(round(_TEXT_RES_Y * w / float(h)))), _TEXT_RES_Y)
    cues = text_cues(project, t0, t1, play_res)
    if not cues:
        return None
    text = subtitle_ass._cues_to_ass(cues, play_res=play_res)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    path = os.path.join(TEMP_DIR, f"sihyx_text_{digest}.ass")
    if not os.path.isfile(path):
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    return path


def _audio_fades(project, parts):
    """{id клипа: (нарастание, затухание)} в секундах: свои фейды клипа и
    встречные на переходах основной дорожки."""
    fades = {c.id: [c.fade_in, c.fade_out] for c in parts}
    prev = None
    for c in project.clips_on(project.main_track):
        ov = project.transition_overlap(prev, c)
        if ov > 0:
            if prev.id in fades:
                fades[prev.id][1] = max(fades[prev.id][1], ov)
            if c.id in fades:
                fades[c.id][0] = max(fades[c.id][0], ov)
        prev = c
    return fades


def _mix(g, labels, n_total, out):
    """amix клипов: первым входом — тишина на всю длину проекта: amix берёт
    метки времени у первого входа, и если им оказывался задержанный adelay
    кусок (клип не с начала шкалы), ffmpeg выдавал битые метки — звук
    обрывался на первых 20 мс («Error submitting a packet to the muxer»).
    Тишина с нуля даёт ровную шкалу, а duration=first — точную длину."""
    rate = _api._AUDIO_RATE
    sil = "asil" if out == "aout" or out == "amix" else g.label("asil")
    g.chains.append(f"anullsrc=r={rate}:cl=stereo,atrim=end_sample={max(1, n_total)}[{sil}]")
    g.chains.append(f"[{sil}]" + "".join(f"[{x}]" for x in labels)
                    + f"amix=inputs={len(labels) + 1}:normalize=0:"
                      f"dropout_transition=0:duration=first[{out}]")


def _ducking(project, parts):
    """Голос приглушает музыку: duck задан и есть клипы обеих ролей."""
    if project.settings.duck <= 0:
        return False
    roles = {project.tracks[c.track].role for c in parts}
    return "voice" in roles and "music" in roles


def _audio(g, project, parts, w0, w1, total_s, pre=0.0):
    """Звук клипов parts на окне [w0, w1); метка итога [aout]. pre — разгон
    перед окном (секунды): собирается с w0 - pre и срезается в конце."""
    rate = _api._AUDIO_RATE
    w0 -= pre
    fades = _audio_fades(project, parts)
    by_role = {"voice": [], "music": [], "": []}
    for c in parts:
        idx = len(g.inputs)
        speed = c.play_speed
        a_start, a_end = max(c.start, w0), min(c.end, w1)
        whole = a_start == c.start and a_end == c.end
        src_span = (c.length if whole else a_end - a_start) * speed
        # Реверс: читается кусок [время на a_end, время на a_start), его
        # первые n сэмплов разворачиваются (areverse после atrim).
        seek = c.source_time(a_end if c.reverse else a_start)
        g.inputs.append(["-ss", _api._num(seek),
                         "-t", _api._num(src_span + 0.25), "-i", c.audio_path])
        spec = f"{idx}:{c.audio_stream}" if c.audio_stream >= 0 else f"{idx}:a:0"
        lab = g.label("a")
        tempo = _api.atempo_chain(speed)
        tempo_vf = (",".join(tempo) + ",") if tempo else ""
        # Место и длина — в сэмплах, от общей сетки шкалы: конец клипа и
        # начало следующего попадают в один и тот же сэмпл. С миллисекундами
        # (adelay округлял начало) на стыке оставалась дыра до 0.5 мс — щелчок.
        a0 = int(round((a_start - w0) * rate))
        n = max(1, int(round((a_end - w0) * rate)) - a0)
        fade_vf = ""
        fi, fo = fades.get(c.id, (0.0, 0.0))
        if fi > 0 or fo > 0:
            # Метки — сэмплы от начала САМОГО клипа: afade считает место по
            # ним, и выдержка с середины клипа затухает с той же фазой.
            local0 = int(round((a_start - c.start) * rate))
            length = int(round(c.length * rate))
            fade_vf = f"asettb=1/{rate},asetpts=PTS-STARTPTS+{local0},"
            if fi > 0:
                fade_vf += f"afade=t=in:ss=0:ns={max(1, int(round(fi * rate)))},"
            if fo > 0:
                ns = max(1, int(round(fo * rate)))
                fade_vf += f"afade=t=out:ss={max(0, length - ns)}:ns={ns},"
            fade_vf += "asetpts=PTS-STARTPTS,"
        g.chains.append(
            f"[{spec}]aresample={rate},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"{tempo_vf}atrim=end_sample={n},{'areverse,' if c.reverse else ''}"
            f"asetpts=PTS-STARTPTS,{fade_vf}"
            f"volume={_api._num(c.volume)},adelay={a0}S:all=1[{lab}]")
        role = project.tracks[c.track].role
        by_role[role if role in by_role else ""].append(lab)
    n_total = int(round((total_s + pre) * rate))
    duck = project.settings.duck
    if duck > 0 and by_role["voice"] and by_role["music"]:
        _mix(g, by_role["music"], n_total, "amus")
        _mix(g, by_role["voice"], n_total, "avoi")
        g.chains.append("[avoi]asplit=2[akey][avo]")
        g.chains.append(f"[amus][akey]sidechaincompress=threshold={_DUCK_THRESHOLD}:"
                        f"ratio={_api._num(1.0 + 19.0 * duck)}:attack=20:release=400[aduck]")
        _mix(g, ["aduck", "avo"] + by_role[""], n_total, "amix")
    else:
        _mix(g, by_role["voice"] + by_role["music"] + by_role[""], n_total, "amix")
    # Сумма клипов (normalize=0) могла выйти за 0 dBFS — ограничитель;
    # latency=1 возвращает его задержку, сэмплы остаются на местах.
    trim = (f",atrim=start_sample={int(round(pre * rate))},asetpts=PTS-STARTPTS"
            if pre > 0 else "")
    g.chains.append(f"[amix]alimiter=limit={_LIMIT}:level=0:latency=1{trim}[aout]")


def build_source(project, video=True, audio=True, subs=None, tonemap=None, window=None):
    """Граф проекта без кодирования: SourceGraph или None, если собирать
    нечего. video/audio=False выбрасывают соответствующую часть.

    tonemap — HDR-куски в SDR: {source_key(файл): цепочка фильтров}
    (hdr_tonemap.tonemap_filters). Цепочка встаёт первой, на кадр исходника:
    субтитры потом рисуются уже в SDR, а куски HDR и SDR файлов склеиваются
    в одном цветовом пространстве.

    subs — вшивание субтитров: {source_key(файл): фильтр subtitles=…}. Куски
    этих файлов получают фильтр на кадре исходника (до масштаба под проект)
    и во времени исходника: входной -ss обнуляет метки, а реплики фильтр
    ищет по времени самого файла субтитров.

    window — (t0, t1): только этот отрезок проекта, метки с нуля (звук
    просмотра, превью, кадр); по полному проекту, а не по excerpt."""
    total = project.duration()
    w0, w1 = 0.0, total
    if window is not None:
        w0, w1 = max(0.0, float(window[0])), min(float(window[1]), total)
    if w1 - w0 <= _api._EPS:
        return None
    w, h, fps = project.output_format()
    rate = _api.fps_expr(fps)
    bg = _api.ff_color(project.settings.background)
    g = _Graph()
    vout = None
    total_s = w1 - w0
    if video and project.has_video():
        g0, g1 = _fr(w0, fps), _fr(w1, fps)
        if g1 > g0:
            items = _main_items(project, fps)
            r0, r1 = _render_range(items, g0, g1)
            cur = _video(g, project, w, h, fps, rate, bg, r0, r1, subs, tonemap, items)
            ass = _text_file(project, r0 / fps, r1 / fps, w, h) if project.texts else None
            if ass:
                from ffmpeg_env import escape_filter_path
                import karaoke.style
                out = g.label("t")
                # Метки — время проекта на время вшивания (текст в ASS — в
                # нём же), затем снова с нуля.
                g.chains.append(f"[{cur}]setpts=PTS-STARTPTS+{_api._num(r0 / fps)}/TB,"
                                f"subtitles=filename='{escape_filter_path(ass)}':"
                                f"fontsdir='{escape_filter_path(karaoke.style.FONT_DIR)}',"
                                f"setpts=PTS-STARTPTS[{out}]")
                cur = out
            if (r0, r1) != (g0, g1):
                out = g.label("w")
                g.chains.append(f"[{cur}]trim=start_frame={g0 - r0}:end_frame={g1 - r0},"
                                f"setpts=PTS-STARTPTS[{out}]")
                cur = out
            vout = cur
            total_s = (g1 - g0) / fps
    parts = []
    if audio:
        parts = [c for c in project.audio_parts()
                 if c.end > w0 + _api._EPS and c.start < w1 - _api._EPS]
    pre = min(w0, _DUCK_PREROLL_S) if parts and _ducking(project, parts) else 0.0
    if pre > 0:
        parts = [c for c in project.audio_parts()
                 if c.end > w0 - pre + _api._EPS and c.start < w1 - _api._EPS]
    if vout is None and not parts:
        return None
    if vout is not None:
        _name_vout(g, vout)
    if parts:
        _audio(g, project, parts, w0, w1, total_s, pre)
    return _api.SourceGraph(g.inputs, ";".join(g.chains), vout is not None, bool(parts),
                            total_s, w, h, fps)


def _name_vout(g, label):
    """Выход картинки — [vout]: последняя цепочка, которая даёт label,
    переименовывается; одиночный кусок — через null, как раньше."""
    tail = f"[{label}]"
    for i in range(len(g.chains) - 1, -1, -1):
        if g.chains[i].endswith(tail):
            if label.startswith("v") and label[1:].isdigit():
                g.chains.append(f"[{label}]null[vout]")
            else:
                g.chains[i] = g.chains[i][:-len(tail)] + "[vout]"
            return


def loudnorm_filter(target, measured=None):
    """loudnorm к target LUFS (TP −1.5, LRA 11). measured — замер первого
    прохода (print_format=json: input_i, input_tp, input_lra,
    input_thresh, target_offset): тогда нормализация линейная, без
    «дыхания» однопроходного режима."""
    f = f"loudnorm=I={_api._num(target)}:TP=-1.5:LRA=11"
    if measured:
        try:
            vals = {k: float(measured[k]) for k in ("input_i", "input_tp", "input_lra",
                                                     "input_thresh", "target_offset")}
        except (KeyError, TypeError, ValueError):
            return f
        f += (f":measured_I={_api._num(vals['input_i'])}:measured_TP={_api._num(vals['input_tp'])}"
              f":measured_LRA={_api._num(vals['input_lra'])}"
              f":measured_thresh={_api._num(vals['input_thresh'])}"
              f":offset={_api._num(vals['target_offset'])}:linear=true")
    return f


def build_export(project, out_path, ffmpeg, video_args, audio_args=None, subs=None,
                 tonemap=None, loudnorm=None):
    """Команда ffmpeg для сборки проекта.

    Возвращает (cmd, graph, duration): graph — граф фильтров (его кладут в
    файл и передают через -/filter_complex, если команда длинная), duration —
    длина итога для прогресса. None, если собирать нечего. subs и tonemap —
    как у build_source. Целевая громкость проекта (settings.loudness) —
    loudnorm на выходе звука; loudnorm — замер первого прохода (см.
    loudnorm_filter), без него нормализация однопроходная."""
    audio_args = audio_args or ["-c:a", "aac", "-b:a", "192k"]
    src = build_source(project, subs=subs, tonemap=tonemap)
    if src is None:
        return None
    graph, amap = src.graph, "[aout]"
    if src.audio and project.settings.loudness is not None:
        graph += (f";[aout]{loudnorm_filter(project.settings.loudness, loudnorm)},"
                  f"aresample={_api._AUDIO_RATE}[anorm]")
        amap = "[anorm]"
    cmd = [ffmpeg, "-y", "-hide_banner"] + src.input_args()
    cmd += ["-filter_complex", graph]
    if src.video:
        cmd += ["-map", "[vout]"] + list(video_args)
        if "-pix_fmt" not in video_args:
            cmd += ["-pix_fmt", "yuv420p"]
    if src.audio:
        cmd += ["-map", amap] + list(audio_args)
    else:
        cmd += ["-an"]
    cmd += ["-t", _api._num(src.duration), str(out_path)]
    return cmd, graph, src.duration
