"""Парсер каталога sibrowser.ru.

Всё нужное (название, авторы, темы, кол-во вопросов, скачивания, теги, состав
контента) берётся прямо из карточки списка — отдельная страница пакета не нужна.
Список сортируется по скачиваниям (?sort=download_count), поэтому обход можно
останавливать, как только встретился пакет ниже порога скачиваний.
"""
from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config
from .normalize import normalize_name, normalize_theme, display_theme

_PID_RE = re.compile(r"/packages/(\d+)")
_CATEGORY_SLUG_RE = re.compile(r"/categories/([^/?#]+)")
_QC_RE = re.compile(r"(\d+)\s+вопрос")
_SIZE_RE = re.compile(r"([\d.,]+)\s*(КБ|МБ|ГБ|KB|MB|GB)", re.IGNORECASE)
_PCT_RE = re.compile(r"(\d+)\s*%")
_CONTENT_LABELS = {"Текст": "pct_text", "Фото": "pct_photo",
                   "Звук": "pct_audio", "Видео": "pct_video"}
_SIQ_SUFFIX_RE = re.compile(r"\.siq$", re.IGNORECASE)
# Не баг sibrowser.ru — некоторые авторы оставляют внутреннее название пакета
# (<package name="…"> в content.xml, именно оно попадает в <h1>) одинаковым
# для всех своих паков, различая их только именем .siq-файла при загрузке.
# Из-за этого паки такого автора получали одинаковый name_norm и затирали
# друг друга в БД при upsert (соберёшь 5 паков автора — в базе останется
# только последний). Фолбэк: если <h1> совпадает с этим известным «дефолтным»
# названием, берём в качестве имени itemprop="alternateName" (имя .siq-файла)
# — оно у таких авторов и есть единственное реально уникальное поле.
_AUTHOR_PAGE_GENERIC_TITLE = "Вопросы SIGame"


@dataclass
class Card:
    sibrowser_id: str | None
    name: str
    name_norm: str
    authors: list[str]
    download_count: int | None
    question_count: int | None
    round_count: int | None
    size_mb: float | None
    date_published: str | None
    tags: list[str]
    categories: list[dict]
    pct_text: int | None = None
    pct_photo: int | None = None
    pct_audio: int | None = None
    pct_video: int | None = None
    description: str | None = None
    themes: list[dict] = field(default_factory=list)

    def as_package(self) -> dict:
        d = self.__dict__.copy()
        d["length_group"] = config.length_group(self.question_count)
        return d


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT,
                      "Accept-Language": "ru,en;q=0.8"})
    # sibrowser.ru иногда рвёт соединение посреди ответа (ConnectionResetError
    # 10054) — транзиентная ошибка сервера/сети, не повод обрывать весь обход
    # каталога на первой же странице. Ретраим на уровне адаптера с backoff.
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def _parse_size_mb(text: str) -> float | None:
    m = _SIZE_RE.search(text or "")
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    unit = m.group(2).upper()
    return {"КБ": val / 1024, "KB": val / 1024,
            "МБ": val, "MB": val,
            "ГБ": val * 1024, "GB": val * 1024}.get(unit)


def _split_themes(text: str) -> list[str]:
    """Делит список тем раунда. Темы на sibrowser склеены через «, ».

    Разрываем ТОЛЬКО по запятой, за которой идёт пробел (как разделитель тем), и
    не внутри скобок. Запятая без пробела (числа «4,5», «1,000») и запятые в
    скобках («(ОП, опенинги)») не считаются границей темы — это снимает ложное
    дробление названий вроде «Опрометчивая перемотка (ОП, опенинги)».
    """
    parts: list[str] = []
    buf = ""
    depth = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
            buf += ch
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf += ch
        elif ch == "," and depth == 0 and (i + 1 >= n or text[i + 1].isspace()):
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _parse_themes(article) -> list[dict]:
    """Темы из блока «Темы в раундах»."""
    h2 = article.find(lambda t: t.name == "h2" and "Темы в раундах" in t.get_text())
    container = h2.parent if h2 else article
    spans = container.find_all("span", class_="text-neutral-500")
    result: list[dict] = []
    for r_idx, span in enumerate(spans):
        # имя раунда — ближайший непустой текстовый узел перед span
        round_name = ""
        prev = span.previous_sibling
        while prev is not None:
            name = getattr(prev, "name", None)
            if name == "br":
                prev = prev.previous_sibling
                continue
            if isinstance(prev, str):
                s = prev.strip()
                if s:
                    round_name = s.rstrip(":").strip()
                    break
                prev = prev.previous_sibling
                continue
            break  # наткнулись на тег (h2/span) — имени раунда нет
        themes_raw = _split_themes(span.get_text())
        t_idx = 0
        for raw in themes_raw:
            if not raw:
                continue
            result.append({
                "round_index": r_idx,
                "round_name": round_name or f"Раунд {r_idx + 1}",
                "theme_index": t_idx,
                "name": display_theme(raw),
                "name_norm": normalize_theme(raw),
                "source": "sibrowser",
            })
            t_idx += 1
    return result


