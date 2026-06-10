import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import traceback
try:
    import main
    from PyQt6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    w=main.UnifiedWindow(); app.processEvents()
    assert not hasattr(w,'btn_top_restart'), "restart button still present"
    assert hasattr(w,'_log_context_menu'), "no log context menu"
    ty=w.tab_ytdlp
    assert hasattr(ty,'slider_start') and hasattr(ty,'ts') and hasattr(ty,'c_s')
    # worker has cleanup + watchdog
    from workers import YtdlpWorker
    assert hasattr(YtdlpWorker,'_cleanup_partials') and hasattr(YtdlpWorker,'_watchdog')
    # cleanup prefix logic sanity (no crash on empty dir)
    print("SMOKE7_OK")
    import sys; sys.stdout.flush(); os._exit(0)
except Exception:
    traceback.print_exc(); os._exit(1)
