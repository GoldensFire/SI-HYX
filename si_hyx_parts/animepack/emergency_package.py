"""Write available questions without quotas, network calls or a size ceiling."""
import copy
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import animepack as ap

from .pack_completion import warn
from .package_transaction import archive

FOLDERS = {'image': 'Images', 'audio': 'Audio', 'video': 'Video'}


def _questions(generator, songs, result):
    ready, elements, media = [], [], {}
    bases = [Path(path) for path in (generator.folder,
             getattr(generator, '_recovery_source', '')) if path]
    for candidate in songs:
        try:
            questions = ET.Element('questions')
            ap._append_question(questions, candidate, generator.s)
            question = questions[0]
            body = question.find("./params/param[@name='question']")
            if body is None or not any((item.text or '').strip() for item in body.iter('item')):
                raise ValueError('содержимое вопроса ещё не готово')
            references = {}
            for item in question.iter('item'):
                folder = FOLDERS.get(item.get('type'))
                if folder and item.get('isRef') == 'True':
                    name = (item.text or '').strip()
                    source = next((base / folder / name for base in bases
                                   if name and (base / folder / name).is_file()), None)
                    if source is None or not source.is_file():
                        raise FileNotFoundError(f'нет готового медиа {folder}/{name}')
                    references[f'{folder}/{name}'] = source
            ready.append(candidate)
            elements.append(question)
            media.update(references)
        except Exception as error:
            warn(generator, result, f'Незавершённый вопрос пропущен: {error}')
    return ready, elements, media


def _fallback_xml(settings, elements):
    package = ET.Element('package', {
        'name': settings.title or 'Сгенерировано в SI-HYX',
        'version': '5', 'id': str(ap.uuid.uuid4()),
        'date': ap.date.today().strftime('%d.%m.%Y'), 'xmlns': ap.SIQ_NS})
    info = ET.SubElement(package, 'info')
    authors = ET.SubElement(info, 'authors')
    ET.SubElement(authors, 'author').text = ap.PACK_AUTHOR
    ET.SubElement(info, 'comments').text = f'Сохранено готовых вопросов: {len(elements)}.'
    rounds = ET.SubElement(package, 'rounds')
    per_theme = max(1, int(settings.questions))
    per_round = max(1, int(settings.themes))
    themes = None
    for index in range(0, len(elements), per_theme):
        theme_index = index // per_theme
        if theme_index % per_round == 0:
            round_ = ET.SubElement(rounds, 'round', {'name': f'Раунд {theme_index // per_round + 1}'})
            themes = ET.SubElement(round_, 'themes')
        theme = ET.SubElement(themes, 'theme', {'name': settings.theme_title or 'Аниме'})
        questions = ET.SubElement(theme, 'questions')
        questions.extend(elements[index:index + per_theme])
    return ET.tostring(package, encoding='utf-8', xml_declaration=True)


def _xml(generator, ready, elements, result):
    settings = copy.copy(generator.s)
    settings.questions = max(1, int(settings.questions))
    settings.themes = max(1, int(settings.themes))
    settings.rounds = max(1, int(settings.rounds),
                          math.ceil(len(ready) / (settings.questions * settings.themes)))
    try:
        return ap.build_content_xml(ready, settings)
    except Exception as error:
        warn(generator, result, f'Обычное оформление пака недоступно: {error}. Использую простое.')
        return _fallback_xml(settings, elements)


def _targets(generator, songs, out_path):
    from .pack_summary import pack_title
    try:
        title = pack_title(generator.s.title, getattr(generator.s, 'pack_number', 0), songs,
                           test_number=getattr(generator.s, 'test_pack_number', 0),
                           ignore_test_packs=getattr(generator.s, 'ignore_test_packs', False))
    except Exception:
        title = generator.s.title or 'Сгенерировано в SI-HYX'
    name = ap.safe_filename(title, 'Аниме пак') + '.siq'
    targets = [Path(out_path)] if out_path else []
    if generator.s.out_dir.strip():
        targets.append(Path(generator.s.out_dir.strip()) / name)
    try:
        from utils import default_download_dir
        targets.append(Path(default_download_dir()) / name)
    except Exception:
        pass
    from config import CONFIG_DIR
    targets.append(Path(CONFIG_DIR) / 'partial_packs' / name)
    targets.append(Path(tempfile.gettempdir()) / name)
    return list(dict.fromkeys(targets))


def _extras(generator, songs, result):
    extras = {}
    try:
        from .pack_manifest import MANIFEST_NAME, build
        extras[MANIFEST_NAME] = build(songs)
        from .karaoke_processing import manifest
        extras['karaoke.json'] = manifest(songs)
        from .music_processing import processing_manifest
        extras['chiptune.json'] = processing_manifest(songs, generator.s)
        from .cover_processing import covers_manifest
        extras['covers.json'] = covers_manifest(songs, generator.s)
        # Те же сведения, что кладёт обычная сборка (write_package): без них
        # аварийный пак терял субтитры караоке и описание отрывков серий.
        episodes = [{'file': c.video_out, **c.episode_clip} for c in songs if c.episode_clip]
        if episodes:
            extras['episodes.json'] = ap.json.dumps(episodes, ensure_ascii=False, indent=2)
    except Exception as error:
        warn(generator, result, f'Дополнительные сведения пака: {error}')
    return {name: data for name, data in extras.items() if data}


def _subtitles(generator, songs, result):
    """Karaoke/*.ass готовых вопросов караоке — как в обычной сборке."""
    bases = [Path(path) for path in (generator.folder,
             getattr(generator, '_recovery_source', '')) if path]
    found = {}
    for candidate in songs:
        if candidate.music_effect != 'karaoke' or not candidate.has_video:
            continue
        name = Path(candidate.video_out).stem + '.ass'
        source = next((base / 'Video' / name for base in bases
                       if (base / 'Video' / name).is_file()), None)
        if source is None:
            warn(generator, result, f'Нет субтитров караоке {name}.')
            continue
        found['Karaoke/' + name] = source
    return found


def write(generator, songs, out_path, result):
    ready, elements, media = _questions(generator, songs, result)
    media.update(_subtitles(generator, ready, result))
    xml = _xml(generator, ready, elements, result)
    extras = _extras(generator, ready, result)
    if not ready:
        # Пустой пак со статусом «Готово» хуже честного «Не получилось».
        raise ap.AnimePackError('Готовых вопросов нет — сохранять нечего.')
    errors = []
    for target in _targets(generator, ready, out_path):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = Path(ap.unique_path(target))
            with archive(target, ap.zipfile) as package:
                package.writestr('content.xml', xml, ap.zipfile.ZIP_DEFLATED)
                package.writestr('quality.marker', b'', ap.zipfile.ZIP_STORED)
                package.writestr('generation-errors.json', ap.json.dumps(
                    {'requested': result.requested, 'saved': len(ready), 'warnings': result.warnings},
                    ensure_ascii=False, indent=2), ap.zipfile.ZIP_DEFLATED)
                for name, data in extras.items():
                    package.writestr(name, data, ap.zipfile.ZIP_DEFLATED)
                for name, source in sorted(media.items()):
                    package.write(source, name, ap.zipfile.ZIP_STORED)
            return str(target), ready
        except OSError as error:
            errors.append(f'{target}: {error}')
            warn(generator, result, f'Не удалось записать в {target.parent}: {error}. Пробую другую папку.')
    raise OSError('; '.join(errors))
