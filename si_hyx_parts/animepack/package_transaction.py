"""Publish a complete SIQ atomically, retaining no broken final archive."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


@contextmanager
def archive(target, zip_module, maximum=None):
    target = Path(target)
    descriptor, name = tempfile.mkstemp(prefix=target.stem + "-", suffix=".partial", dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zip_module.ZipFile(temporary, "w") as package:
            yield package
        with zip_module.ZipFile(temporary, "r") as package:
            infos = package.infolist()
            names = {info.filename for info in infos}
            if "content.xml" not in names:
                raise OSError("Не прошла проверка целостности SIQ: отсутствует content.xml")
            try:
                ET.fromstring(package.read("content.xml"))
            except Exception as error:
                raise OSError(f"Не прошла проверка целостности SIQ: повреждён content.xml ({error})") from error
            # Несжатые медиа (ZIP_STORED) не перечитываем целиком с диска;
            # проверяем только сжатые служебные потоки (JSON, субтитры).
            for info in infos:
                if info.compress_type != zip_module.ZIP_STORED and info.filename != "content.xml":
                    with package.open(info, "r") as stream:
                        while stream.read(65536):
                            pass
        if maximum is not None and temporary.stat().st_size > maximum:
            raise OSError(f"Размер готового пака {temporary.stat().st_size / 1048576:.1f} МБ "
                          f"превышает выбранный потолок {maximum / 1048576:.1f} МБ.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