def _parse_card(article) -> Card | None:
    # id пакета
    link = article.find("a", href=_PID_RE)
    pid = None
    if link:
        m = _PID_RE.search(link["href"])
        pid = m.group(1) if m else None

    # название
    h1 = article.find("h1")
    name = h1.get_text(strip=True) if h1 else None
    if not name or name == _AUTHOR_PAGE_GENERIC_TITLE:
        alt_el = article.find(attrs={"itemprop": "alternateName"})
        if alt_el:
            alt_name = _SIQ_SUFFIX_RE.sub("", alt_el.get_text(strip=True)).strip()
            name = alt_name or name
    if not name:
        return None

    # авторы
    authors = []
    for au in article.find_all(attrs={"itemprop": "author"}):
        nm = au.find(attrs={"itemprop": "name"})
        if nm:
            txt = nm.get_text(strip=True)
            if txt:
                authors.append(txt)

    # дата
    time_el = article.find("time")
    date_pub = time_el.get("datetime") if time_el else None

    # размер
    size_el = article.find(attrs={"itemprop": "contentSize"})
    size_mb = _parse_size_mb(size_el.get_text()) if size_el else None

    # количество скачиваний
    dl_el = article.find(
        "span", attrs={"data-packages--download_link--component-target": "count"})
    download_count = None
    if dl_el:
        digits = re.sub(r"\D", "", dl_el.get_text())
        download_count = int(digits) if digits else None

    # вопросы + состав контента из таблицы распределения
    qc = None
    pct = {v: None for v in _CONTENT_LABELS.values()}
    table = article.find("table")
    if table:
        m = _QC_RE.search(table.get_text())
        qc = int(m.group(1)) if m else None
        cells = [td.get_text(strip=True) for td in table.find_all("td")]
        for i, c in enumerate(cells):
            if c in _CONTENT_LABELS and i + 1 < len(cells):
                pv = _PCT_RE.search(cells[i + 1])
                if pv:
                    pct[_CONTENT_LABELS[c]] = int(pv.group(1))

    # теги и категории
    tags = [a.get_text(strip=True) for a in article.select('a[rel~="tag"]')]
    categories = []
    for a in article.select('a[rel~="category"]'):
        spans = a.find_all("span")
        cname = spans[0].get_text(strip=True) if spans else a.get_text(strip=True)
        cpct = None
        pv = _PCT_RE.search(a.get_text())
        if pv:
            cpct = int(pv.group(1))
        slug = None
        m = _CATEGORY_SLUG_RE.search(a.get("href", ""))
        if m:
            slug = m.group(1)
        categories.append({"name": cname, "pct": cpct, "slug": slug})

    themes = _parse_themes(article)
    round_count = (max((t["round_index"] for t in themes), default=-1) + 1) or None

    # описание пака (свободный текст автора) — лежит прямо в карточке списка.
    desc_el = article.find(attrs={"itemprop": "description"})
    description = desc_el.get_text(strip=True) if desc_el else None

    return Card(
        sibrowser_id=pid,
        name=name,
        name_norm=normalize_name(name),
        authors=authors,
        download_count=download_count,
        question_count=qc,
        round_count=round_count,
        size_mb=size_mb,
        date_published=date_pub,
        tags=[t for t in tags if t],
        categories=categories,
        description=description or None,
        themes=themes,
        **pct,
    )


