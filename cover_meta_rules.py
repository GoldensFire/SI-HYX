# -*- coding: utf-8 -*-
"""Vocabulary of the cover metadata gate: what a title has to say, and mustn't.

Все выражения ниже проверены на 3681 настоящем результате поиска YouTube по 129
песням (tools/cover_probe.py --collect), из которых 421 заголовок размечен
руками (tools/cover_cases.json). Комментарии держат причину, а не пересказ:
каждый пункт здесь появился из конкретного разобранного заголовка.

Отдельный модуль от cover_meta нарочно: тут словарь, там решение. Словарь
пополняется каждым новым разбором корпуса, логика — почти никогда.
"""
from __future__ import annotations

import re
import unicodedata

# ── чем кандидат не является ни при каких маркерах ─────────────────────────
# Разбор и реакция: внутри играет ОРИГИНАЛ, по звуку они неотличимы от кавера
# (на замерах 314 и 60 очков при пороге 60).
REACTION = re.compile(
    r"react(?:ion|s|ing)?\b|\breacts?\s+to\b|реакц|обзор|\breview\b"
    r"|first\s+time\s+(?:hearing|listening)|blind\s+(?:react|listen)"
    r"|what\s+happened|explained|\banalysis\b|разбор|impressions?\b"
    r"|discussion\b", re.IGNORECASE)
# Учебное видео. ВАЖНО: tab/tabs здесь НЕТ — «Guitar Instrumental Cover + Tabs»
# и «【TAB】… Guitar cover» это настоящие исполнения, табы у них в описании.
TUTORIAL = re.compile(
    r"tutorial|how\s+to\s+play|\blesson\b|\bурок\b"
    r"|synthesia|piano\s+roll|\bmidi\b|noteblock|minecraft|\broblox\b"
    # Разбор вокала: поют там по-настоящему, но вперемешку с объяснением, как
    # это делать. Школа «シアーミュージック» встретилась так на трёх песнях подряд.
    r"|歌い方|ボイストレーナ|発声練習|\btranscription\b", re.IGNORECASE)
# «Ноты» сами по себе туториалом не делают: исполнители сплошь дописывают их к
# настоящему кавору («Piano Cover with Sheets!», «Guitar Cover + Tabs»).
# Отказываем по ним только когда слова cover в заголовке нет вовсе.
SHEETS_ONLY = re.compile(r"sheet\s*music|\bsheets?\b|\btabs?\b", re.IGNORECASE)
# Караоке отвергается ВСЕГДА, даже с маркером исполнения (просьба
# пользователя): под минусовку поют мимо нот и в зал, и для вопроса это
# оригинальная аранжировка с посторонним голосом поверх. Раньше «(Karaoke
# Cover)» проходил как настоящее исполнение — теперь нет.
KARAOKE = re.compile(r"karaoke|カラオケ|караоке", re.IGNORECASE)
# Живьём — тоже мимо (просьба пользователя): в концертной записи слышен зал,
# микрофон и та же самая аранжировка, а звук вдобавок хуже студийного.
LIVE = re.compile(r"\blive\b|\blive[ _-]?(?:ver|session|performance|stage)\b"
                  r"|концерт|\bconcert\b|\bgig\b|\bunplugged\b"
                  r"|ライブ|生演奏|\bfes(?:tival)?\s+\d{4}\b", re.IGNORECASE)
# Игра ПОД ОРИГИНАЛ: барабанщик, басист или гитарист играет свою партию поверх
# самой записи, и оригинальный вокал в ролике слышно целиком (просьба
# пользователя). Угадывать там нечего — звучит оригинал.
# «Drum cover» и «bass cover» попали сюда целиком нарочно: сольного исполнения
# песни одними барабанами не бывает, так подписывают именно игру под запись.
PLAYALONG = re.compile(
    r"\bdrums?\s*(?:cover|cam|playthrough|play\s*-?\s*through)\b"
    r"|\bbass\s*(?:cover|cam|playthrough|play\s*-?\s*through)\b"
    r"|\b(?:cover|кавер)\s+(?:on\s+)?drums?\b"
    r"|play\s*-?\s*along|playthrough|play\s*-?\s*through"
    r"|backing\s+track|\bjam\s+session\b|\bdrumeo\b"
    r"|叩いてみた|ドラム(?:で)?(?:叩|演奏)|ベース(?:で)?弾いてみた",
    re.IGNORECASE)
