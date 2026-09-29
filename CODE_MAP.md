# Карта небольших модулей SI-HYX

Изменяй реализацию в указанной папке; прежний файл сохраняет публичные импорты и общее состояние.
Сначала найди нужный символ, например:

```powershell
rg -n "^def _build_sidebar" si_hyx_parts/edit_tab
rg -n "^def process_media" si_hyx_parts/workers
```

Каждый файл ограничен 600 строками и 40 КиБ; целевой размер — 200–300 строк.
Маленькие исходные файлы остаются на прежних местах. Подробные правила — [CLAUDE.md](CLAUDE.md).

Раскрытие кадров аниме-пака: [frame_reveal.py](frame_reveal.py) — список эффектов и ступени;
отдельные эффекты на numpy — [tone](frame_reveal_tone.py) (темнота, пересвет),
[warp](frame_reveal_warp.py) (волны, полосы, спираль),
[layout](frame_reveal_layout.py) (миниатюра, пазл);
[encode_reveal](si_hyx_parts/animepack/anime_pack_generator_encode_reveal.py) — кодирование;
[frame_effect_controls](si_hyx_parts/animepack_tab/frame_effect_controls.py) — панель выбора.
«DVD-заставка» — не ступени, а покадровая анимация 30 или 60 к/с:
[frame_reveal_dvd](frame_reveal_dvd.py) (движение и сглаженный след),
[frame_reveal_dvd_path](frame_reveal_dvd_path.py) (путь, открывающий кадр целиком),
[frame_reveal_dvd_media](frame_reveal_dvd_media.py) (картинки/видео из папки
пользователя в прямоугольнике), [encode_dvd](si_hyx_parts/animepack/anime_pack_generator_encode_dvd.py)
(кадры в ffmpeg по трубе).

Анонсы в пак не идут ничем — [announced.py](si_hyx_parts/animepack/announced.py),
проверка в `filter_anime` и при поиске первого появления персонажа.
Ctrl+F в консоли — [console_find_bar.py](si_hyx_parts/main/console_find_bar.py).
Ключ категории `pixel` и прежние настройки `pixel_*` сохранены для совместимости.

ИИ-арты: [инструкция и карта модулей](docs/anime-ai-art.md).

Проверки картинок Gemini: [visual_batch](si_hyx_parts/animepack/visual_batch.py)
собирает до четырёх параллельных проверок Pixiv и манги с одинаковой моделью
в один запрос; каждый вердикт сопоставляется со своей картинкой по id.

Арты Pixiv: [pixiv_art_api.py](pixiv_art_api.py) — клиент и отбор;
[pixiv_art_search.py](pixiv_art_search.py) — три источника выдачи;
[pixiv_titles.py](pixiv_titles.py) — названия тайтлов в виде, сравнимом с
метками (по ним отсеиваются сборки сразу по нескольким сериалам);
[pixiv_art_match.py](pixiv_art_match.py) — локальное исключение артов с метками
чужих франшиз при совпадении неоднозначного названия;
[pixiv_art_tags.py](pixiv_art_tags.py) и [pixiv_tag_rules.py](pixiv_tag_rules.py) —
метки-исключения.

Страницы манги: [manga_panel](si_hyx_parts/animepack/manga_panel.py) — выбор и
загрузка; [manga_visual_check](si_hyx_parts/animepack/manga_visual_check.py) —
проверка Gemini «не видно ли названия» (как у Pixiv), галочка и модель —
[manga_gemini_controls](si_hyx_parts/animepack_tab/manga_gemini_controls.py).

Узнаваемость и цена вопроса: «в избранном» — вторая мера рядом со списками.
Число берётся у САМОГО Shikimori, со страницы тайтла
([title_favorites](si_hyx_parts/animepack_api/shikimori_api_character_favorites.py)):
в его API этого поля нет ни в GraphQL, ни в REST, и сортировки по избранному
тоже нет — подробности в комментарии у `ShikimoriApi._RE_FAVOURED`. Адрес
страницы всегда с приставкой «z» перед номером Shikimori. Запрос стоит страницы,
поэтому спрашивается он только у кандидата, дошедшего до `_fetch_media`, и
оседает в memo кэша каталога; после поправки рамка сложности рода вопросов
проверяется заново. Сама поправка работает ТОЛЬКО В ПЛЮС и меряется по
СОСЕДЯМ по индексу — [favorites_norm](si_hyx_parts/animepack/favorites_norm.py):
надбавка начинается, когда избранных вдвое больше, чем в среднем у тайтлов того
же рода с близким индексом (соседи собираются из memo базы генератором и панелью
базы). Пока соседей мало — прежняя планка
[index_favorites_factor](si_hyx_parts/shikimori_api/age_years.py), потолок в
[shikimori_api.py](shikimori_api.py).

