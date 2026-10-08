"""Local opt-out for a measured unusable Kim model; no automatic reinstall."""
import json
from pathlib import Path

from .hardware import adapters

STATUS = Path.home() / ".cache/si-hyx-karaoke/models/kim-disabled.json"


def gpu_names():
    return sorted(name for name in adapters() if any(
        word in name.casefold() for word in ("amd", "radeon", "intel", "nvidia")))


def kim_disabled():
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
        return bool(data.get("disabled") and data.get("adapters") == gpu_names())
    except (OSError, ValueError, TypeError):
        return False


def disable_kim(reason):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"disabled": True, "adapters": gpu_names(), "reason": reason},
                                ensure_ascii=False, indent=2), encoding="utf-8")
