# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SiqPackage: __init__. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


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
    self._zip = _api.zipfile.ZipFile(self.path, 'r')
    # Build media map AND a size map in a single infolist() pass.
    # _zip_sizes lets mp3_duration compute total_bytes without a seek/read.
    self._zip_sizes: dict[str, int] = {}
    for info in self._zip.infolist():
        zname   = info.filename
        decoded = _api._unquote(zname)
        self._media_map[decoded] = zname
        self._media_map[decoded.split('/')[-1]] = zname
        self._zip_sizes[zname] = info.file_size   # uncompressed size
    xml_bytes = self._zip.read('content.xml')
    if xml_bytes.startswith(b'\xef\xbb\xbf'):
        xml_bytes = xml_bytes[3:]
    root = _api._et_fromstring(xml_bytes)
    ns_url = root.tag.split('}')[0][1:] if '{' in root.tag else ''
    tag = _api._make_tag_fn(ns_url)
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
        _api._qs_price_map.pop(old_id, None)
    self._old_qs_ids = []
    self._q_index.clear()
    # Clear old entries from the global lookup map before re-registering.
    # We remove only entries belonging to this package's previous question lists
    # by rebuilding; a full clear is safe since SiqPackage objects are per-file.
    _api._qs_price_map.clear()
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
            _api._qs_price_map[id(th["questions"])] = {
                q["price"]: i for i, q in enumerate(th["questions"])
            }
            self._old_qs_ids.append(id(th["questions"]))
            rd["themes"].append(th)
        rounds.append(rd)
    return rounds, total_duration

def _parse_q(self, q_el, tag):
    price = int(q_el.get('price', 0)); items = []

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
    _MEDIA_ITEM_TYPES = ('image', 'audio', 'video', 'html')  # a_items normalizes voice→audio
    # q_items/a_items — формат, который ждёт общая логика группировки/итога
    # длительности из siq_duration.py (см.
    # question_duration ниже). Отдельно от items[] (используется в
    # UI-редакторе вопроса, формат которого не меняем).
    q_items: list[dict] = []
    a_items: list[dict] = []
    for param in all_params:
        pname = param.get('name', '')
        if pname in ('answerType', 'answerOptions'):
            continue
        is_background_param = (pname == 'background')
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

            dur_attr = _api.siq_duration.parse_dur_attr(xml_duration) if xml_duration else None
            item_dur = 0.0
            if dur_attr is not None:
                item_dur = max(0.0, dur_attr)
            elif is_ref and itype in ('video', 'audio', 'voice'):
                fname = _api._unquote(text)
                mm = self._media_map
                zpath = mm.get(fname) or mm.get(fname.split('/')[-1])
                if zpath:
                    try:
                        with self._zip.open(zpath) as zfp:
                            if zpath[-4:].lower() == '.mp4':
                                item_dur = _api.mp4_duration(zfp)
                            else:
                                item_dur = _api.mp3_duration(
                                    zfp, total_bytes=self._zip_sizes.get(zpath, 0))
                    except Exception:
                        pass
            elif itype == 'image':
                item_dur = _api.siq_duration.IMAGE_SEC
            elif itype == 'html':
                # No reliable way to know how long an interactive minigame
                # runs — treat it like a static image unless timed.
                item_dur = _api.siq_duration.IMAGE_SEC
            elif itype == 'text' and placement != 'replic':
                item_dur = (len(text) / _api.siq_duration.CHARS_PER_SEC) if text else 0.0
            items.append({"param": pname, "type": itype, "text": text,
                          "is_ref": is_ref, "dur": item_dur,
                          "placement": placement, "simultaneous": simultaneous,
                          "wait_for_finish": wait_for_finish,
                          "xml_duration": xml_duration})

            # Классификация для siq_duration: только пункты из params
            # "question"/"answer" (не "background" — спецобработки по имени
            # параметра нет, только по атрибуту placement на самом пункте),
            # группировка одновременного показа — по
            # placement=="background"/waitForFinish=="false".
            if pname in ('question', 'answer'):
                dest = q_items if pname == 'question' else a_items
                dest.append({
                    "type": "audio" if itype == "voice" else itype,
                    "raw": text,
                    "placement": placement.lower(),
                    "wait_false": wait_for_finish.lower() == "false",
                    "duration": item_dur,
                })

    # «время на ответ»: таймер на вопросе целиком или на блоке ответа

    answer_time = _api.siq_duration.parse_dur_attr(q_el.get('duration'))
    for p in params_by_name.get('answer', []):
        if answer_time is None:
            answer_time = _api.siq_duration.parse_dur_attr(p.get('duration'))
        if answer_time is not None:
            break
    has_answer_content = any(
        it["raw"] or it["type"] in _MEDIA_ITEM_TYPES for it in a_items)
    has_plain_answer = any(a and a.strip() for a in right_ans)
    dur = _api.siq_duration.question_duration(
        q_items, a_items, answer_time, has_answer_content, has_plain_answer,
        lambda it: it["duration"])

    # ── answerDeviation (for q_type == "point") ────────────────
    answer_deviation = 0.1
    for p in params_by_name.get('answerDeviation', []):
        try: answer_deviation = float((p.text or '0.1').strip()); break
        except Exception: pass

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