Из чего сложилась цена — [price_parts.py](si_hyx_parts/animepack/price_parts.py),
из чего сложились индекс и цена в подсказках таблицы —
[index_tooltip.py](si_hyx_parts/animepack_tab/index_tooltip.py); отдельное окно
состава пака ([table_dialog.py](si_hyx_parts/animepack_tab/table_dialog.py))
устроено как панель базы: поиск, сортировка и подсказки на заголовках и на
строках. Номер пака («№ 3») и состав для поля «Комментарии» —
[pack_summary.py](si_hyx_parts/animepack/pack_summary.py); отменённая генерация
номер возвращает (`_release_pack_number` во вкладке).

Что пак уже спрашивал — [pack_manifest.py](si_hyx_parts/animepack/pack_manifest.py):
список франшиз и корней названий лежит ВНУТРИ .siq. Настройка «не повторять
франшизы из этих паков» читает его, а не строки ответов: у «детали сюжета», у
персонажа и у загадок по названию в ответе стоит не тайтл, и прежним способом
такая франшиза не находилась. У паков, собранных раньше, названия достаются из
подписей медиафайлов.

Дата показа серии берётся из инфобокса и через ПОДЧЁРКИВАНИЕ
(`|japanese_air_date =`): у вики «Обещанного Неверленда» поле зовётся так, и
серия 19 из-за прежнего шаблона оставалась при карточке первого сезона.

Отпечаток песни для «не повторять вопросы из этих паков»
([exact_repeat.py](si_hyx_parts/animepack/exact_repeat.py)) отрезает название по
тире ПЕРЕД кавычками, а не по первому попавшемуся: тире бывает и в самом
названии («Код Гиас: Восставший Лелуш — Пробуждение»), и тогда тег песни
оставался за границей — вопрос шёл без отпечатка вовсе и повторялся.

Какой сезон достаётся вопросу:
[plot_season.py](si_hyx_parts/animepack/plot_season.py) — серия с вики
принадлежит своему сезону (`|season number=`), карточка кандидата подменяется на
него, а сплошной номер серии пересчитывается во внутрисезонный. Первым делом
пробуется ДАТА показа серии из инфобокса
([plot_air_date.py](si_hyx_parts/animepack/plot_air_date.py)): номер сезона у
частей без номера в названии («Алисизация» и её «Война в Подмирье» — у вики один
третий сезон, у Shikimori три тайтла) не работает вовсе. А вот КАКАЯ
часть франшизы достанется паку — чистый жребий, и так и надо (просьба
пользователя: иначе одна и та же часть попадалась бы из пака в пак). «Царство»
приходило шестым сезоном не из-за выбора, а потому что остальных сезонов в
каталоге не было: автодобор во время генерации ходит `order: random` и целиком
каталог не вычерпывает — это делает только кнопка «Обновить базу»
(`fetch_full_catalog`, `order: id`). Мешок базы с фильтрами ШИРЕ нынешних
(полный каталог без исключённых жанров и т. п.) годится генерации целиком —
лишнее отсеивается на месте ([catalog_superset](si_hyx_parts/animepack/catalog_superset.py));
мешок, вычерпанный кнопкой до конца, помечен `complete`, и за ним на сервер
больше не ходят.

Возраст тайтла считается по ОБОИМ краям выпуска
([effective_age](si_hyx_parts/shikimori_api/age_years.py)): выходящий сериал
стареет вдвое медленнее вышедшего. Поля `releasedOn` и `status` появляются в
карточках только после обновления базы — у старых карточек их нет, и свежесть
считается по одному году начала, как раньше.
Панель базы Shikimori (кнопка «Обновить базу»: что в базе лежит и обновление
её по частям) — [db_table_dialog.py](si_hyx_parts/animepack_tab/db_table_dialog.py);
блоки частей с подсказками «как это собиралось» —
[db_part_blocks.py](si_hyx_parts/animepack_tab/db_part_blocks.py), разбор
кэша в строки — [db_rows.py](si_hyx_parts/animepack_tab/db_rows.py), сама
таблица — [db_table_view.py](si_hyx_parts/animepack_tab/db_table_view.py),
подсказка строки при наведении —
[db_row_tip.py](si_hyx_parts/animepack_tab/db_row_tip.py) (пока попап показан,
смена строки под курсором сразу меняет текст; разборы запоминаются), ПКМ
«Обновить данные» / «Обновить всю франшизу» —
[db_refresh.py](si_hyx_parts/animepack_tab/db_refresh.py). Франшизы в дереве
склеиваются по `franchise` и ветке
([franchise_branch.py](si_hyx_parts/animepack/franchise_branch.py)): ключ ветки
— общий корень названия ВСЕХ её частей, а не самый длинный корень карточки,
иначе каждый сезон («… 2nd Season», «… 3rd Season») становился своей франшизой.
Таблица там СВОЯ модель, а не QTableWidget, и поиск с сортировкой она делает
сама: на каталоге книг (сорок тысяч строк) ячейки-объекты стоили пяти секунд на
открытие, буква в поиске — трёх секунд, а QSortFilterProxyModel сравнивал бы
строки через `data()` и сортировал бы десяток секунд. Чтение базы и разбор
строк идут в рабочем потоке (`DbTableDialog._work`) — окно на это время живо;
`flush()` дожидается счёта там, где ответ нужен сразу (тесты).
Роды изданий из настроек — фильтр ТОЛЬКО для книг: у аниме своя колода типов,
и книжный фильтр вычищал вкладку «Аниме» целиком.
Части базы (каталог аниме, каталог манги, «в избранном», франшизы, «хвосты») и
их выборочная чистка — [db_cache_parts.py](si_hyx_parts/animepack/db_cache_parts.py);
сам сбор — [anime_pack_generator_refresh_db.py](si_hyx_parts/animepack/anime_pack_generator_refresh_db.py).
Кого имеет смысл спрашивать про «в избранном» (число живёт только на странице
тайтла, то есть стоит запроса на карточку) —
[favorites_sweep.py](si_hyx_parts/animepack/favorites_sweep.py).

