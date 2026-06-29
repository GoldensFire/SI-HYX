"""The SiqPackage model: parse / edit / repack a .siq archive (incl. the robust _safe_replace save)."""

from .qt import *
from .constants import *
from .util import *
from .media import *

def _safe_replace(tmp: str, dst: str) -> None:
    """Replace *dst* with the freshly-written *tmp*, as robustly as Windows allows.

    Mirrors the original SIQuester 6.8.0 save flow
    (QDocument.SaveInternalAsync → File.Replace → File.Copy fallback):

      1. Clear a possible read-only bit on the destination — downloaded ``.siq``
         files frequently carry it, and ``os.replace`` over a read-only target
         is itself denied with WinError 5.
      2. Retry ``os.replace`` a few times. Right after we rewrite the archive the
         destination can be briefly locked by antivirus, the search indexer or a
         cloud-sync client (OneDrive — and the package here lives on the Desktop,
         which is usually a synced folder). A short backoff lets that clear.
      3. If the atomic replace still fails with a permission/sharing error
         (WinError 5 *Access denied* / WinError 32 *being used by another
         process* — the equivalents of .NET's ``UnauthorizedAccessException`` /
         ``IOException``), fall back to a **non-atomic in-place overwrite copy**,
         exactly like the original's "old unsafe method". An overwrite only needs
         write access to the existing file, not the right to delete its directory
         entry, so it succeeds against a lingering shared read handle or
         Controlled-Folder-Access protection that blocks the rename.

    Raises the last error only if even the overwrite copy fails (target truly
    locked for writing); the caller logs it and removes *tmp*.
    """
    def _clear_readonly():
        try:
            os.chmod(dst, _stat.S_IWRITE | _stat.S_IREAD)
        except OSError:
            pass

    _clear_readonly()

    last_err: OSError | None = None
    for _attempt in range(5):
        try:
            os.replace(tmp, dst)
            return
        except OSError as _e:        # PermissionError (WinError 5/32) ⊂ OSError
            last_err = _e
            _time.sleep(0.2 * (_attempt + 1))

    # Atomic replace impossible — fall back to overwriting the file in place.
    # An overwrite only needs write access to the *existing* file, not the right
    # to delete its directory entry, so it beats a lingering shared read handle
    # or Controlled-Folder-Access that blocks the rename. The lock is still
    # often transient (OneDrive/AV/indexer), so retry this fallback too, clearing
    # the read-only bit before every attempt and backing off between tries.
    for _attempt in range(5):
        try:
            _clear_readonly()
            _shutil.copyfile(tmp, dst)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        except OSError as _e:
            last_err = _e
            _time.sleep(0.3 * (_attempt + 1))

    # Truly locked for writing — leave the original file untouched and let the
    # caller surface an actionable message. (copyfile only ever raised before
    # opening dst for write here, so dst is still the intact previous version.)
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last_err if last_err is not None else OSError(f"could not replace {dst}")


