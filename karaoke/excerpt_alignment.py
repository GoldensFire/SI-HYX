"""Bounded audio windows and recovery of complete verses after aligner omissions."""
from dataclasses import replace
from difflib import SequenceMatcher
import hashlib
import json
from xml.etree import ElementTree as ET

from chiptune.runtime import run_process
from .acoustic_excerpt import candidates, select
from .budget import run as budget_run
from .lyric_versions import phonetic_key
from .model import Unit
from .rejections import SourceRejected
from .ttml import read_ttml


def recover(lines, anchors, original, minimum):
    """A missing line splits a verse; it never receives an invented interval."""
    rows, cursor = [], 0
    for line in lines:
        matches = [(SequenceMatcher(None, phonetic_key(original[row['line_index']]),
                                     phonetic_key(line.text), autojunk=False).ratio(), i)
                   for i, row in enumerate(anchors) if i >= cursor
                   and line.start >= row['start'] - .15 and line.end <= row['end'] + .15]
        good = [(score, i) for score, i in matches if score >= .9]
        if not good:
            continue
        _, index = max(good, key=lambda pair: (pair[0], -pair[1]))
        anchor = anchors[index]
        rows.append({'line_index': anchor['line_index'],
                     'start': max(anchor['start'], line.start),
                     'end': min(anchor['end'], line.end), 'line': line})
        cursor = index + 1
    return select(rows, minimum)


def payload_for(lines):
    root = ET.Element('tt')
    body = ET.SubElement(root, 'body')
    for line in lines:
        p = ET.SubElement(body, 'p', begin=f'{line.start:.6f}s', end=f'{line.end:.6f}s')
        for unit in line.units:
            ET.SubElement(p, 'span', begin=f'{unit.start:.6f}s',
                          end=f'{unit.end:.6f}s').text = unit.text
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def align_group(python, group, original, work, minimum, *, stopped, log):
    lyrics, prepared, output = work / 'lyrics.txt', work / 'phrases.json', work / 'timed.ttml'
    lyrics.write_text('\n'.join(original[row['line_index']] for row in group), encoding='utf-8')
    prepared.write_text(json.dumps(group, ensure_ascii=False), encoding='utf-8')
    output.unlink(missing_ok=True)
    code, diagnostic = budget_run('выравнивание текста', run_process,
        [str(python), '-I', '-X', 'utf8', '-m', 'lyric_align.cli', '--segments', str(prepared),
         str(lyrics), '--pairing', '1', '-f', 'ttml', '-o', str(output)], 1800, stopped=stopped)
    (work / 'diagnostics.txt').write_text(diagnostic, encoding='utf-8')
    if code or not output.is_file():
        raise ValueError('lyric-align: ' + diagnostic[-500:])
    rows = recover(read_ttml(output.read_bytes()), group, original, minimum)
    if rows:
        if len(rows) != len(group):
            log('Караоке: после пропуска строки найдена другая полностью выровненная строфа.')
        return rows
    return []


def windows(duration, size=60, overlap=25):
    start = 0
    while start < duration:
        end = min(duration, start + size)
        yield start, end
        if end >= duration:
            break
        start = end - overlap


def run(python, source, original, languages, directory, work, info, minimum, details,
        acoustic_phrases, *, stopped, log):
    from config import FFMPEG, FFPROBE
    code, output = budget_run('определение длительности аудио', run_process,
        [str(FFPROBE), '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(source)], 30, stopped=stopped)
    if code:
        raise ValueError('Не удалось определить длительность: ' + output[-300:])
    duration = float(output.strip())
    errors = []
    for number, (start, end) in enumerate(windows(duration, size=max(60, minimum + 30)), 1):
        stopped.check()
        part = work / f'window-{start:g}-{end:g}'
        part.mkdir(exist_ok=True)
        audio = part / 'source.wav'
        log(f'Караоке: проверяю окно {start:g}–{end:g} с исходной записи.')
        code, diagnostic = budget_run('подготовка окна аудио', run_process,
            [str(FFMPEG), '-v', 'error', '-y', '-ss', str(start), '-i', str(source),
             '-t', str(end - start), '-ac', '2', '-ar', '44100', str(audio)], 60, stopped=stopped)
        if code:
            raise ValueError('Окно аудио: ' + diagnostic[-300:])
        sha = hashlib.sha256(audio.read_bytes()).hexdigest()
        window_details = {}
        try:
            anchors = acoustic_phrases(python, audio, sha, original, languages, directory,
                stopped=stopped, log=log, info=info, excerpt_duration=minimum,
                details=window_details, retain_candidates=True)
            for group in candidates(anchors, minimum):
                try:
                    rows = align_group(python, group, original, part, minimum, stopped=stopped, log=log)
                except ValueError as error:
                    log(f'Караоке: выравнивание строфы: {str(error)[:160]}')
                    continue
                if not rows:
                    continue
                lines = [replace(row['line'], start=row['line'].start + start,
                                 end=row['line'].end + start,
                                 units=[Unit(u.start + start, u.end + start, u.text)
                                        for u in row['line'].units]) for row in rows]
                details.update(window_details, analysis_window=[start, end],
                    analysis_windows_attempted=number,
                    confirmed_excerpt=[rows[0]['start'] + start, rows[-1]['end'] + start],
                    selected_lyric_indices=[row['line_index'] for row in rows],
                    aligned_lyrics_lines=len(lines))
                return lines, payload_for(lines)
        except (SourceRejected, ValueError) as error:
            errors.append(str(error))
            log(f'Караоке: окно {start:g}–{end:g} не подошло: {str(error)[:160]}')
            continue
        errors.append('Нет полностью выровненной строфы')
    raise SourceRejected('Нет полного подтверждённого фрагмента после проверки окон: ' +
                         '; '.join(errors[-2:]))