Кандидаты пака идут ТРЕМЯ потоками сразу (`iter_candidates`): песенный,
непесенный и книжный. Песня из AnisongDB нужна только песенным вопросам —
кадры, персонажи, сюжет, арты, сакуга и загадки по названию берутся прямо с
карточки Shikimori. Каталог аниме при этом разбирается ОДИН раз, и карточки
раскладываются по двум очередям —
[anime_card_feed.py](si_hyx_parts/animepack/anime_card_feed.py); `used_anime` и
брони франшиз у потоков общие. Пока это было одним потоком через AnisongDB, из
12 811 карточек кэша до отбора добирались 849, и пак выходил 116 вопросов из 144.

Кандидат, временно не подходящий под просимую среднюю сложность, не
выбрасывается, а ждёт на скамейке (`_bench_candidate`); когда каталог кончился,
а пак не набран, скамейка идёт в дело и середина больше не сторожится
(`_take_level_bench`). Бронь франшизы на время ожидания отпускается и
занимается заново — `_rebook_candidate`.

Почему пак недобрался — [shortage_report.py](si_hyx_parts/animepack/shortage_report.py):
каталоги порознь (аниме/книги), судьба кандидатов со сходящейся арифметикой,
«нужно / получено / не хватило» по родам вопросов. Совет в конце зависит от
настоящей причины: полный диапазон годов расширять не предлагается, а
«Обновить базу» советуется, только когда карточек и правда мало.
Своя модель Gemini у загадок по названию —
[gemini_title_controls.py](si_hyx_parts/animepack_tab/gemini_title_controls.py)
(генератор держит для них отдельный клиент `gemini_titles`).

Рамки узнаваемости по родам вопросов:
[pack_settings_levels.py](si_hyx_parts/animepack/pack_settings_levels.py) —
какой род вопросов какую рамку слушает;
[level_panel.py](si_hyx_parts/animepack_tab/level_panel.py) — все рамки одной
колонкой в группе «Аниме»; сами виджеты заводит
[level_controls.py](si_hyx_parts/animepack_tab/level_controls.py). Полоса с
границами и средней — [difficulty_range.py](si_hyx_parts/animepack_tab/difficulty_range.py),
очередь снимков настроек — [generation_queue.py](si_hyx_parts/animepack_tab/generation_queue.py).
Низкий приоритет ограничивает параллелизм и понижает приоритет рабочих потоков
и ffmpeg — [generation_priority.py](si_hyx_parts/animepack/generation_priority.py).
Старые одноразовые песни и кадры из медиа-кэша убирает
[one_use_cache.py](si_hyx_parts/animepack/one_use_cache.py).

Панель настроек аниме-пака: коробки настроек — это
[SettingsBox](si_hyx_parts/animepack_tab/settings_box.py), а не голый QWidget.
Он нарочно НЕ объявляет heightForWidth: строку с heightForWidth QGridLayout
считает только по нему и минимальную высоту виджета не смотрит вовсе —
раскрытый Chiptune из-за этого рисовался поверх соседних галочек.

Вопрос-СТУДИЯ (кадры подряд, а называют студию) —
[studio_question.py](si_hyx_parts/animepack/studio_question.py): кадры скачиваются
без медиа-кэша, как и у обычного вопроса-кадра, и внутри одного вопроса
не повторяются ни кадры, ни франшизы. Надпись «Назовите студию» стоит ПЕРЕД
КАЖДЫМ кадром с
`waitForFinish="False"`: SIGame показывает разом только те элементы, что идут
подряд до первого ждущего, — одной надписи в начале хватило бы ровно на один
кадр (см. `QuestionEngine.PlayNext` в исходниках SI). Студии лежат в карточке
Shikimori (`studios` в `ANIME_FIELDS`); у карточек из старой базы поля нет
вовсе — тогда они доспрашиваются на тайтл и оседают в memo кэша. В ответе
остаётся только студия и коллаж постеров — без автора и рейтинга случайной
карточки. Панель
настроек — [studio_controls.py](si_hyx_parts/animepack_tab/studio_controls.py).
Правильный ответ кандидата (у каждого рода вопросов он свой) вынесен в
[song_answer.py](si_hyx_parts/animepack/song_answer.py).

