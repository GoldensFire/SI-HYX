# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""PackUpgrader: _write. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _write(self, root, ns: str, cname: str, out_path: _api.Optional[str],
           images: _api.Optional[dict] = None,
           dropped: _api.Optional[set] = None) -> str:
    """Пишет новый .siq: правленый content.xml плюс все прочие записи как
        есть. Исходный файл не трогается — на случай, если правка не понравится.

        images — {имя записи: (новое имя, путь к готовому файлу)}: такие записи
        подменяются пережатыми, остальные копируются байт в байт. dropped —
        имена записей, которые в новый пак не идут вовсе (мусор без ссылок)."""
    images = images or {}
    dropped = dropped or set()
    if ns:
        # Иначе ElementTree расставит по всему файлу префиксы ns0:, и пак
        # перестанет открываться в SIGame.
        _api.ET.register_namespace("", ns)
    xml = _api.ET.tostring(root, encoding="utf-8", xml_declaration=True)
    target = self._out_path(out_path)
    try:
        with _api.zipfile.ZipFile(self.path) as src, \
                _api.zipfile.ZipFile(target, "w") as dst:
            dst.writestr(cname, xml, _api.zipfile.ZIP_DEFLATED)
            for info in src.infolist():
                if (info.filename == cname or info.is_dir()
                        or info.filename in dropped):
                    continue
                made = images.get(info.filename)
                if made:
                    # Сжатая картинка: имя новое (.avif), сжимать её ещё и
                    # архиватором незачем — AVIF уже сжат.
                    with open(made[1], "rb") as f:
                        dst.writestr(made[0], f.read(), _api.zipfile.ZIP_STORED)
                    continue
                # Копируем запись КАК ЕСТЬ, вместе с её способом сжатия:
                # медиа в паках лежит уже сжатым (opus/avif/mp4), и разжимать
                # его, чтобы тут же сжать обратно, — чистая трата времени.
                if not _api.copy_zip_entry(src, dst, info):
                    dst.writestr(_api.copy.copy(info), src.read(info.filename))
            # Файлы, которых в исходном паке не было (постеры из ответов).
            for name, tmp in (self._extra or {}).items():
                if not _api.os.path.exists(tmp):
                    continue
                with open(tmp, "rb") as f:
                    dst.writestr(name, f.read(), _api.zipfile.ZIP_STORED)
    except (OSError, _api.zipfile.BadZipFile) as e:
        raise _api.UpgradeError(f"Не удалось записать пак: {e}") from e
    return target
