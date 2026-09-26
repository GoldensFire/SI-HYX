# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""UnifiedWindow: _spawn_updater. Public namespace: main."""
import main as _api


def _spawn_updater(self, task_name, register_cmd, ps_path):
    """Запускает апдейтер ВНЕ job-объекта программы. Основной путь —
        Планировщик задач через register.cmd (служба исполняет задачу в своей
        сессии, job родителя на неё не влияет — работает даже в Win Sandbox).
        Фолбэк — обычный detached Popen (+breakaway) для машин без жёсткого job."""
    flags = getattr(_api.subprocess, "CREATE_NO_WINDOW", 0)
    # 1) Планировщик задач (register.cmd сам делает /Create и /Run)
    try:
        # encoding задан явно, как и везде в проекте: без него Python берёт
        # кодировку системной локали (cp1251 на русской Windows, cp1252 на
        # английской) — поведение зависело бы от языка системы пользователя.
        # Вывод здесь не разбирается, важен только returncode; если он всё
        # же понадобится — учесть, что cmd/schtasks пишут в OEM-кодировку
        # консоли, и errors="replace" превратит кириллицу в «?».
        _api.subprocess.run(["cmd", "/c", register_cmd], creationflags=flags,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
        chk = _api.subprocess.run(["schtasks", "/Query", "/TN", task_name],
                             creationflags=flags, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15)
        if chk.returncode == 0:
            self.log("Апдейтер запущен через Планировщик задач (вне job-объекта).")
            return True
        self.log("Планировщик: задача не зарегистрирована — пробую прямой запуск.")
    except Exception as e:
        self.log(f"Планировщик задач недоступен ({e}); пробую прямой запуск.")
    # 2) Фолбэк: detached Popen (+breakaway) — для обычных машин без жёсткого job
    try:
        DETACHED = getattr(_api.subprocess, "DETACHED_PROCESS", 0)
        NEWGRP = getattr(_api.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        BREAKAWAY = getattr(_api.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", ps_path]
        try:
            _api.subprocess.Popen(args, creationflags=DETACHED | NEWGRP | BREAKAWAY, close_fds=True)
        except OSError:
            _api.subprocess.Popen(args, creationflags=DETACHED | NEWGRP, close_fds=True)
        self.log("Апдейтер запущен напрямую (detached).")
        return True
    except Exception as e:
        self.log(f"Не удалось запустить апдейтер: {e}")
        return False