Источники вопросов AniZip, Jimaku, MangaDex и Sakugabooru:
[описание и карта модулей](docs/anime-pack-sources.md). Реестр родов вопросов
(имена, подписи, семьи «картинка / ролик / текст») —
[question_kinds.py](si_hyx_parts/animepack/question_kinds.py).
Вопросы по описанию: [description_question.py](si_hyx_parts/animepack/description_question.py)
берёт описание Shikimori и перевод Gemini, затем оставляет текст или озвучивает;
[description_batch.py](si_hyx_parts/animepack/description_batch.py) собирает
переводы ожидающих вопросов в один запрос; [description_audio_encode.py](si_hyx_parts/animepack/description_audio_encode.py)
приводит речь к Opus и общей громкости;
[description_tts.py](si_hyx_parts/animepack/description_tts.py) переключает
провайдеры, [description_gemini_tts.py](si_hyx_parts/animepack/description_gemini_tts.py)
обрабатывает модели Gemini TTS. Порог тестового пака и чтение его из SIQ —
[test_packs.py](si_hyx_parts/animepack/test_packs.py). Настройки —
[description_controls.py](si_hyx_parts/animepack_tab/description_controls.py).

| Публичный модуль | Реализация | Частей | Строк было → стало |
|---|---|---:|---:|
| [animepack.py](animepack.py) | [si_hyx_parts/animepack/](si_hyx_parts/animepack/) | 31 | 4838 → 502 |
| [animepack_api.py](animepack_api.py) | [si_hyx_parts/animepack_api/](si_hyx_parts/animepack_api/) | 13 | 1645 → 159 |
| [animepack_tab.py](animepack_tab.py) | [si_hyx_parts/animepack_tab/](si_hyx_parts/animepack_tab/) | 15 | 3227 → 103 |
| [animepack_upgrade.py](animepack_upgrade.py) | [si_hyx_parts/animepack_upgrade/](si_hyx_parts/animepack_upgrade/) | 23 | 3321 → 503 |
| [animepack_upgrade_tab.py](animepack_upgrade_tab.py) | [si_hyx_parts/animepack_upgrade_tab/](si_hyx_parts/animepack_upgrade_tab/) | 8 | 1455 → 75 |
| [config.py](config.py) | [si_hyx_parts/config/](si_hyx_parts/config/) | 11 | 964 → 274 |
| [coop_tab.py](coop_tab.py) | [si_hyx_parts/coop_tab/](si_hyx_parts/coop_tab/) | 3 | 788 → 81 |
| [dyhit_tracker.py](dyhit_tracker.py) | [si_hyx_parts/dyhit_tracker/](si_hyx_parts/dyhit_tracker/) | 3 | 604 → 144 |
| [edit_tab.py](edit_tab.py) | [si_hyx_parts/edit_tab/](si_hyx_parts/edit_tab/) | 37 | 8436 → 96 |
| [edit_tab_base.py](edit_tab_base.py) | [si_hyx_parts/edit_tab_base/](si_hyx_parts/edit_tab_base/) | 5 | 617 → 182 |
| [edit_tab_dialogs.py](edit_tab_dialogs.py) | [si_hyx_parts/edit_tab_dialogs/](si_hyx_parts/edit_tab_dialogs/) | 7 | 1501 → 45 |
| [edit_tab_overlay.py](edit_tab_overlay.py) | [si_hyx_parts/edit_tab_overlay/](si_hyx_parts/edit_tab_overlay/) | 3 | 665 → 62 |
| [edit_tab_widgets.py](edit_tab_widgets.py) | [si_hyx_parts/edit_tab_widgets/](si_hyx_parts/edit_tab_widgets/) | 18 | 4088 → 126 |
| [edit_tab_workers.py](edit_tab_workers.py) | [si_hyx_parts/edit_tab_workers/](si_hyx_parts/edit_tab_workers/) | 8 | 1874 → 55 |
| [main.py](main.py) | [si_hyx_parts/main/](si_hyx_parts/main/) | 13 | 3106 → 99 |
| [photo_tab.py](photo_tab.py) | [si_hyx_parts/photo_tab/](si_hyx_parts/photo_tab/) | 20 | 4086 → 100 |
| [shikimori_api.py](shikimori_api.py) | [si_hyx_parts/shikimori_api/](si_hyx_parts/shikimori_api/) | 8 | 952 → 206 |
| [shikimori_tab.py](shikimori_tab.py) | [si_hyx_parts/shikimori_tab/](si_hyx_parts/shikimori_tab/) | 13 | 2323 → 226 |
| [siquester/main_window.py](siquester/main_window.py) | [si_hyx_parts/siquester/main_window/](si_hyx_parts/siquester/main_window/) | 5 | 1115 → 32 |
| [siquester/media.py](siquester/media.py) | [si_hyx_parts/siquester/media/](si_hyx_parts/siquester/media/) | 6 | 625 → 91 |
| [siquester/result_page.py](siquester/result_page.py) | [si_hyx_parts/siquester/result_page/](si_hyx_parts/siquester/result_page/) | 9 | 1730 → 34 |
| [siquester/siq_package.py](siquester/siq_package.py) | [si_hyx_parts/siquester/siq_package/](si_hyx_parts/siquester/siq_package/) | 6 | 1197 → 21 |
| [siquester/widgets_editors.py](siquester/widgets_editors.py) | [si_hyx_parts/siquester/widgets_editors/](si_hyx_parts/siquester/widgets_editors/) | 3 | 860 → 44 |
| [siquester/widgets_players.py](siquester/widgets_players.py) | [si_hyx_parts/siquester/widgets_players/](si_hyx_parts/siquester/widgets_players/) | 4 | 659 → 59 |
| [siquester/widgets_question.py](siquester/widgets_question.py) | [si_hyx_parts/siquester/widgets_question/](si_hyx_parts/siquester/widgets_question/) | 7 | 1653 → 39 |
| [tabs.py](tabs.py) | [si_hyx_parts/tabs/](si_hyx_parts/tabs/) | 14 | 2973 → 55 |
| [tests/test_animepack.py](tests/test_animepack.py) | [si_hyx_parts/tests/test_animepack/](si_hyx_parts/tests/test_animepack/) | 6 | 1686 → 171 |
| [tests/test_animepack_chars_cache.py](tests/test_animepack_chars_cache.py) | [si_hyx_parts/tests/test_animepack_chars_cache/](si_hyx_parts/tests/test_animepack_chars_cache/) | 3 | 675 → 85 |
| [tests/test_animepack_upgrade.py](tests/test_animepack_upgrade.py) | [si_hyx_parts/tests/test_animepack_upgrade/](si_hyx_parts/tests/test_animepack_upgrade/) | 20 | 2641 → 452 |
| [tests/test_shikimori_api.py](tests/test_shikimori_api.py) | [si_hyx_parts/tests/test_shikimori_api/](si_hyx_parts/tests/test_shikimori_api/) | 3 | 644 → 44 |
| [tests/test_utils_pure.py](tests/test_utils_pure.py) | [si_hyx_parts/tests/test_utils_pure/](si_hyx_parts/tests/test_utils_pure/) | 4 | 722 → 63 |
| [tests/test_workers_helpers.py](tests/test_workers_helpers.py) | [si_hyx_parts/tests/test_workers_helpers/](si_hyx_parts/tests/test_workers_helpers/) | 4 | 1088 → 56 |
| [utils.py](utils.py) | [si_hyx_parts/utils/](si_hyx_parts/utils/) | 12 | 1835 → 268 |
| [widgets.py](widgets.py) | [si_hyx_parts/widgets/](si_hyx_parts/widgets/) | 14 | 3298 → 163 |
| [workers.py](workers.py) | [si_hyx_parts/workers/](si_hyx_parts/workers/) | 17 | 3446 → 61 |

