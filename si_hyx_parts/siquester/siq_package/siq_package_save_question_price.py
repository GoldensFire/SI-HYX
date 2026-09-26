# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SiqPackage: save_question_price. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


def save_question_price(self, rnd_idx: int, theme_idx: int, q_idx: int,
                        new_price: int) -> bool:
    """Change the price (номинал) of a question in the SIQ file."""
    try:
        root, ns_url, tag = self._load_xml_root()
        q_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx, q_idx)
        q_el.set('price', str(new_price))
        try: self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]["price"] = new_price
        except Exception: pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_price] {e}")
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
        _api._logger.warning("[save_round_prices] invalid args: "
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
                _api._qs_price_map[id(qs_list)] = {
                    q["price"]: idx for idx, q in enumerate(qs_list)}
                for idx, q in enumerate(qs_list):
                    self._q_index[(rnd_idx, t_idx, q["price"])] = idx
            except Exception:
                pass
        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_round_prices] {e}")
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
            params_el = _api.ET.SubElement(q_el, tag('params'))

        def get_or_create_param(name, ptype=None):
            for p in params_el.findall(tag('param')):
                if p.get('name') == name:
                    return p
            p = _api.ET.SubElement(params_el, tag('param'))
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
                new_it = _api.ET.SubElement(q_param, tag('item'))
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
        ao_param = _api.ET.SubElement(params_el, tag('param'))
        ao_param.set('name', 'answerOptions')
        ao_param.set('type', 'group')
        for key, text in answer_options.items():
            sub = _api.ET.SubElement(ao_param, tag('param'))
            sub.set('name', key)
            sub.set('type', 'content')
            it = _api.ET.SubElement(sub, tag('item'))
            it.text = text

        # ── right answer ───────────────────────────────────
        right_el = q_el.find(tag('right'))
        if right_el is None:
            right_el = _api.ET.SubElement(q_el, tag('right'))
        # Clear existing answers, write single correct key
        for a in right_el.findall(tag('answer')):
            right_el.remove(a)
        ans_el = _api.ET.SubElement(right_el, tag('answer'))
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
        except Exception as _e: _api._logger.debug(str(_e))

        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_select_question] {e}")
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
            params_el = _api.ET.SubElement(q_el, tag('params'))

        def _get_or_create(name):
            for p in params_el.findall(tag('param')):
                if p.get('name') == name: return p
            p = _api.ET.SubElement(params_el, tag('param')); p.set('name', name); return p

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
            right_el = _api.ET.SubElement(q_el, tag('right'))
        ans_els = right_el.findall(tag('answer'))
        coord_str = f"{cx:.4f},{cy:.4f}"
        if ans_els:
            ans_els[0].text = coord_str
        else:
            a = _api.ET.SubElement(right_el, tag('answer')); a.text = coord_str

        # Update in-memory
        try:
            q_obj = self.rounds[rnd_idx]["themes"][theme_idx]["questions"][q_idx]
            q_obj["price"] = new_price; q_obj["q_type"] = "point"
            q_obj["answers"] = [coord_str]; q_obj["answer_deviation"] = deviation
        except Exception as _e: _api._logger.debug(str(_e))

        return self._save_xml(root, ns_url)
    except Exception as e:
        _api._logger.warning(f"[save_point_question] {e}")
        return False

def add_question(self, rnd_idx: int, theme_idx: int, price: int) -> bool:
    """Add a new empty question (price, empty text, empty answer) to theme."""
    try:
        root, ns_url, tag = self._load_xml_root()
        theme_el, tag = self._nav_to_question(root, tag, rnd_idx, theme_idx)
        qs_el = theme_el.find(tag('questions'))
        if qs_el is None:
            qs_el = _api.ET.SubElement(theme_el, tag('questions'))
        q_el = _api.ET.SubElement(qs_el, tag('question'))
        q_el.set('price', str(price))
        params_el = _api.ET.SubElement(q_el, tag('params'))
        q_param = _api.ET.SubElement(params_el, tag('param'))
        q_param.set('name', 'question'); q_param.set('type', 'content')
        item_el = _api.ET.SubElement(q_param, tag('item')); item_el.text = ''
        right_el = _api.ET.SubElement(q_el, tag('right'))
        ans_el = _api.ET.SubElement(right_el, tag('answer')); ans_el.text = ''
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
        _api._logger.warning(f"[add_question] {e}")
        return False
