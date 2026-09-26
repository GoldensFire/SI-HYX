# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SiqPackage: _xml_to_bytes. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


def _xml_to_bytes(self, root, ns_url: str) -> bytes:
    if _api._ET_IS_LXML:
        return _api.ET.tostring(root, xml_declaration=True, encoding='utf-8')
    if ns_url and ns_url not in _api.SiqPackage._registered_ns:
        _api.ET.register_namespace('', ns_url)
        _api.SiqPackage._registered_ns.add(ns_url)
    raw = _api.ET.tostring(root, encoding='unicode')
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
                right_el = _api.ET.SubElement(q_el, tag('right'))
            for i in range(len(ans_els), len(new_answers)):
                a = _api.ET.SubElement(right_el, tag('answer'))
                a.text = new_answers[i]

        # Also update in-memory parsed data
        try:
            q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
            ti = 0
            for it in q_obj["items"]:
                if it["param"] == "question" and it["type"] == "text" and not it["is_ref"]:
                    if ti < len(new_texts): it["text"] = new_texts[ti]; ti += 1
            q_obj["answers"] = list(new_answers)
        except Exception as _e: _api._logger.debug(str(_e))

        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_question] {e}")
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
            tags_el = _api.ET.Element(tag_fn('tags'))
            root.insert(0, tags_el)
        for t in tags_el.findall(tag_fn('tag')): tags_el.remove(t)
        for txt in tags:
            t = _api.ET.SubElement(tags_el, tag_fn('tag')); t.text = txt
        # ── info ──
        info_el = root.find(tag_fn('info'))
        if info_el is None and (authors or comments):
            info_el = _api.ET.SubElement(root, tag_fn('info'))
        if info_el is not None:
            auth_el = info_el.find(tag_fn('authors'))
            if auth_el is None and authors:
                auth_el = _api.ET.SubElement(info_el, tag_fn('authors'))
            if auth_el is not None:
                for a in auth_el.findall(tag_fn('author')): auth_el.remove(a)
                for at in authors:
                    a = _api.ET.SubElement(auth_el, tag_fn('author')); a.text = at
            comm_el = info_el.find(tag_fn('comments'))
            if comments:
                if comm_el is None: comm_el = _api.ET.SubElement(info_el, tag_fn('comments'))
                comm_el.text = comments
            elif comm_el is not None:
                info_el.remove(comm_el)
        self.pkg_meta.update(meta); self.pkg_tags = list(tags)
        self.pkg_authors = list(authors); self.pkg_comments = comments
        if 'name' in meta and meta['name']: self.name = meta['name']
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_pkg_info] {e}"); return False

def save_round_info(self, rnd_idx: int, rnd_type: str, comment: str) -> bool:
    """Save round type ('' or 'final') and comment to SIQ XML."""
    try:
        root, ns_url, tag_fn = self._load_xml_root()
        rnd_el, tag_fn = self._nav_to_round(root, tag_fn, rnd_idx)
        if rnd_type: rnd_el.set('type', rnd_type)
        elif 'type' in rnd_el.attrib: del rnd_el.attrib['type']
        info_el = rnd_el.find(tag_fn('info'))
        if comment:
            if info_el is None: info_el = _api.ET.SubElement(rnd_el, tag_fn('info'))
            comm_el = info_el.find(tag_fn('comments'))
            if comm_el is None: comm_el = _api.ET.SubElement(info_el, tag_fn('comments'))
            comm_el.text = comment
        elif info_el is not None:
            comm_el = info_el.find(tag_fn('comments'))
            if comm_el is not None: info_el.remove(comm_el)
        try:
            self.rounds[rnd_idx]["type"] = rnd_type
            self.rounds[rnd_idx]["comment"] = comment
        except Exception: pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_round_info] {e}"); return False

def save_question_comment(self, rnd_idx: int, theme_idx: int, q_idx: int,
                           comment: str) -> bool:
    """Save a comment to a question's <info><comments> element."""
    try:
        root, ns_url, tag_fn = self._load_xml_root()
        q_el, tag_fn = self._nav_to_question(root, tag_fn, rnd_idx, theme_idx, q_idx)
        info_el = q_el.find(tag_fn('info'))
        if comment:
            if info_el is None:
                info_el = _api.ET.Element(tag_fn('info'))
                q_el.insert(0, info_el)
            comm_el = info_el.find(tag_fn('comments'))
            if comm_el is None: comm_el = _api.ET.SubElement(info_el, tag_fn('comments'))
            comm_el.text = comment
        elif info_el is not None:
            comm_el = info_el.find(tag_fn('comments'))
            if comm_el is not None: info_el.remove(comm_el)
        try: self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]["comment"] = comment
        except Exception: pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_question_comment] {e}"); return False

def save_round_name(self, rnd_idx: int, new_name: str) -> bool:
    """Rename a round in the SIQ file."""
    try:
        root, ns_url, tag = self._load_xml_root()
        rnd_el, tag = self._nav_to_round(root, tag, rnd_idx)
        rnd_el.set('name', new_name)
        try: self.rounds[rnd_idx]["name"] = new_name
        except Exception: pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_round_name] {e}")
        return False

def add_theme(self, rnd_idx: int, theme_name: str = "") -> bool:
    """Append a new empty theme to a round in the SIQ file."""
    try:
        root, ns_url, tag = self._load_xml_root()
        rnd_el, tag = self._nav_to_round(root, tag, rnd_idx)
        themes_el = rnd_el.find(tag("themes"))
        if themes_el is None:
            themes_el = _api.ET.SubElement(rnd_el, tag("themes"))
        new_th = _api.ET.SubElement(themes_el, tag("theme"))
        new_th.set("name", theme_name or f"Тема {len(self.rounds[rnd_idx]['themes'])+1}")
        _api.ET.SubElement(new_th, tag("questions"))
        self.rounds[rnd_idx]["themes"].append({"name": new_th.get("name"), "questions": []})
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[add_theme] {e}")
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
        _api._logger.warning(f"[move_round] {e}")
        return False

def add_round(self, round_name: str = "") -> bool:
    """Append a new empty round to the SIQ file."""
    try:
        root, ns_url, tag = self._load_xml_root()
        rounds_el = root.find(tag("rounds"))
        if rounds_el is None:
            rounds_el = _api.ET.SubElement(root, tag("rounds"))
        new_rd = _api.ET.SubElement(rounds_el, tag("round"))
        new_rd.set("name", round_name or f"Раунд {len(self.rounds)+1}")
        _api.ET.SubElement(new_rd, tag("themes"))
        self.rounds.append({"name": new_rd.get("name"), "themes": []})
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[add_round] {e}")
        return False

def save_theme_name(self, rnd_idx: int, theme_idx: int, new_name: str) -> bool:
    """Rename a theme in the SIQ file."""
    try:
        root, ns_url, tag = self._load_xml_root()
        theme_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx)
        theme_el.set('name', new_name)
        # Update in-memory
        try: self.rounds[rnd_idx]["themes"][theme_idx]["name"] = new_name
        except Exception: pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_theme_name] {e}")
        return False