`-movflags +faststart` у любого MP4/MOV-выхода — [ffmpeg_faststart.py](ffmpeg_faststart.py):
подставляется там, где команда уходит в процесс (`FfmpegWorker`, Smart Cut,
`run_ffmpeg_capture` «Обработки»), а не в каждом построителе команды.

Сакуга сначала СКАЧИВАЕТСЯ под сетевым замком, а кодируется уже локальный
файл без замка (`sakuga_generation._download`): прежнее кодирование прямо с
URL держало замок минутами и при медленном пресете висело по 600 с × 3.

Покадровый слой «Монтажа» разнесён по двум файлам:
[edit_tab_frames.py](edit_tab_frames.py) — сетка кадров и предекодер картинки,
[edit_tab_audio_scrub.py](edit_tab_audio_scrub.py) — звук покадрового шага
(`AudioScrubber`). Прежний импорт `from edit_tab_frames import AudioScrubber`
работает: класс реэкспортируется.

Время «Монтажа» для ЛЮБОГО показа на экране берётся только у
`EditTab._ui_time_s` ([edit_tab__playhead_target_s.py](si_hyx_parts/edit_tab/edit_tab__playhead_target_s.py)):
`player.position()` во время прогрева уезжает на полсекунды назад, а на паузе
живёт по аудио-часам. Фильтр вшивания субтитров общий для обоих путей экспорта —
[edit_tab__subtitles_vf.py](si_hyx_parts/edit_tab/edit_tab__subtitles_vf.py).

