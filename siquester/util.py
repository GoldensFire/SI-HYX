"""Small shared helpers: layout tightening, screen scaling, XML/price lookups, label/checkbox helpers."""

from .qt import *

def _tight(layout):
    """Set zero margins and spacing on *layout* in one call."""
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    return layout


_SCREEN_SCALE_CACHE: float | None = None


def _screen_scale() -> float:
    """Return a scale factor based on primary screen width (1.0 at 1920px). Result is cached."""
    global _SCREEN_SCALE_CACHE
    if _SCREEN_SCALE_CACHE is not None:
        return _SCREEN_SCALE_CACHE
    try:
        screen = QApplication.primaryScreen()
        if screen:
            _SCREEN_SCALE_CACHE = max(0.75, min(1.5, screen.availableGeometry().width() / 1920.0))
            return _SCREEN_SCALE_CACHE
    except Exception:
        pass
    _SCREEN_SCALE_CACHE = 1.0
    return 1.0


def fmt_dur(sec):
    sec=int(sec); h,rem=divmod(sec,3600); m,s=divmod(rem,60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


_qs_price_map: dict[int, dict[int, int]] = {}


def _q_idx(qs: list, price: int) -> int:
    """Return the index of the question with the given price in *qs*.
    O(1) when *qs* is a list registered in _qs_price_map (built by _parse_rounds).
    Falls back to O(n) linear scan for copied/detached lists.
    Raises ValueError when price is not found."""
    pm = _qs_price_map.get(id(qs))
    if pm is not None:
        idx = pm.get(price)
        if idx is not None:
            return idx
    # Fallback linear scan
    for i, q in enumerate(qs):
        if q.get("price") == price:
            return i
    raise ValueError(f"price {price} not found in question list")


_unquote = functools.lru_cache(maxsize=512)(urllib.parse.unquote)


def _make_tag_fn(ns_url: str):
    """Return a tag-name resolver for the given XML namespace.

    Uses a dict cache so repeated calls for the same tag name are O(1)
    dict lookups instead of f-string allocations.  142 tag() calls per
    pack parse are reduced to at most ~15 unique string allocations.
    """
    if not ns_url:
        return lambda t: t
    prefix = f'{{{ns_url}}}'
    _cache: dict[str, str] = {}
    def _tag(t: str, _c=_cache, _p=prefix) -> str:
        r = _c.get(t)
        if r is None:
            r = _p + t
            _c[t] = r
        return r
    return _tag


@functools.lru_cache(maxsize=512)
def _parse_hms(s: str) -> float | None:
    """Parse 'HH:MM:SS' or 'MM:SS' string to seconds. Returns None on failure.
    lru_cache: the same duration strings repeat across questions in a pack."""
    try:
        parts = s.strip().split(":")
        if len(parts) == 3:
            return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0])*60 + int(parts[1])
    except Exception:
        pass
    return None


def _xml_nav_q(siq, rnd: int, th: int, q_idx: int):
    """Return (root, ns_url, tag, q_el) using SiqPackage's cached nav.

    Replaces the repeated raw pattern:
        root, ns_url, tag = siq._load_xml_root()
        rnds = root.findall(f'.//{tag("round")}')
        ths  = rnds[rnd].findall(...)
        q_els = ths[th].findall(...)
        q_el = q_els[q_idx]

    _nav_to_question already caches rounds/themes/questions lists between
    calls so repeated XML navigation on the same root is O(1).
    """
    root, ns_url, tag = siq._load_xml_root()
    q_el, tag = siq._nav_to_question(root, tag, rnd, th, q_idx)
    return root, ns_url, tag, q_el


def _lbl(html, style):
    l = QLabel(html); l.setStyleSheet(style); return l


def _style_cb(cb):
    cb.setStyleSheet(
        "QComboBox{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 8px;font-size:12px;}"
        "QComboBox QAbstractItemView{background:#1e1e2e;color:#cdd6f4;selection-background-color:#313244;}")


def _find_mw(widget):
    """Walk up the parent chain to find siquester's own MainWindow.

    QWidget.window() finds the nearest top-level ancestor — but when SiQuester
    is embedded as a SI-HYX tab (siquester_tab.py), its MainWindow is
    reparented as a plain child widget (Qt.WindowType.Widget) so it's no
    longer a "window", and .window() bubbles past it to the SI-HYX host
    window instead (which has no .datasets/_save_notif/etc). Duck-type our
    way up the parent chain instead so this works both standalone and
    embedded.
    """
    p = widget
    while p is not None:
        if hasattr(p, "datasets") and hasattr(p, "_save_notif"):
            return p
        p = p.parentWidget()
    return widget.window()


__all__ = [
    '_SCREEN_SCALE_CACHE',
    '_find_mw',
    '_lbl',
    '_make_tag_fn',
    '_parse_hms',
    '_q_idx',
    '_qs_price_map',
    '_screen_scale',
    '_style_cb',
    '_tight',
    '_unquote',
    '_xml_nav_q',
    'fmt_dur',
]
