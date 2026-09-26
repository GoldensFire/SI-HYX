# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SiqPackage: extract_media. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


def extract_media(self, ref_name: str) -> str | None:
    """Extract a media entry to the temp dir and return the local path.

        Streams from the zip to disk in 1 MB chunks — avoids loading the entire
        file (up to 10 MB) into Python heap before writing.  The result is cached
        so subsequent calls for the same entry are free.
        """
    fname = _api._unquote(ref_name)
    zpath = self._media_map.get(fname) or self._media_map.get(fname.split('/')[-1])
    if not zpath: return None

    # Cache hit — return immediately if the extracted file still exists.
    if zpath in self._extract_cache:
        p = self._extract_cache[zpath]
        if _api.os.path.exists(p): return p

    if self._tmp_dir is None:
        self._tmp_dir = _api.tempfile.mkdtemp(prefix='sigame_')

    orig_name = _api._unquote(zpath.split('/')[-1])
    ext = orig_name[orig_name.rfind('.'):] if '.' in orig_name else ''
    # Имя берётся из недоверенного архива: оставляем в расширении только
    # буквы/цифры/точку, чтобы разделители пути и «..» не вытащили запись за
    # пределы tmp_dir (zip-slip). Само имя файла полностью контролируем мы.
    ext = _api.re.sub(r'[^A-Za-z0-9.]', '', ext)[:12]
    self._file_counter += 1
    out = _api.os.path.join(self._tmp_dir, f"media_{self._file_counter}{ext}")

    def _do_extract(zf):
        with zf.open(zpath) as src, open(out, 'wb') as dst:
            _api._shutil.copyfileobj(src, dst, length=1 << 20)  # 1 MB chunks

    try:
        _do_extract(self._zip)
        self._extract_cache[zpath] = out
        return out
    except Exception:
        # Stale zip handle (e.g. after a rewrite) — reopen once and retry.
        try:
            if self._zip is not None:
                try: self._zip.close()
                except Exception: pass
            self._zip = _api.zipfile.ZipFile(self.path, 'r')
            _do_extract(self._zip)
            self._extract_cache[zpath] = out
            return out
        except Exception as e2:
            _api._logger.warning(f"[extract] {e2}")
            return None

def find_q_idx(self, rnd_idx: int, theme_idx: int, price: int) -> int:
    """Return the list index of a question by price. O(1) via _q_index.
        Raises ValueError if not found (mirrors list.index() contract)."""
    q_idx = self._q_index.get((rnd_idx, theme_idx, price))
    if q_idx is not None:
        return q_idx
    # Fallback: linear scan (stale index after manual edits without full reload)
    try:
        for i, q in enumerate(self.rounds[rnd_idx]["themes"][theme_idx]["questions"]):
            if q["price"] == price:
                return i
    except (IndexError, KeyError):
        pass
    raise ValueError(f"price={price} not found in rnd={rnd_idx} theme={theme_idx}")

def find_question(self, rnd_idx: int, theme_idx: int, price: int) -> dict | None:
    """Find a question object by round/theme/price. O(1) via index."""
    try:
        q_idx = self._q_index.get((rnd_idx, theme_idx, price))
        if q_idx is not None:
            return self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
        # Fallback: linear scan (index stale after manual edits)
        for q in self.rounds[rnd_idx]["themes"][theme_idx]["questions"]:
            if q["price"] == price:
                return q
    except Exception:
        pass
    return None

def rebuild_index_for_theme(self, rnd_idx: int, theme_idx: int):
    """Rebuild _q_index and _qs_price_map for one theme after an in-memory
        question reorder.  O(n) where n = questions in that theme.
        Must be called whenever self.rounds[r]["themes"][t]["questions"] is
        mutated without going through _parse_rounds (e.g. drag-reorder)."""
    try:
        qs = self.rounds[rnd_idx]["themes"][theme_idx]["questions"]
    except (IndexError, KeyError):
        return
    # Rebuild _q_index entries for this theme
    for q_idx, q in enumerate(qs):
        self._q_index[(rnd_idx, theme_idx, q["price"])] = q_idx
    # Rebuild _qs_price_map entry for this questions list
    _api._qs_price_map[id(qs)] = {q["price"]: i for i, q in enumerate(qs)}

def _save_xml(self, root, ns_url: str):
    """Convenience wrapper: serialise *root* and rewrite the zip.
        Replaces the 13+ call-sites of _xml_to_bytes + _rewrite_zip."""
    return self._rewrite_zip(self._xml_to_bytes(root, ns_url))