class SiqPackage:
    def __init__(self, path):
        self.path = path
        self.name = ""
        self.rounds = []
        self.total_duration = 0.0
        self.pkg_meta = {}
        self.pkg_tags: list = []
        self.pkg_authors: list = []
        self.pkg_comments: str = ""
        self._zip = None
        self._media_map = {}
        self._tmp_dir = None
        self._file_counter = 0
        self._extract_cache = {}
        # (rnd_idx, theme_idx, price) → q_idx — O(1) lookup instead of linear scan
        self._q_index: dict[tuple, int] = {}
        # Cache of the last parsed XML: (bytes_key, root, ns_url, tag_fn)
        # Invalidated in _rewrite_zip(). Avoids re-parsing on rapid sequential edits.
        self._xml_cache: tuple | None = None
        # XML navigation cache: reset each time _load_xml_root returns a new root.
        # Initialized here (not lazily) to avoid hasattr() cost on every nav call.
        self._xml_nav: dict | None = None
        self._old_qs_ids: list = []   # tracks question-list ids for _qs_price_map GC
        self._parse()

    def _parse(self):
        self._zip = zipfile.ZipFile(self.path, 'r')
        # Build media map AND a size map in a single infolist() pass.
        # _zip_sizes lets mp3_duration compute total_bytes without a seek/read.
        self._zip_sizes: dict[str, int] = {}
        for info in self._zip.infolist():
            zname   = info.filename
            decoded = _unquote(zname)
            self._media_map[decoded] = zname
            self._media_map[decoded.split('/')[-1]] = zname
            self._zip_sizes[zname] = info.file_size   # uncompressed size
        xml_bytes = self._zip.read('content.xml')
        if xml_bytes.startswith(b'\xef\xbb\xbf'):
            xml_bytes = xml_bytes[3:]
        root = _et_fromstring(xml_bytes)
        ns_url = root.tag.split('}')[0][1:] if '{' in root.tag else ''
        tag = _make_tag_fn(ns_url)
        self.name = root.get('name','')
        self.pkg_meta = {
            'version': root.get('version','5'), 'id': root.get('id',''),
            'restriction': root.get('restriction',''), 'date': root.get('date',''),
            'contactUri': root.get('contactUri',''), 'difficulty': root.get('difficulty',''),
            'logo': root.get('logo',''), 'language': root.get('language',''),
        }
        self.pkg_tags = [t.text.strip() for t in root.findall(f'.//{tag("tag")}')
                         if t.text and t.text.strip()]
        pkg_info_el = root.find(tag('info'))
        if pkg_info_el is not None:
            self.pkg_authors = [a.text.strip() for a in pkg_info_el.findall(f'{tag("authors")}/{tag("author")}')
                                if a.text and a.text.strip()]
            _comm = pkg_info_el.find(tag('comments'))
            self.pkg_comments = (_comm.text or '').strip() if _comm is not None else ''
        else:
            self.pkg_authors = []; self.pkg_comments = ''
        self.rounds, self.total_duration = self._parse_rounds(root, tag)

    def _parse_rounds(self, root, tag) -> tuple:
        """Parse all rounds/themes/questions from an XML root. Returns (rounds, total_duration)."""
        rounds = []; total_duration = 0.0
        # Invalidate old _qs_price_map entries for this package to prevent
        # memory growth from stale list-id keys when rounds are reloaded.
        for old_id in self._old_qs_ids:
            _qs_price_map.pop(old_id, None)
        self._old_qs_ids = []
        self._q_index.clear()
        # Clear old entries from the global lookup map before re-registering.
        # We remove only entries belonging to this package's previous question lists
        # by rebuilding; a full clear is safe since SiqPackage objects are per-file.
        _qs_price_map.clear()
        for r_idx, rnd in enumerate(root.findall(f'.//{tag("round")}')):
            rd = {"name": rnd.get('name',''), "themes": [],
                  "type": rnd.get('type',''), "comment": ''}
            rnd_info = rnd.find(tag('info'))
            if rnd_info is not None:
                _rc = rnd_info.find(tag('comments'))
                if _rc is not None and _rc.text: rd["comment"] = _rc.text.strip()
            for t_idx, theme in enumerate(rnd.findall(f'{tag("themes")}/{tag("theme")}')):
                th = {"name": theme.get('name',''), "questions": []}
                for q in theme.findall(f'{tag("questions")}/{tag("question")}'):
                    q_obj = self._parse_q(q, tag)
                    q_idx = len(th["questions"])
                    th["questions"].append(q_obj)
                    total_duration += q_obj["dur"]
                    self._q_index[(r_idx, t_idx, q_obj["price"])] = q_idx
                # Register this theme's question list in the global price→idx map.
                _qs_price_map[id(th["questions"])] = {
                    q["price"]: i for i, q in enumerate(th["questions"])
                }
                self._old_qs_ids.append(id(th["questions"]))
                rd["themes"].append(th)
            rounds.append(rd)
        return rounds, total_duration

    def _parse_q(self, q_el, tag):
        price = int(q_el.get('price', 0)); items = []; dur = 0.0

        # ── Collect all params into a list (document order) AND a name-dict ──
        # Single findall call — second loop below reuses this list instead of
        # calling findall() again, eliminating the redundant XML traversal.
        all_params = q_el.findall(f'{tag("params")}/{tag("param")}')
        params_by_name = {}
        for param in all_params:
            pname = param.get('name', '')
            params_by_name.setdefault(pname, []).append(param)

        # ── answerType: "select" means multiple-choice, "point" = click on image ──
        # Hoist _item_tag and _true_set once — reused in all 3 sections below.
        _item_tag  = tag('item')
        _true_set  = frozenset(('true', '1', 'yes'))
        q_type = ''
        for p in params_by_name.get('answerType', []):
            val = (p.text or '').strip()
            if not val:
                for it in p.findall(_item_tag):
                    val = (it.text or '').strip(); break
            if val:
                q_type = val; break

        # ── answerOptions: labeled choices A/B/C/D ──────────────
        # Each sub-param has name="A"/"B"/… and contains items (text or media)
        answer_options: dict[str, list[dict]] = {}  # key → list of item-dicts
        for p in params_by_name.get('answerOptions', []):
            for sub in p:   # iterate direct children (sub-params)
                key = sub.get('name', '')
                if not key: continue
                option_items = []
                for it in sub.findall(_item_tag):
                    itype  = it.get('type', 'text')
                    is_ref = it.get('isRef', 'False').lower() in _true_set
                    text   = (it.text or '').strip()
                    option_items.append({'type': itype, 'is_ref': is_ref, 'text': text})
                if not option_items:
                    # plain text content directly in sub-param
                    text = (sub.text or '').strip()
                    if text:
                        option_items.append({'type': 'text', 'is_ref': False, 'text': text})
                answer_options[key] = option_items

        # ── right/wrong answers ─────────────────────────────────
        right_ans = [a.text or '' for a in q_el.findall(f'.//{tag("right")}/{tag("answer")}')]
        wrong_ans = [a.text or '' for a in q_el.findall(f'.//{tag("wrong")}/{tag("answer")}')]
        if not right_ans and not wrong_ans:
            right_ans = [a.text or '' for a in q_el.findall(f'.//{tag("answer")}')]

        # For legacy packs with multiple answer-param items but no answerOptions
        if not answer_options and not wrong_ans:
            answer_param_items = []
            for p in params_by_name.get('answer', []):
                for it in p.findall(_item_tag):
                    itype     = it.get('type', 'text')
                    is_ref    = it.get('isRef', 'False').lower() in _true_set
                    placement = it.get('placement', '')
                    text      = (it.text or '').strip()
                    # Skip refs (media files), replic items (oral text), and empty
                    if is_ref or placement == 'replic' or not text:
                        continue
                    answer_param_items.append((itype, is_ref, text))
            if len(answer_param_items) > 1:
                correct_texts = set(right_ans)
                derived_wrong = [t for _, _, t in answer_param_items if t not in correct_texts]
                derived_right = [t for _, _, t in answer_param_items if t in correct_texts]
                if derived_wrong:
                    right_ans = derived_right or right_ans
                    wrong_ans = derived_wrong

        # ── Build items list — reuse all_params collected above ──
        # Cache frequently-used attribute accessors to avoid repeated
        # Python attribute lookups on every iteration.
        _item_tag = tag('item')
        _true_set = frozenset(('true', '1', 'yes'))
        for param in all_params:
            pname = param.get('name', '')
            if pname in ('answerType', 'answerOptions'):
                continue
            is_background_param = (pname == 'background')
            is_q_or_bg = is_background_param or pname == 'question'
            for item in param.findall(_item_tag):
                iget      = item.get
                itype     = iget('type', 'text')
                is_ref    = iget('isRef', 'False').lower() in _true_set
                text      = (item.text or '').strip()
                placement = iget('placement', '')
                xml_duration = iget('duration', '')

                wait_for_finish = iget('waitForFinish', 'True')
                simultaneous = (wait_for_finish.lower() == 'false') \
                               or is_background_param \
                               or (placement == 'background')

                item_dur = 0.0
                if xml_duration:
                    item_dur = _parse_hms(xml_duration) or 0.0
                elif is_ref and itype in ('video', 'audio'):
                    fname = _unquote(text)
                    mm = self._media_map
                    zpath = mm.get(fname) or mm.get(fname.split('/')[-1])
                    if zpath:
                        try:
                            with self._zip.open(zpath) as zfp:
                                if zpath[-4:].lower() == '.mp4':
                                    item_dur = mp4_duration(zfp)
                                else:
                                    item_dur = mp3_duration(
                                        zfp, total_bytes=self._zip_sizes.get(zpath, 0))
                        except Exception:
                            pass
                elif itype == 'image':
                    item_dur = 5.0
                elif itype == 'text' and placement != 'replic':
                    item_dur = (len(text) / 20 * 60 / 60 + 2) if text else 0.0
                items.append({"param": pname, "type": itype, "text": text,
                              "is_ref": is_ref, "dur": item_dur,
                              "placement": placement, "simultaneous": simultaneous,
                              "wait_for_finish": wait_for_finish,
                              "xml_duration": xml_duration})
                if is_q_or_bg:
                    dur += item_dur

        # ── answerDeviation (for q_type == "point") ────────────────
        answer_deviation = 0.1
        for p in params_by_name.get('answerDeviation', []):
            try: answer_deviation = float((p.text or '0.1').strip()); break
            except: pass

        q_comment = ''
        q_info_el = q_el.find(tag('info'))
        if q_info_el is not None:
            _qc = q_info_el.find(tag('comments'))
            if _qc is not None and _qc.text: q_comment = _qc.text.strip()
        return {"price": price, "items": items,
                "answers": right_ans,
                "wrong_answers": wrong_ans,
                "answer_options": answer_options,
                "q_type": q_type,
                "answer_deviation": answer_deviation,
                "comment": q_comment,
                "dur": dur}


    def extract_media(self, ref_name: str) -> str | None:
        """Extract a media entry to the temp dir and return the local path.

        Streams from the zip to disk in 1 MB chunks — avoids loading the entire
        file (up to 10 MB) into Python heap before writing.  The result is cached
        so subsequent calls for the same entry are free.
        """
        fname = _unquote(ref_name)
        zpath = self._media_map.get(fname) or self._media_map.get(fname.split('/')[-1])
        if not zpath: return None

        # Cache hit — return immediately if the extracted file still exists.
        if zpath in self._extract_cache:
            p = self._extract_cache[zpath]
            if os.path.exists(p): return p

        if self._tmp_dir is None:
            self._tmp_dir = tempfile.mkdtemp(prefix='sigame_')

        orig_name = _unquote(zpath.split('/')[-1])
        ext = orig_name[orig_name.rfind('.'):] if '.' in orig_name else ''
        # Имя берётся из недоверенного архива: оставляем в расширении только
        # буквы/цифры/точку, чтобы разделители пути и «..» не вытащили запись за
        # пределы tmp_dir (zip-slip). Само имя файла полностью контролируем мы.
        ext = re.sub(r'[^A-Za-z0-9.]', '', ext)[:12]
        self._file_counter += 1
        out = os.path.join(self._tmp_dir, f"media_{self._file_counter}{ext}")

        def _do_extract(zf):
            with zf.open(zpath) as src, open(out, 'wb') as dst:
                _shutil.copyfileobj(src, dst, length=1 << 20)  # 1 MB chunks

        try:
            _do_extract(self._zip)
            self._extract_cache[zpath] = out
            return out
        except Exception as e:
            # Stale zip handle (e.g. after a rewrite) — reopen once and retry.
            try:
                if self._zip is not None:
                    try: self._zip.close()
                    except: pass
                self._zip = zipfile.ZipFile(self.path, 'r')
                _do_extract(self._zip)
                self._extract_cache[zpath] = out
                return out
            except Exception as e2:
                _logger.warning(f"[extract] {e2}")
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
        _qs_price_map[id(qs)] = {q["price"]: i for i, q in enumerate(qs)}

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
            _logger.warning(f"[reload_rounds] {e}")

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

            # Preserve original file attributes (timestamps, permissions) before writing
            try:
                orig_stat = os.stat(self.path)
                orig_mode = orig_stat.st_mode
            except Exception:
                orig_stat = None; orig_mode = None

            with zipfile.ZipFile(self.path, 'r') as zin:
                with zipfile.ZipFile(tmp, 'w') as zout:
                    for info in zin.infolist():
                        # Clear Hidden/System bits
                        if info.create_system == 0:
                            dos_attr = (info.external_attr >> 16) & 0xFFFF
                            dos_attr &= ~0x02; dos_attr &= ~0x04
                            info.external_attr = (info.external_attr & 0x0000FFFF) | (dos_attr << 16)
                        if info.filename == 'content.xml':
                            # XML is text — worth compressing
                            xml_info = zipfile.ZipInfo('content.xml')
                            xml_info.compress_type = zipfile.ZIP_DEFLATED
                            xml_info.external_attr = info.external_attr
                            zout.writestr(xml_info, new_xml_bytes)
                        else:
                            # Media (MP3/MP4/AVIF/…) is already compressed —
                            # stream the raw compressed bytes directly without
                            # buffering the entire file in memory.
                            with zin.open(info) as src, zout.open(info, 'w') as dst:
                                _shutil.copyfileobj(src, dst, length=1 << 20)

            # Atomically swap the rewritten archive into place: clears a possible
            # read-only bit, retries while the file is transiently locked, then
            # falls back to an in-place overwrite copy (see _safe_replace).
            _safe_replace(tmp, self.path)

            # Restore normal file permissions and clear Hidden attribute on Windows
            try:
                os.chmod(self.path, _stat.S_IWRITE | _stat.S_IREAD)
            except Exception:
                pass
            try:
                FILE_ATTRIBUTE_HIDDEN = 0x02
                attrs = _ctypes.windll.kernel32.GetFileAttributesW(self.path)
                if attrs != -1 and (attrs & FILE_ATTRIBUTE_HIDDEN):
                    _ctypes.windll.kernel32.SetFileAttributesW(
                        self.path, (attrs & ~FILE_ATTRIBUTE_HIDDEN) | 0x80)
            except Exception:
                pass

            self._zip = zipfile.ZipFile(self.path, 'r')
            # Rebuild the size map so mp3_duration probes stay accurate.
            self._zip_sizes = {info.filename: info.file_size
                               for info in self._zip.infolist()}
            return True
        except Exception as e:
            _logger.warning(f"[save_siq] {e}")
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass
            if self._zip is None:
                try: self._zip = zipfile.ZipFile(self.path, 'r')
                except: pass
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
        root = _et_fromstring(xml_bytes)
        ns_url = root.tag.split('}')[0][1:] if '{' in root.tag else ''
        tag = _make_tag_fn(ns_url)
        self._xml_cache = (root, ns_url, tag)
        self._xml_nav = None   # nav cache tied to root object — reset on new parse
        return root, ns_url, tag

    _registered_ns: set = set()   # class-level set; ns registration is process-global

    def _xml_to_bytes(self, root, ns_url: str) -> bytes:
        if _ET_IS_LXML:
            return ET.tostring(root, xml_declaration=True, encoding='utf-8')
        if ns_url and ns_url not in SiqPackage._registered_ns:
            ET.register_namespace('', ns_url)
            SiqPackage._registered_ns.add(ns_url)
        raw = ET.tostring(root, encoding='unicode')
        return ('<?xml version="1.0" encoding="utf-8"?>\n' + raw).encode('utf-8')

    def _nav_to_question(self, root, tag, rnd_idx: int, theme_idx: int,
                         q_idx: int | None = None):
        """Navigate XML to a round/theme/question element.
        Caches the round-list and per-round theme-lists inside _xml_nav so that
        repeated calls (common during sequential edits) avoid repeated findall()."""
        # _xml_nav is invalidated together with _xml_cache (set to None in _rewrite_zip).
        nav = self._xml_nav or {}; self._xml_nav = nav

        # rounds list
        rounds = nav.get('rounds')
        if rounds is None:
            rounds = root.findall(f'.//{tag("round")}')
            nav['rounds'] = rounds
        if rnd_idx >= len(rounds): raise IndexError("rnd_idx out of range")

        # themes list for this round
        th_key = ('themes', rnd_idx)
        themes = nav.get(th_key)
        if themes is None:
            themes = rounds[rnd_idx].findall(f'{tag("themes")}/{tag("theme")}')
            nav[th_key] = themes
        if theme_idx >= len(themes): raise IndexError("theme_idx out of range")

        if q_idx is None:
            return themes[theme_idx], tag

        # questions list for this theme
        q_key = ('questions', rnd_idx, theme_idx)
        questions = nav.get(q_key)
        if questions is None:
            questions = themes[theme_idx].findall(f'{tag("questions")}/{tag("question")}')
            nav[q_key] = questions
        if q_idx >= len(questions): raise IndexError("q_idx out of range")
        return questions[q_idx], tag

    def _nav_to_round(self, root, tag, rnd_idx: int):
        """Navigate XML to a round element — reuses _nav_to_question's cache."""
        nav = self._xml_nav or {}; self._xml_nav = nav
        rounds = nav.get("rounds")
        if rounds is None:
            rounds = root.findall(f".//{tag('round')}")
            nav["rounds"] = rounds
        if rnd_idx >= len(rounds): raise IndexError("rnd_idx out of range")
        return rounds[rnd_idx], tag

    def _xml_nav_q(self, rnd_idx: int, theme_idx: int, q_idx: int):
        """Load XML root + navigate to question element in one call.

        Returns ``(root, ns_url, tag_fn, q_el)`` using the cached root and the
        ``_nav_to_question`` index, so repeated calls during an editing session
        cost only the key-lookup instead of re-parsing XML or re-traversing
        the round/theme/question lists.

        Callers that need to call ``_rewrite_zip`` afterwards must pass the
        returned ``root`` to ``_xml_to_bytes(root, ns_url)`` as usual.
        """
        root, ns_url, tag = self._load_xml_root()
        q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)
        return root, ns_url, tag, q_el

    def save_question(self, rnd_idx: int, theme_idx: int, q_idx: int,
                      new_texts: list, new_answers: list) -> bool:
        """Edit text items and answers of a question and save back to the zip."""
        try:
            root, ns_url, tag = self._load_xml_root()
            q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)

            # Update text items in question param
            text_idx = 0
            for param in q_el.findall(f'{tag("params")}/{tag("param")}'):
                if param.get('name') == 'question':
                    for item in param.findall(tag('item')):
                        if item.get('type', 'text') == 'text' and \
                                item.get('isRef', 'False').lower() != 'true':
                            if text_idx < len(new_texts):
                                item.text = new_texts[text_idx]
                                text_idx += 1

            # Update answers
            ans_els = q_el.findall(f'.//{tag("answer")}')
            # Remove extra answers, update existing
            for i, ans_el in enumerate(ans_els):
                if i < len(new_answers):
                    ans_el.text = new_answers[i]
                else:
                    ans_el.getparent().remove(ans_el) if hasattr(ans_el, 'getparent') else None
            # Add new answers if more provided
            if len(new_answers) > len(ans_els):
                right_el = q_el.find(f'.//{tag("right")}')
                if right_el is None:
                    right_el = ET.SubElement(q_el, tag('right'))
                for i in range(len(ans_els), len(new_answers)):
                    a = ET.SubElement(right_el, tag('answer'))
                    a.text = new_answers[i]

            # Also update in-memory parsed data
            try:
                q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
                ti = 0
                for it in q_obj["items"]:
                    if it["param"] == "question" and it["type"] == "text" and not it["is_ref"]:
                        if ti < len(new_texts): it["text"] = new_texts[ti]; ti += 1
                q_obj["answers"] = list(new_answers)
            except Exception as _e: _logger.debug(str(_e))

            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_question] {e}")
            return False

    def save_pkg_info(self, meta: dict, tags: list, authors: list, comments: str) -> bool:
        """Save package-level metadata (attributes, tags, info) to the SIQ file."""
        try:
            root, ns_url, tag_fn = self._load_xml_root()
            for key in ('restriction','date','contactUri','difficulty','logo','language','version','name'):
                val = meta.get(key,'')
                if val: root.set(key, val)
                elif key in root.attrib and key not in ('name','version'): del root.attrib[key]
            # ── tags ──
            tags_el = root.find(tag_fn('tags'))
            # Find position: tags is usually first child right after package root
            if tags_el is None:
                tags_el = ET.Element(tag_fn('tags'))
                root.insert(0, tags_el)
            for t in tags_el.findall(tag_fn('tag')): tags_el.remove(t)
            for txt in tags:
                t = ET.SubElement(tags_el, tag_fn('tag')); t.text = txt
            # ── info ──
            info_el = root.find(tag_fn('info'))
            if info_el is None and (authors or comments):
                info_el = ET.SubElement(root, tag_fn('info'))
            if info_el is not None:
                auth_el = info_el.find(tag_fn('authors'))
                if auth_el is None and authors:
                    auth_el = ET.SubElement(info_el, tag_fn('authors'))
                if auth_el is not None:
                    for a in auth_el.findall(tag_fn('author')): auth_el.remove(a)
                    for at in authors:
                        a = ET.SubElement(auth_el, tag_fn('author')); a.text = at
                comm_el = info_el.find(tag_fn('comments'))
                if comments:
                    if comm_el is None: comm_el = ET.SubElement(info_el, tag_fn('comments'))
                    comm_el.text = comments
                elif comm_el is not None:
                    info_el.remove(comm_el)
            self.pkg_meta.update(meta); self.pkg_tags = list(tags)
            self.pkg_authors = list(authors); self.pkg_comments = comments
            if 'name' in meta and meta['name']: self.name = meta['name']
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_pkg_info] {e}"); return False

    def save_round_info(self, rnd_idx: int, rnd_type: str, comment: str) -> bool:
        """Save round type ('' or 'final') and comment to SIQ XML."""
        try:
            root, ns_url, tag_fn = self._load_xml_root()
            rnd_el, tag_fn = self._nav_to_round(root, tag_fn, rnd_idx)
            if rnd_type: rnd_el.set('type', rnd_type)
            elif 'type' in rnd_el.attrib: del rnd_el.attrib['type']
            info_el = rnd_el.find(tag_fn('info'))
            if comment:
                if info_el is None: info_el = ET.SubElement(rnd_el, tag_fn('info'))
                comm_el = info_el.find(tag_fn('comments'))
                if comm_el is None: comm_el = ET.SubElement(info_el, tag_fn('comments'))
                comm_el.text = comment
            elif info_el is not None:
                comm_el = info_el.find(tag_fn('comments'))
                if comm_el is not None: info_el.remove(comm_el)
            try:
                self.rounds[rnd_idx]["type"] = rnd_type
                self.rounds[rnd_idx]["comment"] = comment
            except: pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_round_info] {e}"); return False

    def save_question_comment(self, rnd_idx: int, theme_idx: int, q_idx: int,
                               comment: str) -> bool:
        """Save a comment to a question's <info><comments> element."""
        try:
            root, ns_url, tag_fn = self._load_xml_root()
            q_el, tag_fn = self._nav_to_question(root, tag_fn, rnd_idx, theme_idx, q_idx)
            info_el = q_el.find(tag_fn('info'))
            if comment:
                if info_el is None:
                    info_el = ET.Element(tag_fn('info'))
                    q_el.insert(0, info_el)
                comm_el = info_el.find(tag_fn('comments'))
                if comm_el is None: comm_el = ET.SubElement(info_el, tag_fn('comments'))
                comm_el.text = comment
            elif info_el is not None:
                comm_el = info_el.find(tag_fn('comments'))
                if comm_el is not None: info_el.remove(comm_el)
            try: self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]["comment"] = comment
            except: pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_question_comment] {e}"); return False

    def save_round_name(self, rnd_idx: int, new_name: str) -> bool:
        """Rename a round in the SIQ file."""
        try:
            root, ns_url, tag = self._load_xml_root()
            rnd_el, tag = self._nav_to_round(root, tag, rnd_idx)
            rnd_el.set('name', new_name)
            try: self.rounds[rnd_idx]["name"] = new_name
            except: pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_round_name] {e}")
            return False

    def add_theme(self, rnd_idx: int, theme_name: str = "") -> bool:
        """Append a new empty theme to a round in the SIQ file."""
        try:
            root, ns_url, tag = self._load_xml_root()
            rnd_el, tag = self._nav_to_round(root, tag, rnd_idx)
            themes_el = rnd_el.find(tag("themes"))
            if themes_el is None:
                themes_el = ET.SubElement(rnd_el, tag("themes"))
            new_th = ET.SubElement(themes_el, tag("theme"))
            new_th.set("name", theme_name or f"Тема {len(self.rounds[rnd_idx]['themes'])+1}")
            ET.SubElement(new_th, tag("questions"))
            self.rounds[rnd_idx]["themes"].append({"name": new_th.get("name"), "questions": []})
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[add_theme] {e}")
            return False

    def move_round(self, src_idx: int, dst_idx: int) -> bool:
        """Reorder rounds in the SIQ file."""
        try:
            if src_idx == dst_idx: return True
            root, ns_url, tag = self._load_xml_root()
            rounds_el = root.find(tag("rounds"))
            if rounds_el is None:
                # Try to find parent of first round
                rnd_els = root.findall(f'.//{tag("round")}')
                if not rnd_els: return False
                # Find parent
                for p in root.iter():
                    if rnd_els[0] in list(p):
                        rounds_el = p; break
            if rounds_el is None: return False
            rnd_els = list(rounds_el.findall(tag("round")))
            if src_idx >= len(rnd_els) or dst_idx >= len(rnd_els): return False
            el = rnd_els[src_idx]
            rounds_el.remove(el)
            rounds_el.insert(dst_idx, el)
            # Update in-memory
            rd = self.rounds.pop(src_idx)
            self.rounds.insert(dst_idx, rd)
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[move_round] {e}")
            return False

    def add_round(self, round_name: str = "") -> bool:
        """Append a new empty round to the SIQ file."""
        try:
            root, ns_url, tag = self._load_xml_root()
            rounds_el = root.find(tag("rounds"))
            if rounds_el is None:
                rounds_el = ET.SubElement(root, tag("rounds"))
            new_rd = ET.SubElement(rounds_el, tag("round"))
            new_rd.set("name", round_name or f"Раунд {len(self.rounds)+1}")
            ET.SubElement(new_rd, tag("themes"))
            self.rounds.append({"name": new_rd.get("name"), "themes": []})
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[add_round] {e}")
            return False

    def save_theme_name(self, rnd_idx: int, theme_idx: int, new_name: str) -> bool:
        """Rename a theme in the SIQ file."""
        try:
            root, ns_url, tag = self._load_xml_root()
            theme_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx)
            theme_el.set('name', new_name)
            # Update in-memory
            try: self.rounds[rnd_idx]["themes"][theme_idx]["name"] = new_name
            except: pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_theme_name] {e}")
            return False

    def save_question_price(self, rnd_idx: int, theme_idx: int, q_idx: int,
                            new_price: int) -> bool:
        """Change the price (номинал) of a question in the SIQ file."""
        try:
            root, ns_url, tag = self._load_xml_root()
            q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)
            q_el.set('price', str(new_price))
            try: self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]["price"] = new_price
            except: pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_price] {e}")
            return False

    def save_round_prices(self, rnd_idx: int, min_price: int,
                          max_price: int, step: int) -> bool:
        """Re-price every question in a round as an arithmetic progression.

        For each theme, the i-th question (0-based, by document order) gets
        price = min_price + i*step. If max_price is reached before all
        questions are priced, the progression keeps extending past max_price
        so prices stay unique within the theme.
        """
        if step <= 0 or min_price <= 0 or max_price < min_price:
            _logger.warning("[save_round_prices] invalid args: "
                            f"min={min_price} max={max_price} step={step}")
            return False
        try:
            root, ns_url, tag = self._load_xml_root()
            rnd_el, tag = self._nav_to_round(root, tag, rnd_idx)
            # Purge stale (rnd_idx, _, _) entries from _q_index before re-keying
            for key in [k for k in self._q_index if k[0] == rnd_idx]:
                del self._q_index[key]
            for t_idx, theme_el in enumerate(
                    rnd_el.findall(f'{tag("themes")}/{tag("theme")}')):
                q_els = theme_el.findall(f'{tag("questions")}/{tag("question")}')
                for i, q_el in enumerate(q_els):
                    new_price = min_price + i * step
                    q_el.set('price', str(new_price))
                    try:
                        self.rounds[rnd_idx]["themes"][t_idx]["questions"][i]["price"] = new_price
                    except Exception:
                        pass
                # Rebuild per-theme price→idx maps so subsequent lookups work
                try:
                    qs_list = self.rounds[rnd_idx]["themes"][t_idx]["questions"]
                    _qs_price_map[id(qs_list)] = {
                        q["price"]: idx for idx, q in enumerate(qs_list)}
                    for idx, q in enumerate(qs_list):
                        self._q_index[(rnd_idx, t_idx, q["price"])] = idx
                except Exception:
                    pass
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_round_prices] {e}")
            return False

    def save_select_question(self, rnd_idx: int, theme_idx: int, q_idx: int,
                             new_price: int,
                             new_q_texts: list,
                             answer_options: dict,
                             correct_key: str) -> bool:
        """Save a select-type (multiple-choice) question back to the SIQ zip.

        answer_options: ordered dict  key → text  e.g. {"A":"Да","B":"Нет","C":"Может быть"}
        correct_key:    the single correct letter, e.g. "B"
        """
        try:
            root, ns_url, tag = self._load_xml_root()
            q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)

            # ── price ──────────────────────────────────────────
            q_el.set('price', str(new_price))

            params_el = q_el.find(tag('params'))
            if params_el is None:
                params_el = ET.SubElement(q_el, tag('params'))

            def get_or_create_param(name, ptype=None):
                for p in params_el.findall(tag('param')):
                    if p.get('name') == name:
                        return p
                p = ET.SubElement(params_el, tag('param'))
                p.set('name', name)
                if ptype: p.set('type', ptype)
                return p

            # ── question param: update text items ──────────────
            q_param = get_or_create_param('question', 'content')
            text_items = [it for it in q_param.findall(tag('item'))
                          if it.get('type','text') == 'text'
                          and it.get('isRef','False').lower() != 'true']
            for i, te in enumerate(new_q_texts):
                if i < len(text_items):
                    text_items[i].text = te
                else:
                    new_it = ET.SubElement(q_param, tag('item'))
                    new_it.text = te

            # ── answerType param ───────────────────────────────
            at_param = get_or_create_param('answerType')
            at_param.text = 'select'

            # ── answerOptions param: rebuild completely ─────────
            # Remove old one first
            old_ao = [p for p in params_el.findall(tag('param'))
                      if p.get('name') == 'answerOptions']
            for old in old_ao:
                params_el.remove(old)
            ao_param = ET.SubElement(params_el, tag('param'))
            ao_param.set('name', 'answerOptions')
            ao_param.set('type', 'group')
            for key, text in answer_options.items():
                sub = ET.SubElement(ao_param, tag('param'))
                sub.set('name', key)
                sub.set('type', 'content')
                it = ET.SubElement(sub, tag('item'))
                it.text = text

            # ── right answer ───────────────────────────────────
            right_el = q_el.find(tag('right'))
            if right_el is None:
                right_el = ET.SubElement(q_el, tag('right'))
            # Clear existing answers, write single correct key
            for a in right_el.findall(tag('answer')):
                right_el.remove(a)
            ans_el = ET.SubElement(right_el, tag('answer'))
            ans_el.text = correct_key

            # ── update in-memory ───────────────────────────────
            try:
                q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
                q_obj["price"] = new_price
                q_obj["q_type"] = "select"
                q_obj["answers"] = [correct_key]
                q_obj["answer_options"] = {k: [{"type":"text","is_ref":False,"text":v}]
                                           for k, v in answer_options.items()}
                ti = 0
                for it in q_obj["items"]:
                    if it["param"] == "question" and it["type"] == "text" and not it["is_ref"]:
                        if ti < len(new_q_texts): it["text"] = new_q_texts[ti]; ti += 1
            except Exception as _e: _logger.debug(str(_e))

            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_select_question] {e}")
            return False

    def save_point_question(self, rnd_idx: int, theme_idx: int, q_idx: int,
                            new_price: int, new_q_texts: list,
                            cx: float, cy: float, deviation: float) -> bool:
        """Save a point-type question (answerType=point, right/answer='cx,cy')."""
        try:
            root, ns_url, tag = self._load_xml_root()
            q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)
            q_el.set('price', str(new_price))

            params_el = q_el.find(tag('params'))
            if params_el is None:
                params_el = ET.SubElement(q_el, tag('params'))

            def _get_or_create(name):
                for p in params_el.findall(tag('param')):
                    if p.get('name') == name: return p
                p = ET.SubElement(params_el, tag('param')); p.set('name', name); return p

            # answerType = point
            at = _get_or_create('answerType'); at.text = 'point'
            # answerDeviation
            ad = _get_or_create('answerDeviation'); ad.text = f"{deviation:.4f}"

            # Update question text items
            q_param = next((p for p in params_el.findall(tag('param')) if p.get('name') == 'question'), None)
            if q_param is not None:
                text_idx = 0
                for item in q_param.findall(tag('item')):
                    if item.get('type', 'text') == 'text' and item.get('isRef', 'False').lower() != 'true':
                        if text_idx < len(new_q_texts):
                            item.text = new_q_texts[text_idx]; text_idx += 1

            # right answer = "cx,cy"
            right_el = q_el.find(tag('right'))
            if right_el is None:
                right_el = ET.SubElement(q_el, tag('right'))
            ans_els = right_el.findall(tag('answer'))
            coord_str = f"{cx:.4f},{cy:.4f}"
            if ans_els:
                ans_els[0].text = coord_str
            else:
                a = ET.SubElement(right_el, tag('answer')); a.text = coord_str

            # Update in-memory
            try:
                q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
                q_obj["price"] = new_price; q_obj["q_type"] = "point"
                q_obj["answers"] = [coord_str]; q_obj["answer_deviation"] = deviation
            except Exception as _e: _logger.debug(str(_e))

            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[save_point_question] {e}")
            return False

    def add_question(self, rnd_idx: int, theme_idx: int, price: int) -> bool:
        """Add a new empty question (price, empty text, empty answer) to theme."""
        try:
            root, ns_url, tag = self._load_xml_root()
            theme_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx)
            qs_el = theme_el.find(tag('questions'))
            if qs_el is None:
                qs_el = ET.SubElement(theme_el, tag('questions'))
            q_el = ET.SubElement(qs_el, tag('question'))
            q_el.set('price', str(price))
            params_el = ET.SubElement(q_el, tag('params'))
            q_param = ET.SubElement(params_el, tag('param'))
            q_param.set('name', 'question'); q_param.set('type', 'content')
            item_el = ET.SubElement(q_param, tag('item')); item_el.text = ''
            right_el = ET.SubElement(q_el, tag('right'))
            ans_el = ET.SubElement(right_el, tag('answer')); ans_el.text = ''
            # Update in-memory
            new_q = {"price": price, "items": [{"param": "question", "type": "text",
                      "text": "", "is_ref": False, "dur": 0.0, "placement": "",
                      "simultaneous": False}],
                     "answers": [""], "wrong_answers": [], "answer_options": {},
                     "q_type": "", "dur": 0.0}
            self.rounds[rnd_idx]["themes"][theme_idx]["questions"].append(new_q)
            # empty question has 0 duration
            return self._save_xml(root, ns_url)
        except Exception as e:
            _logger.warning(f"[add_question] {e}")
            return False

    def add_media_to_question(self, rnd_idx: int, theme_idx: int, q_idx: int,
                               file_path: str, param_name: str = 'question') -> bool:
        """Copy a local media file into the SIQ zip and add a ref item to the question."""
        ext = os.path.splitext(file_path)[1].lower()
        if   ext in _IMG_EXTS:   itype, folder = 'image', 'Images'
        elif ext in _AUDIO_EXTS: itype, folder = 'audio', 'Audio'
        elif ext in _VIDEO_EXTS: itype, folder = 'video', 'Video'
        else:
            print(f"[add_media] unsupported extension: {ext}")
            return False
        try:
            fname = os.path.basename(file_path)
            # Zip entry uses the ORIGINAL (non-encoded) filename so SIGame can find it.
            # content.xml item.text uses the URL-encoded form (SIQ5 spec).
            existing = set(self._zip.namelist())
            candidate = f'{folder}/{fname}'
            counter = 1
            while candidate in existing:
                stem, suf = os.path.splitext(fname)
                candidate = f'{folder}/{stem}_{counter}{suf}'; counter += 1
            zip_name = candidate                             # original name in zip
            ref_text = os.path.basename(zip_name)           # plain filename → item.text (no URL encoding)

            root, ns_url, tag, q_el = self._xml_nav_q(rnd_idx, theme_idx, q_idx)
            params_el = q_el.find(tag('params'))
            if params_el is None:
                params_el = ET.SubElement(q_el, tag('params'))
            # Find or create the target param
            target_param = None
            for p in params_el.findall(tag('param')):
                if p.get('name') == param_name:
                    target_param = p; break
            if target_param is None:
                target_param = ET.SubElement(params_el, tag('param'))
                target_param.set('name', param_name); target_param.set('type', 'content')
            new_item = ET.SubElement(target_param, tag('item'))
            new_item.set('type', itype); new_item.set('isRef', 'True')
            new_item.text = ref_text   # plain filename; SIGame finds the zip entry by this name

            # Repack zip including new media file
            tmp = self.path + ".edit_tmp"
            try:
                if self._zip is not None:
                    self._zip.close(); self._zip = None
                # Invalidate XML cache and nav cache — zip is about to change.
                self._xml_cache = None
                self._xml_nav   = None
                with zipfile.ZipFile(self.path, 'r') as zin:
                    with zipfile.ZipFile(tmp, 'w') as zout:
                        for info in zin.infolist():
                            if info.filename == 'content.xml':
                                xi = zipfile.ZipInfo('content.xml')
                                xi.compress_type = zipfile.ZIP_DEFLATED
                                zout.writestr(xi, self._xml_to_bytes(root, ns_url))
                            else:
                                # Stream-copy compressed bytes — avoids buffering large
                                # MP4/MP3 files entirely in memory (same fix as _rewrite_zip).
                                with zin.open(info) as src, zout.open(info, 'w') as dst:
                                    _shutil.copyfileobj(src, dst, length=1 << 20)
                        # New media: store without re-compression (already compressed).
                        # Stream from disk — avoids buffering up to 10 MB in RAM.
                        mi = zipfile.ZipInfo(zip_name)
                        mi.compress_type = zipfile.ZIP_STORED
                        with open(file_path, 'rb') as mf, zout.open(mi, 'w') as dst:
                            _shutil.copyfileobj(mf, dst, length=1 << 20)
                _safe_replace(tmp, self.path)
                self._zip = zipfile.ZipFile(self.path, 'r')
                # Keep _zip_sizes consistent: add the new entry's size from disk.
                try:
                    self._zip_sizes[zip_name] = os.path.getsize(file_path)
                except Exception:
                    pass
                # Update media map: both the original name and encoded ref map to the zip entry
                self._media_map[fname] = zip_name
                self._media_map[zip_name] = zip_name
                self._media_map[ref_text] = zip_name
                # Update in-memory
                try:
                    q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
                    q_obj["items"].append({"param": param_name, "type": itype,
                                           "text": ref_text, "is_ref": True,
                                           "dur": 5.0 if itype == 'image' else 0.0,
                                           "placement": "", "simultaneous": False,
                                           "wait_for_finish": "True", "xml_duration": ""})
                except Exception as _e: _logger.debug(str(_e))
                return True
            except Exception as e:
                _logger.warning(f"[add_media zip] {e}")
                if os.path.exists(tmp):
                    try: os.remove(tmp)
                    except: pass
                if self._zip is None:
                    try: self._zip = zipfile.ZipFile(self.path, 'r')
                    except: pass
                return False
        except Exception as e:
            _logger.warning(f"[add_media] {e}")
            return False

    def close(self):
        if self._zip: self._zip.close(); self._zip = None
        if self._tmp_dir and os.path.exists(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True); self._tmp_dir = None

__all__ = [
    'SiqPackage',
    '_safe_replace',
]