def parse_list(html: str) -> list[Card]:
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for article in soup.find_all("article", attrs={"itemprop": "itemListElement"}):
        try:
            card = _parse_card(article)
            if card:
                cards.append(card)
        except Exception:
            continue
    return cards


def _friendly_network_error(e: Exception) -> str:
    """Ретраи в make_session() уже покрывают разовые обрывы соединения — если
    ошибка всё равно долетела сюда, значит sibrowser.ru недоступен систематически
    (обрывает КАЖДУЮ попытку, включая повторные с задержкой). На практике для
    пользователей из РФ это обычно не баг сайта/приложения, а блокировка на
    уровне провайдера (сброс TCP-соединения — тот же почерк, что у операторских
    DPI-блокировок), а не временный сетевой сбой — сырой текст исключения этого
    не объясняет и выглядит как поломка приложения."""
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return (f"{e}\n"
                "Похоже, sibrowser.ru недоступен на уровне сети/провайдера (соединение "
                "обрывается даже после повторных попыток) — это не ошибка приложения. "
                "Попробуйте VPN или прокси (переменные окружения HTTP_PROXY/HTTPS_PROXY "
                "перед запуском SI-HYX — requests подхватывает их автоматически).")
    return str(e)


def fetch_list_html(session: requests.Session, page: int,
                    sort: str | None = "download_count",
                    category_slug: str | None = None) -> str:
    """sort='download_count' — по скачиваниям; sort=None — по дате (новые сверху).

    category_slug — если задан, обходится не общий каталог, а страница категории
    (/categories/<slug>) — сайт уже отдаёт там только паки с этой категорией."""
    base = f"{config.SIBROWSER_BASE}/categories/{category_slug}" if category_slug \
        else config.SIBROWSER_BASE
    if sort:
        url = f"{base}/?page={page}&sort={sort}"
    else:
        url = f"{base}/?page={page}"
    resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_full_description(session: requests.Session, sibrowser_id: str) -> str | None:
    """Полное описание пака со СТРАНИЦЫ ПАКА (не карточки списка — там описание
    урезано автором сайта многоточием, см. _parse_card). Запрашивается лениво,
    по одному пакету, только когда пользователь открывает его карточку в
    интерфейсе — не во время массового сбора (иначе N лишних запросов на
    каждый пак, ради чего карточки списка и парсятся без похода на саму
    страницу, см. модульный docstring)."""
    url = f"{config.SIBROWSER_BASE}/packages/{sibrowser_id}"
    resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    p = soup.select_one("p.pt-2")
    if p is None:
        return None
    text = p.get_text(strip=True)
    return text or None


def _category_pct(card: Card, category_slug: str | None) -> int | None:
    """% доминирующей категории пака, если она совпадает с category_slug (или
    первая доступная, если слаг не указан)."""
    for c in card.categories:
        if c.get("pct") is None:
            continue
        if category_slug is None or c.get("slug") == category_slug:
            return c["pct"]
    return None


