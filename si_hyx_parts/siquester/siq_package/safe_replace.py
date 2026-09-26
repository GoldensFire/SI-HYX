# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_safe_replace. Public namespace: siquester.siq_package."""
import siquester.siq_package as _api


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
            _api.os.chmod(dst, _api._stat.S_IWRITE | _api._stat.S_IREAD)
        except OSError:
            pass

    _clear_readonly()

    last_err: OSError | None = None
    for _attempt in range(5):
        try:
            _api.os.replace(tmp, dst)
            return
        except OSError as _e:        # PermissionError (WinError 5/32) ⊂ OSError
            last_err = _e
            _api._time.sleep(0.2 * (_attempt + 1))

    # Atomic replace impossible — fall back to overwriting the file in place.
    # An overwrite only needs write access to the *existing* file, not the right
    # to delete its directory entry, so it beats a lingering shared read handle
    # or Controlled-Folder-Access that blocks the rename. The lock is still
    # often transient (OneDrive/AV/indexer), so retry this fallback too, clearing
    # the read-only bit before every attempt and backing off between tries.
    for _attempt in range(5):
        try:
            _clear_readonly()
            _api._shutil.copyfile(tmp, dst)
            try:
                _api.os.remove(tmp)
            except OSError:
                pass
            return
        except OSError as _e:
            last_err = _e
            _api._time.sleep(0.3 * (_attempt + 1))

    # Truly locked for writing — leave the original file untouched and let the
    # caller surface an actionable message. (copyfile only ever raised before
    # opening dst for write here, so dst is still the intact previous version.)
    try:
        _api.os.remove(tmp)
    except OSError:
        pass
    raise last_err if last_err is not None else OSError(f"could not replace {dst}")

_safe_replace.__module__ = _api.__name__
_api._safe_replace = _safe_replace

class SiqPackage:

    from si_hyx_parts.siquester.siq_package.siq_package___init import (
        __init__,
        _parse,
        _parse_rounds,
        _parse_q,
    )

    from si_hyx_parts.siquester.siq_package.siq_package_extract_media import (
        extract_media,
        find_q_idx,
        find_question,
        rebuild_index_for_theme,
        _save_xml,
        _reload_rounds,
        _rewrite_zip,
        _load_xml_root,
    )

    _registered_ns: set = set()   # class-level set; ns registration is process-global

    from si_hyx_parts.siquester.siq_package.siq_package__xml_to_bytes import (
        _xml_to_bytes,
        _nav_to_question,
        _nav_to_round,
        _xml_nav_q,
        save_question,
        save_pkg_info,
        save_round_info,
        save_question_comment,
        save_round_name,
        add_theme,
        move_round,
        add_round,
        save_theme_name,
    )

    from si_hyx_parts.siquester.siq_package.siq_package_save_question_price import (
        save_question_price,
        save_round_prices,
        save_select_question,
        save_point_question,
        add_question,
    )

    from si_hyx_parts.siquester.siq_package.siq_package_add_media_to_question import (
        add_media_to_question,
        close,
    )

SiqPackage.__module__ = _api.__name__
_api.SiqPackage = SiqPackage
