"""Short progress in the interface, complete diagnostics in a per-run file."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import threading
import time

from config import CONFIG_DIR

IMPORTANT = ('Отобрано вопросов:', 'Средняя сложность', 'Собираю пакет',
             'Вес пака:', 'Готовые вопросы', 'Остановлено:', 'Внимание:',
             'Видео песен:', 'Караоке: готово', 'Ловушки:', 'Ошибка:',
             'Оставшиеся места', 'Добор по', 'Добор средней:', 'Средняя исправлена:',
             'Каверы отключились', 'Исправляю среднюю', 'Подбор по базе:')


class RunLog:
    def __init__(self, callback, directory=None):
        self.callback = callback
        self.lock = threading.RLock()
        directory = Path(directory) if directory else Path(CONFIG_DIR) / 'generation_logs'
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        self.stream = self.path.open('w', encoding='utf-8')
        self.hidden = Counter()
        self.last_done = -10
        self.last_progress = 0
        self.callback('Генерация началась. Подробности записываются в отдельный журнал.')

    def emit(self, message):
        message = str(message)
        with self.lock:
            if self.stream.closed:
                self.callback(message)
                return
            self.stream.write(datetime.now().strftime('%H:%M:%S ') + message + '\n')
            self.stream.flush()
            if message.startswith(IMPORTANT) or 'Пак не сохранён:' in message:
                self.callback(message)
            elif 'не найден' in message.casefold() or 'нет ' in message.casefold():
                self.hidden['нет подходящего материала'] += 1
            elif any(word in message.casefold() for word in ('ошиб', 'отклон', 'не удалось', 'не скач')):
                self.hidden['отказы источников и проверки качества'] += 1

    def progress(self, done, total, message):
        now = time.monotonic()
        if done == total or done >= self.last_done + 10 or now - self.last_progress >= 30:
            self.last_done, self.last_progress = done, now
            self.callback(f'Готово {done}/{total}. Сейчас: {message or "подбор материала"}.')

    def finish(self, generator, result, elapsed):
        import animepack as ap
        self.callback(f'Общее время: {ap.fmt_elapsed(elapsed)}.')
        with generator._stage_lock:
            stages = [(name, generator._merge_spans(list(spans)))
                      for name, spans in generator._stage_spans.items()]
        stages.sort(key=lambda item: -item[1])
        self.callback('Самые долгие этапы (они выполнялись параллельно):')
        for name, duration in stages[:5]:
            self.callback(f'  {name}: {ap.fmt_elapsed(duration)}')
        if self.hidden:
            self.callback('Повторяющиеся причины: ' + '; '.join(
                f'{name} — {count}' for name, count in self.hidden.items()) + '.')
        if result.planned:
            differences = [f'{ap.KIND_TITLES.get(kind, kind)}: {result.actual.get(kind, 0)}/{count}'
                           for kind, count in result.planned.items()
                           if result.actual.get(kind, 0) != count]
            if differences:
                self.callback('Получилось / запрошено: ' + '; '.join(differences) + '.')
        if result.path:
            self.callback(f'Пак сохранён: {result.path}')
        else:
            self.callback('Готового файла пака пока нет. Причина указана в сообщении об ошибке.')
        self.callback(f'Полный журнал: {self.path}')
        with self.lock:
            self.stream.close()


def start(generator):
    import animepack as ap
    log = RunLog(generator._log, Path(ap.SHIKI_CACHE_FILE).parent / 'generation_logs')
    generator._run_log = log
    log.callback(f'План: {generator.s.total_questions} вопросов; '
                 f'общая средняя {generator.s.level_avg or "любая"}. '
                 'Категории со своей средней считаются отдельно.')
    generator._log = log.emit
    progress = generator._progress

    def update(done, total, message):
        progress(done, total, message)
        log.progress(done, total, message)

    generator._progress = update
    return log
