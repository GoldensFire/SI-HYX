# -*- coding: utf-8 -*-
"""Non-blocking account quota refresh; no QWidget access from worker threads."""
import queue
import threading
import time
from datetime import datetime, timezone

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QPushButton

from cloudflare_ai_quota import fetch_quota, QuotaError


def build_quota_controls(tab, layout):
    tab.lbl_ai_quota = tab._hint("Квота ИИ: ещё не загружена.")
    tab.lbl_ai_quota.setToolTip(
        "Остаток бесплатных 10 000 нейронов за сутки по всему аккаунту. "
        "Cloudflare обновляет аналитику с задержкой. Сброс в 00:00 UTC. "
        "На платном плане сверх этой квоты возможны списания.")
    tab.btn_ai_quota = QPushButton("Обновить квоту")
    layout.addWidget(tab.lbl_ai_quota, 5, 0, 1, 2)
    layout.addWidget(tab.btn_ai_quota, 6, 1)
    results = queue.Queue()
    state = {"busy": False, "next": 0, "credentials": None, "day": None}

    def credentials():
        return tab._api_key("cloudflare_account_id"), tab._api_key("cloudflare")

    def refresh():
        if state["busy"]:
            return
        keys = credentials()
        state.update(busy=True, credentials=keys, next=time.monotonic() + 60)
        tab.btn_ai_quota.setEnabled(False)
        tab.lbl_ai_quota.setText("Квота ИИ: обновление…")

        def work():
            try:
                result = fetch_quota(*keys)
            except QuotaError as exc:
                result = str(exc)
            except Exception:
                result = "Квота ИИ временно недоступна. Повторите обновление."
            results.put((keys, result))

        threading.Thread(target=work, daemon=True).start()

    def tick():
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            keys, result = results.get_nowait()
        except queue.Empty:
            pass
        else:
            state["busy"] = False
            tab.btn_ai_quota.setEnabled(True)
            if keys == credentials():
                if isinstance(result, dict) and result["day"] == today:
                    tab.lbl_ai_quota.setText(
                        f"Бесплатная квота ИИ: осталось ≈{result['remaining']:,.0f} "
                        f"из 10 000 нейронов. Сброс в 00:00 UTC. "
                        "Данные Cloudflare могут запаздывать.")
                    state["day"] = today
                elif isinstance(result, str):
                    tab.lbl_ai_quota.setText(result)
            else:
                state["next"] = 0
        if state["day"] and state["day"] != today:
            tab.lbl_ai_quota.setText("Квота ИИ: новый день, требуется обновление.")
            state.update(day=None, next=0)
        if tab.chk_ai_art.isChecked() and not state["busy"] and (
                time.monotonic() >= state["next"] or credentials() != state["credentials"]):
            refresh()

    tab.btn_ai_quota.clicked.connect(refresh)
    tab._ai_quota_timer = QTimer(tab)
    tab._ai_quota_timer.timeout.connect(tick)
    tab._ai_quota_timer.start(1000)
