"""On-disk settings / datasets / tabs and the background save worker."""

from .qt import _logger, _queue, _threading, json, Path, QTimer

SAVE_FILE = Path.home() / ".sigame_stats_save.json"


TABS_FILE = Path.home() / ".sigame_stats_tabs.json"


SETTINGS_FILE = Path.home() / ".sigame_stats_settings.json"


def save_settings(settings: dict):
    try:
        with open(SETTINGS_FILE,"w",encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False)
    except Exception: pass


def load_settings() -> dict:
    if not SETTINGS_FILE.exists(): return {}
    try:
        with open(SETTINGS_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


_SAVE_QUEUE: "_queue.Queue[str | None]" = _queue.Queue(maxsize=1)


def _save_worker():
    while True:
        payload = _SAVE_QUEUE.get()
        if payload is None:
            break
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                f.write(payload)
        except Exception as e:
            _logger.warning(f"[save] {e}")


_threading.Thread(target=_save_worker, daemon=True, name="ds-writer").start()


_SAVE_LAST_HASH: int = 0   # hash of last enqueued payload — skip write if unchanged


def save_datasets(datasets):
    # Serialize on the calling thread (CPU-only, no I/O),
    # then hand off to the single background writer.
    global _SAVE_LAST_HASH
    data = [{"pkg_name": d["pkg_name"], "stats": d["stats"],
             "rounds": d["rounds"], "pkg_size": d.get("pkg_size",""),
             "tab_id": d.get("tab_id",0),
             "total_duration_sec": d.get("total_duration_sec",0),
             "siq_path": d.get("siq_path",""),
             "_view_mode": "tile"}
            for d in datasets]
    payload = json.dumps(data, ensure_ascii=False)
    payload_hash = hash(payload)
    if payload_hash == _SAVE_LAST_HASH:
        return   # identical to last write — skip I/O entirely
    _SAVE_LAST_HASH = payload_hash
    # Drop any pending payload (last-write-wins), then enqueue the new one.
    try: _SAVE_QUEUE.get_nowait()
    except _queue.Empty: pass
    try: _SAVE_QUEUE.put_nowait(payload)
    except _queue.Full: pass


def load_datasets():
    if not SAVE_FILE.exists(): return []
    try:
        with open(SAVE_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return []


def save_tabs(tabs):
    try:
        with open(TABS_FILE,"w",encoding="utf-8") as f:
            json.dump(tabs, f, ensure_ascii=False, indent=2)
    except Exception: pass


def load_tabs():
    if not TABS_FILE.exists(): return [{"id":0,"name":"Все"}]
    try:
        with open(TABS_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return [{"id":0,"name":"Все"}]


def _notif_reset(mw, delay: int = 3100):
    """Reset the save-notification label after *delay* ms."""
    QTimer.singleShot(delay, lambda: mw._save_notif.setText("✅  Файл сохранён"))


def _schedule_save(mw, delay: int = 400):
    """Debounced save: collapses rapid sequential calls into one write."""
    save_fn = getattr(mw, "_save_after_theme_move", None)
    if save_fn is None:
        return
    timer = getattr(mw, "_save_debounce_timer", None)
    if timer is None:
        timer = QTimer(mw)
        timer.setSingleShot(True)
        timer.timeout.connect(save_fn)
        mw._save_debounce_timer = timer
    timer.start(delay)

__all__ = [
    'SAVE_FILE',
    'SETTINGS_FILE',
    'TABS_FILE',
    '_SAVE_LAST_HASH',
    '_SAVE_QUEUE',
    '_notif_reset',
    '_save_worker',
    '_schedule_save',
    'load_datasets',
    'load_settings',
    'load_tabs',
    'save_datasets',
    'save_settings',
    'save_tabs',
]
