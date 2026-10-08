"""Publish a complete SIQ atomically, retaining no broken final archive."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


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
            damaged = package.testzip()
            if damaged:
                raise OSError(f"Не прошла проверка целостности SIQ: {damaged}")
        if maximum is not None and temporary.stat().st_size > maximum:
            raise OSError(f"Размер готового пака {temporary.stat().st_size / 1048576:.1f} МБ "
                          f"превышает выбранный потолок {maximum / 1048576:.1f} МБ.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