# Заведомо плохая запись: сам автор пишет про микрофон, черновик и «первый
# раз» (просьба пользователя — низкокачественные каверы не берём).
LOW_QUALITY = re.compile(
    r"\blow\s*-?\s*quality\b|\bbad\s+(?:quality|audio|mic|singing)\b"
    r"|\bpoor\s+quality\b|\bmic\s+test\b|\btest\s+record|\brecord\s+test\b"
    r"|\bdemo\s+(?:ver|version|take)\b|\brough\s+(?:cut|mix|take)\b"
    r"|\bwork\s+in\s+progress\b|\bw\.?i\.?p\.?\b|unfinished|unmastered"
    r"|\bpractice\b|\brehearsal\b|\bfirst\s+(?:try|take|attempt|cover)\b"
    r"|\bphone\s+(?:mic|record)"
    r"|練習|音質(?:が)?悪|черновик|\bпроба\b|плохое\s+качество",
    re.IGNORECASE)
# Производное от той же записи, а не новое исполнение: тембр и вокал остались
# оригинальные, и для угадайки это оригинал с фильтром.
DERIVATIVE = re.compile(
    r"nightcore|sped\s*-?\s*up|spedup|speed\s*up|slowed|reverb|8d\s+audio"
    r"|bass\s*boost|\bremix\b|mashup|off\s*-?\s*vocal|минус\b"
    # ИИ-перепевки: оригинальная инструменталка плюс склонированный голос.
    # Для вопроса это оригинал, а не исполнение.
    r"|\bai\s+(?:cover|voice)\b|voice\s*model|\brvc\b|so-?vits"
    r"|all\s+characters\s+sing"
    # Шуточные «исполнения»: мяуканье и склейки по нотам. Мелодия там угадаешь,
    # но это не исполнение, а мем — в вопросе ему делать нечего.
    r"|猫が歌|\bcats?\s+sing", re.IGNORECASE)
# Сборник: одна песня занимает в нём секунды, вырезать из него нечего.
COMPILATION = re.compile(
    r"\btop\s*\d|\bbest\s+anime\b|compilation|full\s+album|\ball\s+(?:openings|endings)"
    r"|openings?\s+and\s+endings?|\bmedley\b|\bplaylist\b|\bmix\b|\b1\s*hour\b"
    r"|(?:op|ed|ending|opening)s?\s*\d\s*-\s*\d", re.IGNORECASE)
# Субтитры поверх оригинала. «Lời Việt» и «fandub» сюда НЕ входят: там песню
# перепевают, это полноценный кавер на другом языке.
SUBBED = re.compile(
    r"vietsub|thaisub|\bsub\s+(?:espa|indo|ita|ptbr)|legendado|\blyrics?\s+video\b"
    r"|kan\s*/\s*rom|\[\s*(?:kan|rom)|english\s+sub", re.IGNORECASE)
# Нарезка под музыку и съёмка с косплей-фестиваля: дорожка там оригинальная.
# «(Ep 6 BGM)» — фоновая музыка серии, а не наша песня.
CLIPPED = re.compile(
    r"\bamv\b|\bedit\b|\bcosplay\b|\bexpo\b|convention|\bbgm\b"
    r"|\bep\.?\s*\d+\b|episode\s*\d+"
    # Рисование под музыку и анимация к ней: дорожка там тоже оригинальная.
    r"|animatic|speed\s*-?\s*(?:draw|paint)|speedpaint", re.IGNORECASE)

JUNK = (("reaction", REACTION), ("tutorial", TUTORIAL),
        ("derivative", DERIVATIVE), ("compilation", COMPILATION),
        ("subbed", SUBBED), ("clipped", CLIPPED),
        ("karaoke", KARAOKE), ("live", LIVE), ("playalong", PLAYALONG),
        ("low_quality", LOW_QUALITY))
# Признаки, которые что-то значат ТОЛЬКО без маркера исполнения: исполнители
# дописывают к настоящему кавору ноты и табы.
SOFT_JUNK = (("tutorial", SHEETS_ONLY),)

