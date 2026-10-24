# Монтаж AMV через montage_tool — памятка агента

Все команды: `python -I montage_tool.py <команда> …` из корня SI-HYX. Ответ —
один JSON в stdout (`"ok": true/false`), долгие команды пишут этапы в stderr
(`--progress`) и отменяются файлом (`--cancel-file путь`). Время — секунды.

## Рецепт

1. **Каталог исходников** — один раз на серию (≈13 мин на 24 мин 1080p, CPU):

       index "D:/anime/Show"            # файл или папка, повторный запуск — только новые файлы
       index "D:/anime/Show" --gemini   # + описания сцен Gemini (квота пользователя)

   Что есть у плана: границы (TransNetV2 + scdet; вспышки — не рез,
   растворение — отдельный отрезок `kind: transition`), 3 ключевых кадра,
   движение (`motion` — доля ширины кадра в секунду; `camera`/`object`),
   акценты (`accents`: вспышка или пик движения с силой), повторы кадров
   (`dup_ratio`, анимация «на двойках»), яркость, цвета, крупность
   (`scale`: closeup/medium/wide/none), персонажи (кластеры CCIP: `characters`;
   имя — `characters --rename ID имя`), теги WD (`tags`, `character_tags`),
   текст на кадре и хардсаб, доля речи, опенинг/эндинг (`oped`).

2. **Карта песни**:

       music "song.mp3" --brief          # темп, размер, такты, фразы, части, энергия, удары, места резов
       music "song.mp3" --gemini --brief # подписи частей — один запрос Gemini по звуку

   Части: `label` (intro/verse/build/chorus/drop/bridge/outro) — эвристика,
   надёжнее буквы групп повторов `group` (A, B…). Места резов `slots`:
   `level` (phrase > downbeat > strong > beat > offbeat), `priority`,
   `recommended` — плотность по энергии части.

3. **Черновик**:

       autofill amv.json --song "song.mp3" --duration 45 [--plan plan.json]

   Окно песни выбирается по частям (или `--t0/--t1`), резы — на
   рекомендованных местах и на сетке кадров, планы — по энергии, плану
   частей и подгону акцента к удару. Маркеры песни пишутся в проект.

4. **Проверка** — после каждой правки:

       check-sync amv.json                  # числа и проблемы со временем
       beat-strip amv.json 0 20 strip.png   # волна, доли, части, резы, клипы — смотреть глазами
       contact-sheet amv.json 0 20 16 s.png # кадры проекта с id клипов
       preview amv.json 10 22 p.mp4         # до 15 с — для Gemini (ask)

5. **Правки** — `edit amv.json --ops ops.json`, затем снова check-sync.
6. **Поиск замены** — `search --tags … --character … --motion-min 0.3 --brief`,
   `shot-sheet out.png --query "sword fight" --no-text` (лист с id планов).
7. **Сборка** — `render amv.json amv.mp4 --progress`.

## Операции edit

```json
[
  {"op": "add", "shot": 1234, "length": 0.92, "in_offset": 0.3},
  {"op": "add", "shot": 77, "until": "downbeat#18"},
  {"op": "trim", "clip": "main#5", "edge": "right", "to": "slot#12"},
  {"op": "split", "clip": "main#3", "at": "snare#40"},
  {"op": "swap", "a": "main#2", "b": "main#3"},
  {"op": "move", "clip": "abc123", "to": "section:chorus#2"},
  {"op": "set", "clip": "main#4", "fields": {"speed": 0.8, "transition": "fade", "transition_s": 0.2}},
  {"op": "delete", "clip": "main#7"},
  {"op": "text", "start": "phrase#1", "end": "phrase#1.end", "text": "TITLE"},
  {"op": "effect", "clip": "main#4", "effect": {"type": "zoom_punch", "on": "kick", "amount": 0.08}}
]
```

Время — число или ссылка на маркер проекта: `вид#N` (N с 1 по времени),
`вид:подпись#N` (`section:chorus#2`, `section:A#1`), `.end` — конец
отрезка, `+0.25`/`-0.1` — сдвиг; итог прилипает к кадру. Клип — id,
`main#N`, `track2#N`, `last`. Ответ — операции, добавленные/удалённые/
сдвинутые клипы и проблемы строгой проверки; ошибка в любой операции —
проект не меняется.

## plan.json для autofill

```json
{
  "files": ["Edgerunners"],
  "min_shot": 0.4,
  "exclude_tags": ["text", "subtitled"],
  "sections": {
    "chorus": {"motion": "high", "tags_any": ["gun", "explosion", "running"]},
    "verse":  {"motion": "low", "scale": ["closeup", "medium"], "characters": ["3"]},
    "default": {}
  },
  "prefer": [120, 121], "avoid": [455]
}
```

## Хороший AMV

- Резы — на сильные доли и начала фраз; в громких частях — чаще (до каждой
  доли), в тихих — реже (такт и больше). `check-sync`: `on_beat` ≥ 0.9,
  `on_downbeat` высокий в куплете, `too_dense/too_sparse` — нет.
- Акцент плана (вспышка, удар, резкое движение) — на удар барабана: так
  смена кадра и движение внутри плана «попадают» в музыку.
- Энергия части ↔ движение плана: тихо — статичные крупные планы, припев —
  экшен, быстрая камера.
- Без хардсаба, титров, опенинга и эндинга (`search` их не отдаёт без
  `--with-oped`), без чёрных кадров и вспышек на самом резе.
- Без повторов кусков и соседних кусков одного плана подряд (скачок).
- Короче 0,3–0,4 с план не читается; длинный план — в тихой части.
- Смотреть результат: `beat-strip` (ритм), `contact-sheet` (картинка),
  `preview` + `ask` (Gemini смотрит ролик и отвечает по JSON-схеме).