def iter_cards(
    session: requests.Session,
    min_downloads: int,
    skip_norms: set[str],
    mode: str = "downloads",
    cutoff_date: str | None = None,
    category_slug: str | None = None,
    category_min_pct: int = 0,
    max_pages: int = 400,
    start_page: int = 1,
    state: dict | None = None,
    progress_cb: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[Card]:
    """Идёт по страницам каталога и отдаёт новые карточки.

    mode='downloads' — сортировка по скачиваниям; стоп, когда скачиваний меньше
        порога min_downloads.
    mode='date' — сортировка по дате (новые сверху); собираются паки с датой
        публикации >= cutoff_date (ISO 'YYYY-MM-DD'); порог скачиваний при этом
        работает как доп. фильтр (пак ниже порога пропускается, но обход не
        останавливается).
    category_slug — если задан, обходится страница категории (сайт уже
        предфильтровал паки по ней), а category_min_pct дополнительно требует,
        чтобы доля этой категории в паке была не меньше порога (например,
        «только паки, где Аниме >= 50%»). Паки ниже порога пропускаются, но
        обход не останавливается — режим downloads/date продолжает работать как
        обычно поверх уже суженного списком категории набора страниц.
    start_page — с какой страницы каталога начинать (для продолжения
        предыдущего обхода вместо повторного пролистывания с начала).
    state — если передан, в него после каждой обработанной страницы
        записывается state['last_page'] (для кэширования между запусками) и
        после каждой рассмотренной карточки — state['last_card'] (сама
        карточка, включая дату публикации — для отчёта «докуда дошли»).

    Эта функция НЕ знает про целевое количество «набрали нужное — хватит»:
    она просто отдаёт кандидатов подряд, пока не кончится каталог (или
    max_pages/should_stop). Решение «набрали нужное количество, пора
    остановиться» — на стороне collector.collect(): часть отданных карточек
    он же ещё и отсеивает (мин. начатых игр, чёрный список авторов), поэтому
    считать здесь «отдали N штук — хватит» неверно: если что-то отсеется у
    вызывающего, он получит меньше пакетов, чем просили.
    В обоих режимах останавливается при достижении конца каталога.
    """
    sort = "download_count" if mode == "downloads" else None
    for page in range(start_page, start_page + max_pages):
        if should_stop and should_stop():
            return
        if progress_cb:
            progress_cb(f"Страница {page}…")
        try:
            html = fetch_list_html(session, page, sort=sort, category_slug=category_slug)
        except Exception as e:
            if progress_cb:
                progress_cb(f"Ошибка загрузки страницы {page}: {_friendly_network_error(e)}")
            break
        cards = parse_list(html)
        if not cards:
            break
        if state is not None:
            state["last_page"] = page
        for card in cards:
            if should_stop and should_stop():
                return
            if state is not None:
                state["last_card"] = card
            if mode == "downloads":
                if card.download_count is not None and card.download_count < min_downloads:
                    return  # дальше скачиваний только меньше — выходим
            else:  # date
                if cutoff_date and card.date_published and card.date_published < cutoff_date:
                    return  # дошли до паков старше выбранной даты
                if card.download_count is not None and card.download_count < min_downloads:
                    continue  # ниже порога — пропускаем, но не останавливаемся
            if category_min_pct > 0:
                pct = _category_pct(card, category_slug)
                if pct is None or pct < category_min_pct:
                    continue  # доля категории ниже порога — пропускаем
            if card.name_norm in skip_norms:
                continue
            skip_norms.add(card.name_norm)
            yield card
        time.sleep(config.SCRAPE_DELAY)


def download_url(sibrowser_id: str) -> str:
    return f"{config.SIBROWSER_BASE}/packages/{sibrowser_id}/direct_download"


def play_url(sibrowser_id: str, name: str) -> str:
    """URL SIGame с уже подставленным паком — повторяет то, что делает кнопка
    «Играть» на sibrowser.ru (переход на /packages/<id>/direct_play в итоге
    редиректит именно на этот адрес, см. запрос в devtools:
    sigame.vladimirkhil.com/?packageUri=<direct_download url>&packageName=<имя>)."""
    import urllib.parse
    package_uri = download_url(sibrowser_id)
    return (f"{config.SIGAME_BASE}/?packageUri={urllib.parse.quote(package_uri, safe='')}"
            f"&packageName={urllib.parse.quote(name, safe='')}")


def fetch_author_html(session: requests.Session, author: str, page: int = 1) -> str:
    import urllib.parse
    url = f"{config.SIBROWSER_BASE}/authors/{urllib.parse.quote(author, safe='')}?page={page}"
    resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def iter_author_cards(
    session: requests.Session,
    author: str,
    max_pages: int = 25,
    progress_cb: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[Card]:
    """Все паки конкретного автора (по страницам /authors/<author>)."""
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        if should_stop and should_stop():
            return
        if progress_cb:
            progress_cb(f"Страница автора {page}…")
        try:
            html = fetch_author_html(session, author, page)
        except Exception as e:
            if progress_cb:
                progress_cb(f"Ошибка загрузки страницы автора {page}: {_friendly_network_error(e)}")
            break
        cards = parse_list(html)
        fresh = [c for c in cards if c.name_norm not in seen]
        if not fresh:
            break  # пагинация закончилась (или зациклилась)
        for card in fresh:
            seen.add(card.name_norm)
            # только реально авторские паки
            if any(author.lower() == a.lower() for a in card.authors):
                yield card
        time.sleep(config.SCRAPE_DELAY)