# Официальные каналы и автозаливы «— Topic»: у них лежит сам оригинал.
OFFICIAL_CHANNEL = re.compile(
    r"\s-\s*topic$|crunchyroll|muse\s+asia|ani-?one|aniplex|lantis|flyingdog"
    r"|pony\s+canyon|toho\s+animation|\bavex\b|sony\s+music|vevo$",
    re.IGNORECASE)

# ── маркеры ИСПОЛНЕНИЯ: без одного из них кандидата не берём ───────────────
# Это белый список, и так и надо: precision здесь дороже recall, потому что
# ложный кавер доезжает до игрока, а потерянный — нет.
PERFORMED = re.compile(
    r"\bcover(?:ed|d)?\b|\bкавер|歌ってみた|歌って見た|弾いてみた|演奏してみた"
    r"|唱ってみた|歌いました|歌わせて|アレンジ|弾き語り|合唱"
    r"|\bfandub\b|\bdub\s+cover\b"
    r"|\bsings?\b|\bsinging\b|перепел|\bacoustic\b|арранж|\barrangement\b"
    r"|\barranged?\s+by\b|\barr\.\s|\bver\.?(?:sion)?\s+by\b"
    r"|\bperformed\s+by\b|\bplayed\s+(?:by|on)\b"
    r"|\benglish\s+(?:cover|ver(?:sion)?|dub)\b|\beng\s+cover\b"
    r"|\ba\s*cappella\b|bardcore|medieval"
    # Название языка в заголовке музыкального видео почти всегда значит
    # «перепето на этом языке»: «Dance in the Fake (russian ending)»,
    # «Fandub Latino». Разборы и реакции этих слов уже лишились выше.
    r"|\b(?:russian|spanish|italian|german|french|polish|latino|arabic"
    r"|korean|chinese|indonesian|portuguese|turkish)\b"
    r"|espa[nñ]ol|portugu[eê]s|\bpt-?br\b|lời\s+việt", re.IGNORECASE)
# Инструмент в заголовке — тоже исполнение: «Unravel - Tokyo Ghoul OP [Piano]»
# слова cover не содержит, а кавер это самый настоящий.
INSTRUMENT = re.compile(
    r"\bpiano\b|\bguitar\b|fingerstyle|\bviolin\b|\bviola\b|\bcello\b|\bflute\b"
    r"|harmonica|\bukulele\b|\bdrums?\b|\bbass\b|\bsax\b|\bstrings\b"
    r"|orchestra|symphon|\bmetal\b|\brock\s+ver|\bband\b|8\s*-?\s*bit"
    r"|chiptune|famitunes|\bvocaloid\b"
    # Состав вместо инструмента — тоже исполнение: «Arr. John Wasson | Jazz
    # Ensemble», «String Quartet Classical Cover», «オルゴール» (шкатулка).
    r"|\bensemble\b|\bquartet\b|\bbig\s*band\b|\bbrass\b|\bchoir\b"
    r"|\bmusic\s*box\b|オルゴール", re.IGNORECASE)
# Утайты подписываются 【ником】 в начале заголовка — это и есть «я это спел».
NICK_TAG = re.compile(r"^\s*[【\[]([^】\]]{1,24})[】\]]")
# Что внутри 【】 маркером НЕ является: пометка формата, а не ник.
NOT_A_NICK = re.compile(r"^(?:tv|tv\s*size|full|hd|4k|mv|pv|official|free|new"
                        r"|audio|mp3|live|cover)$", re.IGNORECASE)

# ── позиция песни: OP это не ED ────────────────────────────────────────────
# Здесь тип песни и окупается. «Tsuki ga Kirei OP - Ima Koko Guitar Cover» под
# ЭНДИНГОМ «Tsuki ga Kirei» иначе проходил как точное совпадение: имя песни у
# этого тайтла совпадает с именем самого аниме.
OPENING_TOKEN = re.compile(r"\bop\s*\d*\b|\bopening\b|\bオープニング\b", re.IGNORECASE)
ENDING_TOKEN = re.compile(r"\bed\s*\d*\b|\bending\b|\bエンディング\b", re.IGNORECASE)