## Как устроен перенос

- Корневые модули по-прежнему служат точками входа. Порядок создания объектов и общие кеши сохранены.
- `_api` в частях обращается к публичному модулю, поэтому подмены зависимостей в тестах и изменения настроек видны всей реализации.
- Определения публикуются последовательно. Не импортируй внутренние части как самостоятельный публичный API.
- Методы больших классов подключаются обычными импортами в тело класса; наследование, свойства и сигналы Qt остаются на исходном классе.
- Исходники не склеиваются и не исполняются через `exec`; сборщик видит обычные статические импорты.
- Файлы тестов сохраняют прежние точки сбора pytest, их реализация находится в `si_hyx_parts/tests/`.

Проверки: `python -m pytest` и `python tools/check_hygiene.py`.

Книжная часть пака: [manga_scale.py](si_hyx_parts/animepack/manga_scale.py)
(перевод книжного счёта на общую с аниме шкалу и его потолок — книга без
экранизации легче `MANGA_MIN_LEVEL` не бывает),
[manga_adaptation.py](si_hyx_parts/animepack/manga_adaptation.py)
(есть ли у книги аниме-экранизация — от неё берутся узнаваемость и цена) и
[manga_mix.py](si_hyx_parts/animepack/manga_mix.py) (доли экранизованных книг,
манхвы и маньхуа). Сами манхва и маньхуа добираются в каталог отдельным
запросом — [manga_catalog_topup.py](si_hyx_parts/animepack/manga_catalog_topup.py):
в общем каталоге книг их почти нет. Длинная лента вебтуна режется до книжного разворота —
[manga_crop.py](si_hyx_parts/animepack/manga_crop.py). Отдельные рамки и
СРЕДНИЕ сложности для артов и книг —
[level_controls.py](si_hyx_parts/animepack_tab/level_controls.py) на вкладке и
[level_avg.py](si_hyx_parts/animepack/level_avg.py) в отборе (род вопроса со
своей средней в общую среднюю пака не входит вовсе).
Размер выборки каталога аниме —
[catalog_want.py](si_hyx_parts/animepack/catalog_want.py): цена вопроса в
карточках каталога у каждого рода своя. Поток книг закрывается, когда просить
их больше незачем (`_close_spent_streams`), а франшизу отвергнутого кандидата
возвращает `_release_candidate`.
Цены всех вопросов считает `assign_prices` в
[is_lang_script.py](si_hyx_parts/animepack/is_lang_script.py): база — место
тайтла по индексу популярности, сверху надбавки за род вопроса.

Своя рамка и средняя сложность ПЕРСОНАЖЕЙ стоят под их же галочкой
(`level_controls.build_char`), а проверяются после выбора героя —
`anime_pack_generator__char_reach.py`. Вопрос по сюжету стоит
`PLOT_PRICE_MULT` цены кадра, в ответе ведущий называет номер серии
(`build_content_xml`), а в самом вопросе тайтл назван всегда
(`animepack_plot.name_title`). Вики тайтла, найденная по ОДНОМУ слову названия,
подтверждается поиском: `FandomApi._fits`.

Настройки состава аниме-пака: `si_hyx_parts/animepack_tab/composition_controls.py`
и `percentage_sliders.py` — настройки рода вопросов стоят прямо под его
галочкой. Свои рамки сложности у артов, книг и СЮЖЕТА — `level_controls.py`
на вкладке и `level_bounds` / `level_avg.py` в отборе. Уровень рассуждения
Gemini зависит от модели: «минимальный» умеет только Flash-Lite
(`gemini_api.model_thinking_levels`). Вопрос по сюжету просит у Gemini до трёх вариантов за один запрос
(`animepack/plot_variants.py`); [plot_batch.py](si_hyx_parts/animepack/plot_batch.py)
объединяет до трёх параллельных сюжетных страниц в один запрос с отдельным id
для каждой. Итог расхода с расшифровкой по сюжету —
`log_gemini_spent`. База Shikimori читается и пишется порциями
(`animepack/db_json.py`), чтобы окно не вставало на двухстах мегабайтах JSON.
Пакетное преобразование названий через Gemini:
`si_hyx_parts/animepack/title_questions.py`; локальный расход запросов — `gemini_usage.py`.
Пределы бесплатного тарифа — [gemini_quota.py](gemini_quota.py): общая на оба
клиента одного ключа доска (слоты RPM и исчерпанные модели) и разбор 429.
Исчерпанная модель помнится СУТКИ, обслуженные запросы считаются отдельно от
отклонённых, а запрос без ответа по таймауту не повторяется — Google его уже
засчитал. Итог прогона печатает `log_gemini_spent`.
Диалоги: отрывок ВСЕГДА выбирает Gemini, прочитав серию целиком
(`animepack/dialogue_gemini.py`: номера реплик от модели, текст — из самих
субтитров). Сначала русские субтитры SubDL (`animepack_api/subdl_api.py`,
`animepack/dialogue_subdl.py`), после его суточной квоты — Jimaku;
`animepack_api/jimaku_api.py` строго связывает тайтл по AniList ID,
`animepack/dialogue_questions.py` разбирает субтитры и проверяет построчный
перевод Gemini, `animepack/dialogue_generation.py` записывает номер серии и
источник. Все пары сложности «от/до» показываются одним `DifficultyRange`.
Точные повторы из готовых SIQ: `si_hyx_parts/animepack/exact_repeat.py`;
авторы для устной реплики ответа: `si_hyx_parts/animepack/author_lookup.py`.
Виды загадок по названиям: `si_hyx_parts/animepack/title_kinds.py`
(«зашифрованное название» убрано — загадка решалась механически).
Отбор коротких названий (до 40 символов) и первых частей для загадок:
`si_hyx_parts/animepack/title_selection.py`.

