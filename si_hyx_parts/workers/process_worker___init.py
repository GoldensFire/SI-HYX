# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: __init__. Public namespace: workers."""
import workers as _api


def __init__(self, queue_ref, settings, removed_ids=None):
    super(_api.ProcessWorker, self).__init__()
    self.queue = queue_ref
    self.settings = settings
    self.stop_flag = False
    # Живой набор iid'ов, удалённых пользователем из очереди во время
    # обработки (тот же объект-множество, что и у MediaTab._removed_ids) —
    # позволяет прервать УЖЕ идущий ffmpeg для конкретного файла, а не
    # только не начинать ещё не стартовавшие (см. cancel_check в
    # run_ffmpeg_capture).
    self.removed_ids = removed_ids if removed_ids is not None else set()
    self.svt_available = _api.require_svt()
    self._img_pool = None  # QThreadPool для параллельной обработки изображений
    self._active_count = 0
    self._active_lock = _api.threading.Lock()
    self._max_threads = 1
    self._priority_flag = self._priority_creationflag(settings.get('priority', 'normal'))
