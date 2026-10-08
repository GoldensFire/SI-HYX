"""Stop generation before a full volume destroys temporary media or a pack."""
import errno
from pathlib import Path
import shutil

MIB = 1024 * 1024
WORK_RESERVE = 256 * MIB
START_RESERVE = 1024 * MIB


class StorageError(OSError):
    def __init__(self, path, required, available):
        super().__init__(errno.ENOSPC,
                         f"Недостаточно места на диске для {path}: свободно {available / MIB:.0f} МиБ, "
                         f"нужно не менее {required / MIB:.0f} МиБ. Освободите место; готовые вопросы сохраняются.",
                         str(path))


def require_space(path, required=WORK_RESERVE):
    location = Path(path).absolute()
    while not location.exists() and location != location.parent:
        location = location.parent
    available = shutil.disk_usage(location).free
    if available < required:
        raise StorageError(location, required, available)


def raise_if_full(error, path):
    if isinstance(error, StorageError):
        raise error
    text = str(error).casefold()
    if (getattr(error, "errno", None) == errno.ENOSPC
            or any(word in text for word in ("no space left", "disk full", "not enough space", "недостаточно места"))):
        raise StorageError(path, WORK_RESERVE, 0) from (error if isinstance(error, BaseException) else None)