Chiptune: [описание и проверки](docs/chiptune.md). Настройки способов подачи —
`music_effects.py`; изолированный ML-обработчик, кеш и синтез — `chiptune/`;
интеграция аудио/SIQ — `si_hyx_parts/animepack/music_processing.py`;
панель и прослушивание — `si_hyx_parts/animepack_tab/music_effect_controls.py`
и `music_preview.py`.

Настройки музыки (отрезок, коллаж, Chiptune, каверы) собраны одной коробкой
`box_audio_opts` под галочкой «Песни» в группе «Состав пака» —
`si_hyx_parts/animepack_tab/music_panel.py`. Исключения: подсказки о типе песни
галочки больше нет (она есть всегда, `PackSettings.hint` ставит `collect()`), а
«Сжимать аудио» стоит в «Прочем» рядом со «Сжимать картинки».

Панель настроек раскладывается по колонкам под ширину вкладки —
`si_hyx_parts/animepack_tab/settings_columns.py`; таблица состава пака после
генерации открывается отдельным окном кнопкой «Показать таблицу»
(`animepack_tab/table_dialog.py`). Группа «Пак» в этих колонках НЕ
лежит: она стоит в неподвижной правой колонке вместе с полосой запуска
(`_build_settings_panel`, ширина — `_fit_pack_column`), чтобы не уезжать при
прокрутке настроек.

Каверы опенингов и эндингов: [описание и проверки](docs/anime-covers.md).
[cover_search.py](cover_search.py) — запросы к
YouTube через встроенный yt-dlp и дедуп; [cover_meta.py](cover_meta.py) —
решение «это исполнение нужной композиции или нет» со словарём в
[cover_meta_rules.py](cover_meta_rules.py) (там же список языков исполнения —
его показывает
[cover_lang_controls.py](si_hyx_parts/animepack_tab/cover_lang_controls.py));
[cover_audio.py](cover_audio.py) —
хрома, OTI и локальное выравнивание Qmax (только numpy, ffmpeg зовёт
вызывающая сторона через `decode_args`);
[cover_fingerprint.py](cover_fingerprint.py) — созвездие спектральных пиков:
отвечает на ДРУГОЙ вопрос, «не играет ли внутри сам мастер оригинала», который
хроме не по силам (у точного band-кавера выравнивание такое же, как у гитары
поверх записи); [cover_match.py](cover_match.py) —
порог тождества и выбор двадцати секунд ПО ТОМУ ЖЕ пути выравнивания, плюс
«близость к оригиналу» для сложности вопроса. Стенд и разметка:
[tools/cover_probe.py](tools/cover_probe.py) (`--collect` собирает корпус из
сети, `--meta-only` считает точность без сети) и
[tools/cover_cases.py](tools/cover_cases.py) — чтение разметки из
`tools/cover_cases.json` (421 настоящий заголовок по 15 песням, размеченный
руками; сами данные — файлом, чтобы корпус мог расти). Те же три числа
проверяет [tests/test_cover_corpus.py](tests/test_cover_corpus.py).

Звуковой стенд: [tools/cover_audio_probe.py](tools/cover_audio_probe.py)
(`--fetch` качает эталоны AMQ и звук кандидатов, `--score` строит матрицу
«каждый кандидат против каждого эталона», `--report` печатает вердикты
cover_match). На нём и стоят пороги: 139 настоящих пар и 2662 чужие,
recall 0.813 при НУЛЕ ложных, у каждого принятого кавера нашлось не меньше 36
годных 20-секундных окон. Один кандидат стоит 1.3 с ЦПУ (декод 0.5, хрома 0.8,
вердикт 0.02) плюс ~1.2 с загрузки, и ещё 0.27 с уходит на отпечаток записи.