# Тип кавера — только для разнообразия в паке, не для отбора. Порядок важен:
# выигрывает первый сработавший.
TYPES = (
    ("chiptune", re.compile(r"8\s*-?\s*bit|chiptune|famitunes|\bnes\b", re.IGNORECASE)),
    ("metal", re.compile(r"\bmetal\b|\bdjent\b|hardcore|screamo", re.IGNORECASE)),
    ("orchestra", re.compile(r"orchestra|symphon|\bstrings\b|\bviolin\b|\bviola\b"
                             r"|\bcello\b|quartet", re.IGNORECASE)),
    ("piano", re.compile(r"\bpiano\b|\bkeyboard\b", re.IGNORECASE)),
    ("guitar", re.compile(r"\bguitar\b|fingerstyle|\bukulele\b|\bacoustic\b",
                          re.IGNORECASE)),
    ("band", re.compile(r"\bband\b|\brock\b|\bdrums?\b", re.IGNORECASE)),
    ("other_lang", re.compile(r"\benglish\b|\bfandub\b|на\s+русском|latino"
                              r"|\bspanish\b|\brussian\b", re.IGNORECASE)),
    ("vocal", re.compile(r"\bcover\b|歌ってみた|\bsings?\b|кавер", re.IGNORECASE)),
)

# Как эти виды зовутся по-русски (вкладка, журнал, covers.json). Вида «Живьём»
# больше нет: концертные записи не берутся вовсе (см. LIVE).
TYPE_LABELS = {"vocal": "Вокальный", "piano": "Фортепиано", "guitar": "Гитара",
               "band": "Группа", "metal": "Метал", "orchestra": "Оркестр",
               "chiptune": "8-бит", "other_lang": "На другом языке"}

# На каком языке перепето. Нужно подписи вопроса: игрок должен прочитать
# «Опенинг (кавер на английском)», а не безликое «На другом языке» (просьба
# пользователя). Порядок важен — выигрывает первый сработавший.
LANGUAGES = (
    ("английском", re.compile(r"\benglish\b|\beng\s+(?:cover|ver)|\beng\s*sub"
                              r"|英語", re.IGNORECASE)),
    ("русском", re.compile(r"\brussian\b|на\s+русском|русская\s+вер"
                           r"|\brus\s+cover\b", re.IGNORECASE)),
    ("испанском", re.compile(r"\bspanish\b|espa[nñ]ol|latino|castellano",
                             re.IGNORECASE)),
    ("португальском", re.compile(r"portugu[eê]s|\bpt-?br\b|\bportuguese\b",
                                 re.IGNORECASE)),
    ("немецком", re.compile(r"\bgerman\b|deutsch", re.IGNORECASE)),
    ("французском", re.compile(r"\bfrench\b|fran[cç]ais", re.IGNORECASE)),
    ("итальянском", re.compile(r"\bitalian\b|italiano", re.IGNORECASE)),
    ("польском", re.compile(r"\bpolish\b|\bpolski\b", re.IGNORECASE)),
    ("турецком", re.compile(r"\bturkish\b|t[uü]rk[cç]e", re.IGNORECASE)),
    ("арабском", re.compile(r"\barabic\b", re.IGNORECASE)),
    ("корейском", re.compile(r"\bkorean\b|한국", re.IGNORECASE)),
    ("китайском", re.compile(r"\bchinese\b|中文", re.IGNORECASE)),
    ("индонезийском", re.compile(r"\bindonesian\b|bahasa", re.IGNORECASE)),
    ("вьетнамском", re.compile(r"\bvietnamese\b|lời\s+việt", re.IGNORECASE)),
    ("японском", re.compile(r"\bjapanese\b|日本語(?:ver|版|カバー)?",
                            re.IGNORECASE)),
)

# Те же языки списком и по-русски, в именительном падеже: ключ настройки —
# это то же слово, что стоит в подписи вопроса («кавер на английском»), а
# подпись галочки во вкладке должна читаться отдельно от фразы (просьба
# пользователя — выбирать, какие языки пускать в пак, а какие нет).
LANGUAGE_KEYS = tuple(name for name, _pattern in LANGUAGES)
LANGUAGE_LABELS = {
    "английском": "Английский", "русском": "Русский",
    "испанском": "Испанский", "португальском": "Португальский",
    "немецком": "Немецкий", "французском": "Французский",
    "итальянском": "Итальянский", "польском": "Польский",
    "турецком": "Турецкий", "арабском": "Арабский",
    "корейском": "Корейский", "китайском": "Китайский",
    "индонезийском": "Индонезийский", "вьетнамском": "Вьетнамский",
    "японском": "Японский",
}

