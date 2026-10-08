"""Worker-local reader cursors with shared provider pacing and CDN health."""
from dataclasses import dataclass
import threading
import time
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PageSelection:
    url: str
    chapter: str
    titles: tuple
    source_link: str
    client: object
    info: dict
    errors: tuple


def bot_wall(response) -> str:
    """Имя защиты от ботов, ответившей вместо картинки ("" — обычный 403).

    Такая стена (DDoS-Guard у CDN ReManga) требует браузерной JS-проверки и за
    90 секунд паузы не открывается: каждая следующая страница — тот же 403."""
    headers = getattr(response, "headers", None) or {}
    server = str(headers.get("Server") or "").casefold()
    if "ddos-guard" in server:
        return "DDoS-Guard"
    if str(headers.get("cf-mitigated") or "").casefold() == "challenge":
        return "Cloudflare"
    return ""


class ReaderHealth:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures, self.until = {}, {}
        self.provider_until = {}
        self.walls = {}   # хост → имя защиты; выключен до конца прогона

    def wall(self, url):
        with self.lock:
            return self.walls.get(urlsplit(url).hostname, "")

    def provider_available(self, name):
        with self.lock:
            return self.provider_until.get(name, 0) <= time.monotonic()

    def disable_provider(self, name):
        with self.lock:
            self.provider_until[name] = float("inf")

    def defer_provider(self, name):
        with self.lock:
            self.provider_until[name] = time.monotonic() + 90

    def available(self, url):
        with self.lock:
            return self.until.get(urlsplit(url).hostname, 0) <= time.monotonic()

    def record(self, url, error=None, provider=""):
        host = urlsplit(url).hostname
        with self.lock:
            if error is None:
                self.failures.pop(host, None)
                return
            response = getattr(error, "response", None)
            code = getattr(response, "status_code", None)
            if code not in (403, 429):
                return
            wall = bot_wall(response) if code == 403 else ""
            if wall:
                self.walls[host] = wall
                self.until[host] = float("inf")
                if provider:
                    self.provider_until[provider] = float("inf")
                return
            count = self.failures.get(host, 0) + 1
            self.failures[host] = count
            if count >= 3:
                self.until[host] = time.monotonic() + 90
                if provider:
                    self.provider_until[provider] = time.monotonic() + 90


def worker(source):
    if source._injected:
        return source
    current = getattr(source._worker_local, "reader", None)
    if current is None:
        from .manga_page_sources import MangaPageSources
        current = MangaPageSources(**source._worker_options)
        current._health = source._health
        originals = dict(source.clients)
        for name, client in current.clients:
            original = originals[name]
            if hasattr(original, "limiter"):
                client.limiter = original.limiter
            if hasattr(original, "pages_limiter"):
                client.pages_limiter = original.pages_limiter
            population = getattr(client, "population", None)
            if population is not None:
                population.limiter = original.population.limiter
            client._source_health = source._health
            client._source_health_key = name
        source._worker_local.reader = current
        with source._workers_lock:
            source._workers.append(current)
    return current


def select_page(source, card, excluded=(), deadline=None, stopped=lambda: False):
    current = worker(source)
    for _, client in current.clients:
        client.deadline = deadline
        population = getattr(client, "population", None)
        if population is not None:
            population.stopped = lambda: stopped() or (
                deadline is not None and time.monotonic() >= deadline)
    lock = source._workers_lock if source._injected else threading.RLock()
    with lock:
        url = current.panel_url(card, excluded)
        return PageSelection(url, current.last_chapter, tuple(current.last_titles),
                             current.last_source_link, current.last_client,
                             dict(current.last_page_info), tuple(current.last_errors))


def close(source):
    with source._workers_lock:
        readers, source._workers = source._workers, []
    for reader in readers:
        for _, client in reader.clients:
            for owner in (client, getattr(client, "population", None)):
                session = getattr(owner, "session", None)
                if session is not None:
                    session.close()