def _reload_rounds(self):
    """Re-parse rounds from the current zip (used after undo/redo restores XML)."""
    try:
        root, _ns, tag = self._load_xml_root()
        self.rounds, self.total_duration = self._parse_rounds(root, tag)
    except Exception as e:
        _api._logger.warning(f"[reload_rounds] {e}")

def _rewrite_zip(self, new_xml_bytes: bytes):
    """Repack the SIQ zip replacing content.xml with new_xml_bytes."""
    tmp = self.path + ".edit_tmp"
    try:
        # Close self._zip BEFORE opening self.path for reading.
        # On Windows an open ZipFile holds a file lock that prevents os.replace().
        if self._zip is not None:
            self._zip.close(); self._zip = None

        # Invalidate the XML parse cache and nav cache — the zip content changes after this.
        self._xml_cache = None
        self._xml_nav   = None

        with _api.zipfile.ZipFile(self.path, 'r') as zin:
            with _api.zipfile.ZipFile(tmp, 'w') as zout:
                for info in zin.infolist():
                    # Clear Hidden/System bits
                    if info.create_system == 0:
                        dos_attr = (info.external_attr >> 16) & 0xFFFF
                        dos_attr &= ~0x02; dos_attr &= ~0x04
                        info.external_attr = (info.external_attr & 0x0000FFFF) | (dos_attr << 16)
                    if info.filename == 'content.xml':
                        # XML is text — worth compressing
                        xml_info = _api.zipfile.ZipInfo('content.xml')
                        xml_info.compress_type = _api.zipfile.ZIP_DEFLATED
                        xml_info.external_attr = info.external_attr
                        zout.writestr(xml_info, new_xml_bytes)
                    else:
                        # Media (MP3/MP4/AVIF/…) is already compressed —
                        # stream the raw compressed bytes directly without
                        # buffering the entire file in memory.
                        with zin.open(info) as src, zout.open(info, 'w') as dst:
                            _api._shutil.copyfileobj(src, dst, length=1 << 20)

        # Atomically swap the rewritten archive into place: clears a possible
        # read-only bit, retries while the file is transiently locked, then
        # falls back to an in-place overwrite copy (see _safe_replace).
        _api._safe_replace(tmp, self.path)

        # Restore normal file permissions and clear Hidden attribute on Windows
        try:
            _api.os.chmod(self.path, _api._stat.S_IWRITE | _api._stat.S_IREAD)
        except Exception:
            pass
        try:
            FILE_ATTRIBUTE_HIDDEN = 0x02
            attrs = _api._ctypes.windll.kernel32.GetFileAttributesW(self.path)
            if attrs != -1 and (attrs & FILE_ATTRIBUTE_HIDDEN):
                _api._ctypes.windll.kernel32.SetFileAttributesW(
                    self.path, (attrs & ~FILE_ATTRIBUTE_HIDDEN) | 0x80)
        except Exception:
            pass

        self._zip = _api.zipfile.ZipFile(self.path, 'r')
        # Rebuild the size map so mp3_duration probes stay accurate.
        self._zip_sizes = {info.filename: info.file_size
                           for info in self._zip.infolist()}
        return True
    except Exception as e:
        _api._logger.warning(f"[save_siq] {e}")
        if _api.os.path.exists(tmp):
            try: _api.os.remove(tmp)
            except Exception: pass
        if self._zip is None:
            try: self._zip = _api.zipfile.ZipFile(self.path, 'r')
            except Exception: pass
        return False

def _load_xml_root(self):
    # Fast path: cache is explicitly invalidated by _rewrite_zip /
    # add_media_to_question whenever the underlying XML changes,
    # so a non-None cache is always up-to-date — no need to re-read
    # or hash the full content.xml bytes here.
    if self._xml_cache is not None:
        root, ns_url, tag = self._xml_cache
        return root, ns_url, tag
    raw_bytes = self._zip.read('content.xml')
    xml_bytes = raw_bytes[3:] if raw_bytes.startswith(b'\xef\xbb\xbf') else raw_bytes
    root = _api._et_fromstring(xml_bytes)
    ns_url = root.tag.split('}')[0][1:] if '{' in root.tag else ''
    tag = _api._make_tag_fn(ns_url)
    self._xml_cache = (root, ns_url, tag)
    self._xml_nav = None   # nav cache tied to root object — reset on new parse
    return root, ns_url, tag