# Долгие гласные пишут как угодно: Boukyaku / Bōkyaku / Bokyaku. Сворачиваем
# только на именах от восьми знаков — на коротких это плодит ложные совпадения.
_LONG_VOWEL = re.compile(r"(?:ou|uu|oo|aa|ee|ii)")


def prepare(text) -> str:
    """Заголовок к виду, по которому ищут ВЫРАЖЕНИЯ выше.

    Только NFKC, без снятия регистра и пунктуации: выражениям нужны и пробелы,
    и границы слов. Смысл в том, что модные шрифты из математических символов —
    «Torches / Aimer (𝗰𝗼𝘃𝗲𝗿)» — иначе не содержат слова cover вовсе, и
    настоящий кавер улетал без маркера. NFKC приводит к обычным буквам и их, и
    полноширинные ｃｏｖｅｒ／ＭＶ."""
    return unicodedata.normalize("NFKC", str(text or ""))


def tokens(text) -> list[str]:
    """Название, разбитое по разделителям, без регистра и диакритики.

    Нужно, чтобы короткое латинское имя искалось ЦЕЛЫМ словом. На корпусе это
    стоило восьми настоящих каверов: у «Clannad» есть вставка «Ana», у
    «Fullmetal Alchemist» — «Over» и «Rain», и подстрока находилась внутри слов
    Clannad, cover и Rainych — каверы улетали как медли."""
    prepared = unicodedata.normalize("NFKD", prepare(text).casefold())
    out: list[str] = []
    current: list[str] = []
    for char in prepared:
        # Буквы и цифры ЛЮБОГО письма: кандзи и кана нужны японским названиям,
        # кириллица — русским. Диакритику уже снял NFKD (ō -> o).
        if char.isalnum() and not unicodedata.combining(char):
            current.append(char)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def normalize(text) -> str:
    """Название к виду, в котором его можно искать подстрокой.

    Снимает регистр, пунктуацию, пробелы и диакритику: «Seija-tachi» и
    «Seijatachi» становятся одним словом, а «Nameless - The Forsaken Heart» так
    и не начинает содержать «namelessheart» — на этом отсекается самая частая
    ловушка с похожим названием."""
    return "".join(tokens(text))


def token_run(key: str, title_tokens) -> bool:
    """Совпал ли ключ с ЦЕЛЫМ рядом слов заголовка, а не с серединой слова.

    Рядом, а не одним словом, потому что пробелы в названиях гуляют: «Ima Koko»
    пишут и «Imakoko», «Utsukushiki Zankoku na Sekai» — и «Zankokuna»."""
    folded = fold(key)
    limit = len(key) + 6                      # запас на сжатые долгие гласные
    for start in range(len(title_tokens)):
        joined = ""
        for token in title_tokens[start:]:
            joined += token
            if len(joined) > limit:
                break
            if joined == key or fold(joined) == folded:
                return True
    return False


def fold(name: str) -> str:
    """То же название с сжатыми долгими гласными (только от восьми знаков)."""
    return _LONG_VOWEL.sub(lambda m: m.group(0)[0], name) if len(name) >= 8 else name


def nickname_tag(title: str) -> bool:
    """Начинается ли заголовок с 【ника】 исполнителя (утайтская подпись)."""
    found = NICK_TAG.match(str(title or ""))
    return bool(found) and not NOT_A_NICK.match(found.group(1).strip())


def cover_type(title: str, channel: str = "") -> str:
    text = f"{title} {channel}"
    for name, pattern in TYPES:
        if pattern.search(text):
            return name
    return "vocal"


def cover_language(title: str, channel: str = "") -> str:
    """На каком языке перепето («английском») или «» — язык не назван.

    Ищется в том же тексте, что и вид исполнения: язык пишут и в заголовке
    («English Cover»), и в названии канала («Fandub Latino»)."""
    text = prepare(f"{title} {channel}")
    for name, pattern in LANGUAGES:
        if pattern.search(text):
            return name
    return ""