Стенд отпечатка: [tools/cover_inside_probe.py](tools/cover_inside_probe.py) с
разметкой в `tools/cover_inside_cases.json` — 19 пар «эталон — ролик»: честные
каверы дают 0.05…0.66 совпавших пар в секунду, игра под оригинал 3.13…55.44,
порог посередине.

Кладовая и выбор: [cover_cache.py](cover_cache.py) — файл на КОМПОЗИЦИЮ
(annSongId) рядом с настройками: сырые находки поиска, вердикты звука со
списком годных окон и история использования. Хрома эталона и созвездие пиков
живут только в памяти текущей генерации; старые `.npy` удаляются. Гейт и пороги там НЕ заморожены
— заголовки, сырой счёт хромы и сырое число совпавших пар отпечатка хранятся
как есть, а решение пересчитывается при чтении, поэтому правка словаря правил
или порога не стоит повторной загрузки. Способ СЧИТАТЬ признаки обесценивает
вердикты целиком — на это есть `AUDIO_VERSION`. [cover_select.py](cover_select.py) — какой
из подтверждённых каверов и какой его участок идут в пак: уверенность ×
разнообразие типов × остывание, запрет повтора подряд, запрошенное генератором
место песни (`trim_start`) важнее памяти о занятых окнах.
Стенд политики и цены: [tools/cover_select_probe.py](tools/cover_select_probe.py)
— 52 разыгранных пака на настоящих вердиктах стенда звука, без сети. Замеренное:
все 7.2 подтверждённых кавера песни успевают прозвучать (у «лучшего по счёту» —
один), типов в паке 6.0 против 5.3 у равновероятного выбора, повторов подряд
ноль против 93, попадание в запрошенное место песни 0.954. Песня занимает в
кладовой 19 КиБ (JSON с окнами) плюс 18 КиБ хромы эталона.

Генератор: [cover_service.py](cover_service.py) — поиск, проверка и резка одной
песни целиком (процессы запускает переданный killable-раннер, поэтому «Стоп»
убивает и загрузки каверов); подключение к загрузчику звука —
`si_hyx_parts/animepack/cover_processing.py`, ветка по `music_effect` в
`anime_pack_generator_download_audio.py`, доли способов подачи —
`music_effects.py` (`EffectSlots` делит слоты между chiptune и каверами одним
зерном). Что именно прозвучало, пишется в `covers.json` внутри пака. Кандидаты
слушаются волнами по числу недостающих: чтобы набрать три подтверждённых,
на корпусе уходит 4 кандидата (медиана; максимум 6) — это ~5 с ожидания на
песню при шести потоках, а следующим пакам проверка не стоит ни одной загрузки.

Схожесть кавера с оригиналом — отдельная шкала 0…100% из `closeness`
(`cover_match.similarity_percent`: вокальный кавер ≈53%, фортепианный ≈34%).
Это не `songDifficulty` сайта AMQ; прежнее имя `cover_match.amq` оставлено
только для совместимости. Надбавка к цене СКЛАДЫВАЕТСЯ со сложностью песни, а не
удваивает её — `si_hyx_parts/animepack/cover_difficulty.py` объединяет обе доли
как независимые препятствия и остаётся в прежних `SONG_DIFF_BONUS_MAX`. Панель
вкладки — `si_hyx_parts/animepack_tab/cover_controls.py` (доля, рамка
сложности, виды исполнения), прослушивание до сборки — `cover_preview.py`.

Подписи вопроса-кавера — `si_hyx_parts/animepack/cover_labels.py`: вид и язык
исполнения берутся из ЗАГОЛОВКА ролика (`cover_meta_rules.cover_language`) и
идут в подсказку «Опенинг (кавер на английском)», «Эндинг (кавер на
фортепиано)»; канал уходит ведущему в реплику «Взято с канала …»
одновременно с отрезком, а в ответе исполнитель зовётся «Исполнитель
оригинала». Таймера (`duration`) у звуковой дорожки нет вовсе — отрезок
доигрывает сам.

Что НЕ берётся ни при каких настройках (`cover_meta_rules.JUNK`): караоке
(`KARAOKE`), концертные записи (`LIVE`), игра под оригинал — drum/bass cover,
play-along, backing track (`PLAYALONG`), заведомо плохие записи
(`LOW_QUALITY`) и ролики с числом просмотров ниже `cover_meta.MIN_VIEWS`.
Вида «Живьём» в списке исполнений больше нет.

Порядок ступеней здесь не «дешёвое перед дорогим», а разделение вопросов:
**заголовок решает КАТЕГОРИЮ** (исполнение или оригинал/реакция/туториал/
off-vocal — звук такое пропускает насквозь, на замерах 314, 113 и 371 очка при
пороге 60), **звук решает ТОЖДЕСТВО** (та ли это композиция — 0 ложных
срабатываний на ~140 несовпадающих парах). Ни одна ступень не заменяет другую.
