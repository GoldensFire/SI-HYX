# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Python-объекты Qt, от которых отписываются чужие потоки Qt: первый
disconnectNotify — в главном потоке.

ffmpeg-плагин QtMultimedia подписывает свой AudioRenderer на сигналы
QAudioOutput и удаляет его в СВОЁМ потоке (смена аудиовыхода, смена файла).
~QObject рендерера зовёт QAudioOutput.disconnectNotify, держа мьютекс Qt
(signalSlotLock — пул из 131 мьютекса по адресу объекта). У объекта, созданного
из Python, это виртуальный метод sip: при ПЕРВОМ вызове sip берёт GIL, чтобы
проверить, нет ли переопределения в Python, и запоминает ответ. Если GIL в этот
момент держит поток, которому нужен тот же мьютекс, — вечное зависание.

22.10.2026 так встало окно на «Пробеле» в проекте «Монтажа»: route_player_audio
снял выход у плеера (поток плагина удалял рендерер и ждал GIL), а поток звука
проекта под GIL делал QAudioSink.reset() — тот удалял свои QObject-события и
ждал тот же мьютекс. Повтор в отдельном процессе: без прогрева — зависание
каждый раз, с прогревом — нет.

Прогрев: первый disconnectNotify вызываем сами, в главном потоке, где GIL уже
наш, а мьютексов Qt не держим. Дальше sip ходит быстрым путём, без GIL."""


def _noop(*_args):
    pass


def prime_disconnect_notify(obj):
    """Объект Qt, созданный из Python, с уже проверенным disconnectNotify (см.
    докстроку модуля). Возвращает сам объект."""
    try:
        obj.objectNameChanged.connect(_noop)
        obj.objectNameChanged.disconnect(_noop)
    except Exception:
        pass
    return obj
