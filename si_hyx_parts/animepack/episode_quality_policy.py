"""Quality floors for HD releases and titles from the SD broadcast era."""
from __future__ import annotations

HD_HEIGHT = 1080
SD_HEIGHT = 480
# A release date is a fallback policy, not proof that a film has no HD scan.
# Always prefer the highest verified rendition offered by the source.
SD_LAST_YEAR = 2005


def minimum(candidate):
    year = int(getattr(candidate, "year", 0) or 0)
    return SD_HEIGHT if 0 < year <= SD_LAST_YEAR else HD_HEIGHT


def floor(stream):
    return int(stream.get("min_height") or HD_HEIGHT)


def output_height(stream):
    return min(720, int(stream.get("source_height") or 720))


class ReleaseQuality:
    """Какие релизы тайтла уже проверены ниже нужного разрешения.

    Релиз — источник, плеер и озвучка/субтитры. Разрешение у всех его серий
    одно, а добыть поток серии дорого (страница плеера, браузер, манифест):
    раньше это повторялось в каждой из трёх случайных серий, и на тайтле без
    1080p уходило до четырёх минут, прежде чем выяснялось, что брать нечего."""

    def __init__(self):
        # _unsure — у релиза был вариант, который не ответил («pause»): про
        # его разрешение ничего не известно, и релиз не пропускаем.
        self._low, self._ok, self._unsure = set(), set(), set()
        self.skipped = 0

    @staticmethod
    def key(row):
        return row.get("source"), row.get("player"), str(row.get("release", ""))

    def record(self, stream, verdict):
        key = self.key(stream)
        if verdict == "ok":
            self._ok.add(key)
            self._low.discard(key)
        elif verdict == "low" and key not in self._ok:
            self._low.add(key)
        elif verdict == "pause":
            self._unsure.add(key)

    def low(self, row) -> bool:
        key = self.key(row)
        if key in self._low and key not in self._unsure:
            self.skipped += 1
            return True
        return False
