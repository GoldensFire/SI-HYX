"""Publishing prepared questions takes precedence over targets and enrichment."""
import time

import animepack as ap


def warn(generator, result, message):
    message = str(message)
    if message not in result.warnings:
        result.warnings.append(message)
        generator.log('Внимание: ' + message)


def optional(generator, result, label, action):
    try:
        return action()
    except Exception as error:
        warn(generator, result, f'{label}: {error}. Готовый пак сохраняется.')


def report_targets(generator, songs, result):
    actual = ap.Counter(c.kind for c in songs)
    shortages = [f'{ap.KIND_TITLES.get(kind, kind)} {actual[kind]}/{want}'
                 for kind, want in result.planned.items() if actual[kind] != want]
    if shortages:
        warn(generator, result, 'Фактический состав: ' + ', '.join(shortages) +
             '. Сохраняю все готовые вопросы.')
    from .level_avg import short_pack_average_error
    error = short_pack_average_error(generator.s, songs)
    if error:
        error = error.replace('пакет не создан.', 'сохраняю фактическую среднюю.')
        error = error.replace('Готовые вопросы сохраняются для точечного добора.',
                              'Сохраняю все готовые вопросы.')
        warn(generator, result, error)


def after_error(generator, songs, out_path, result, error):
    """Skip failed preparation and publish a playable archive immediately."""
    if result.path:
        warn(generator, result, f'Ошибка после записи пака: {error}')
        return
    if not songs:
        # Досрочное сохранение — только замена провалу. Сохранять нечего, и
        # вкладка покажет «Не получилось» с настоящей причиной.
        raise error
    warn(generator, result, f'Ошибка генерации: {error}. Собираю готовые вопросы.')
    result.aborted = True
    from .emergency_package import write
    try:
        result.path, ready = write(generator, songs, out_path, result)
    except Exception as packaging_error:
        from .assembly_recovery import keep_or_raise
        text = (str(error) if isinstance(error, ap.AnimePackError)
                else f'{type(error).__name__}: {error}')
        keep_or_raise(generator, songs, ap.AnimePackError(
            f'{text}\nАвтоматическая запись пака не удалась: {packaging_error}'))
    result.songs = ready
    result.actual = dict(ap.Counter(c.kind for c in ready))
    result.failed_media = getattr(generator, '_failed_media', 0)
    generator.log(f'Пак сохранён после ошибки: {len(ready)} вопросов; {result.path}')
    from .title_rotation import record
    optional(generator, result, 'История кадров', lambda: generator.save_frames_history(ready))
    optional(generator, result, 'История названий', lambda: record(ready))


def finish(generator, result, started, readable_log=None):
    if not result.songs and not result.path:
        result.songs = list(getattr(generator, '_selected_songs', ()))
    result.actual = dict(ap.Counter(c.kind for c in result.songs))
    optional(generator, result, 'Очистка', generator.cleanup)
    result.elapsed = time.monotonic() - started
    optional(generator, result, 'Статистика Gemini', generator.log_gemini_spent)
    from .local_visual_ocr import summary
    optional(generator, result, 'Статистика OCR', lambda: summary(generator))
    optional(generator, result, 'Замеры времени', lambda: generator.log_stage_times(result.elapsed))
    if readable_log is not None:
        optional(generator, result, 'Итоговый журнал',
                 lambda: readable_log.finish(generator, result, result.elapsed))
