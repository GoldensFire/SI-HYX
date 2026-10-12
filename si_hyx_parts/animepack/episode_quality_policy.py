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


class ProviderQuality:
    """Провайдеры Kuhi, у которых в проверенной серии все потоки ниже рамки.

    Релиз провайдера один на все серии тайтла, как и у RU-каталогов (см.
    ReleaseQuality). Раньше anikoto с 480p резолвился и проверялся в трёх
    сериях подряд: «Трогательный комплекс» терял так 3 минуты, «Ди Грэй-мен» —
    2,5. Провайдер, ответивший хоть одним годным или молчащим потоком, не
    отсекается."""

    def __init__(self):
        self._episode: dict = {}
        self._low: set = set()

    def record(self, stream, verdict):
        self._episode.setdefault(stream.get("provider"), set()).add(verdict)

    def finish_episode(self):
        """Итог серии: провайдеры, у которых проверенные потоки все «low»."""
        self._low |= {name for name, verdicts in self._episode.items()
                      if name and verdicts == {"low"}}
        self._episode = {}

    def providers(self, available):
        """Провайдеры серии без уже проверенных как низкие."""
        return {name: modes for name, modes in available.items() if name not in self._low}
