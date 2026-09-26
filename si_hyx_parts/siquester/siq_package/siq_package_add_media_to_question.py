# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""SiqPackage: add_media_to_question. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


def add_media_to_question(self, rnd_idx: int, theme_idx: int, q_idx: int,
                           file_path: str, param_name: str = 'question') -> bool:
    """Copy a local media file into the SIQ zip and add a ref item to the question."""
    ext = _api.os.path.splitext(file_path)[1].lower()
    if   ext in _api._IMG_EXTS:   itype, folder = 'image', 'Images'
    elif ext in _api._AUDIO_EXTS: itype, folder = 'audio', 'Audio'
    elif ext in _api._VIDEO_EXTS: itype, folder = 'video', 'Video'
    elif ext in _api._HTML_EXTS:  itype, folder = 'html', 'Html'
    else:
        print(f"[add_media] unsupported extension: {ext}")
        return False
    try:
        fname = _api.os.path.basename(file_path)
        # Zip entry uses the ORIGINAL (non-encoded) filename so SIGame can find it.
        # content.xml item.text uses the URL-encoded form (SIQ5 spec).
        existing = set(self._zip.namelist())
        candidate = f'{folder}/{fname}'
        counter = 1
        while candidate in existing:
            stem, suf = _api.os.path.splitext(fname)
            candidate = f'{folder}/{stem}_{counter}{suf}'; counter += 1
        zip_name = candidate                             # original name in zip
        ref_text = _api.os.path.basename(zip_name)           # plain filename → item.text (no URL encoding)

        root, ns_url, tag, q_el = self._xml_nav_q(rnd_idx, theme_idx, q_idx)
        params_el = q_el.find(tag('params'))
        if params_el is None:
            params_el = _api.ET.SubElement(q_el, tag('params'))
        # Find or create the target param
        target_param = None
        for p in params_el.findall(tag('param')):
            if p.get('name') == param_name:
                target_param = p; break
        if target_param is None:
            target_param = _api.ET.SubElement(params_el, tag('param'))
            target_param.set('name', param_name); target_param.set('type', 'content')
        new_item = _api.ET.SubElement(target_param, tag('item'))
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
            with _api.zipfile.ZipFile(self.path, 'r') as zin:
                with _api.zipfile.ZipFile(tmp, 'w') as zout:
                    for info in zin.infolist():
                        if info.filename == 'content.xml':
                            xi = _api.zipfile.ZipInfo('content.xml')
                            xi.compress_type = _api.zipfile.ZIP_DEFLATED
                            zout.writestr(xi, self._xml_to_bytes(root, ns_url))
                        else:
                            # Stream-copy compressed bytes — avoids buffering large
                            # MP4/MP3 files entirely in memory (same fix as _rewrite_zip).
                            with zin.open(info) as src, zout.open(info, 'w') as dst:
                                _api._shutil.copyfileobj(src, dst, length=1 << 20)
                    # New media: store without re-compression (already compressed).
                    # Stream from disk — avoids buffering up to 10 MB in RAM.
                    mi = _api.zipfile.ZipInfo(zip_name)
                    mi.compress_type = _api.zipfile.ZIP_STORED
                    with open(file_path, 'rb') as mf, zout.open(mi, 'w') as dst:
                        _api._shutil.copyfileobj(mf, dst, length=1 << 20)
            _api._safe_replace(tmp, self.path)
            self._zip = _api.zipfile.ZipFile(self.path, 'r')
            # Keep _zip_sizes consistent: add the new entry's size from disk.
            try:
                self._zip_sizes[zip_name] = _api.os.path.getsize(file_path)
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
                                       "dur": 5.0 if itype in ('image', 'html') else 0.0,
                                       "placement": "", "simultaneous": False,
                                       "wait_for_finish": "True", "xml_duration": ""})
            except Exception as _e: _api._logger.debug(str(_e))
            return True
        except Exception as e:
            _api._logger.warning(f"[add_media zip] {e}")
            if _api.os.path.exists(tmp):
                try: _api.os.remove(tmp)
                except Exception: pass
            if self._zip is None:
                try: self._zip = _api.zipfile.ZipFile(self.path, 'r')
                except Exception: pass
            return False
    except Exception as e:
        _api._logger.warning(f"[add_media] {e}")
        return False

def close(self):
    if self._zip: self._zip.close(); self._zip = None
    if self._tmp_dir and _api.os.path.exists(self._tmp_dir):
        _api.shutil.rmtree(self._tmp_dir, ignore_errors=True); self._tmp_dir = None
