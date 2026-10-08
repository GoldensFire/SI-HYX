# Карта кода SI-HYX

Правила разработки — [CLAUDE.md](CLAUDE.md). Нужный символ ищи через `rg -n`:

```powershell
rg -n "def _ui_time_s" si_hyx_parts/edit_tab
rg -n "class .*Mixin" si_hyx_parts/animepack
```

## Как устроен проект

- **Точка входа** — [main.py](main.py): главное окно `UnifiedWindow`, запуск,
  значок панели задач. Остальные корневые `*.py` — публичные модули
  компонентов: их импортируют приложение, тесты и `tools/`.
- **Небольшие компоненты** живут целиком в своём модуле: `config.py`,
  `shikimori_api.py`, `edit_tab_base.py`, `edit_tab_overlay.py`, `coop_tab.py`,
  `dyhit_tracker.py`, `gemini_api.py`, `pixiv_art_api.py` и другие.
- **Крупные компоненты** — публичный модуль плюс пакет `si_hyx_parts/<модуль>/`
  с реализацией. Публичный модуль импортирует общие зависимости и реэкспортирует
  классы и функции частей; части обращаются к нему как `_api`.
- [si_hyx_parts/kuhi/](si_hyx_parts/kuhi/) — собственная библиотека источников
  серий со своей лицензией; `siquester/` — встроенный редактор паков SIQuesterHYX.
- Проверки: `python tools/check_hygiene.py` (pyflakes, кодировка, голые except,
  правила CodeQL из `tools/check_security.py`; `--alerts` — открытые алерты GitHub)
  и `python tools/check_file_sizes.py` (предупреждение о файлах длиннее 1500 строк).

| Публичный модуль | Что это | Реализация |
|---|---|---|
| [main.py](main.py) | главное окно, вкладки, настройки, обновление | [si_hyx_parts/main/](si_hyx_parts/main/) |
| [tabs.py](tabs.py) | вкладки «Загрузка», «Обработка», Base64, промпт | [si_hyx_parts/tabs/](si_hyx_parts/tabs/) |
| [workers.py](workers.py) | фоновые потоки yt-dlp и ffmpeg-обработки | [si_hyx_parts/workers/](si_hyx_parts/workers/) |
| [widgets.py](widgets.py) | общие виджеты, подсказки, лента последних файлов | [si_hyx_parts/widgets/](si_hyx_parts/widgets/) |
| [utils.py](utils.py) | настройки, медиа-сведения, ffmpeg, Kodik, HTML-маска | [si_hyx_parts/utils/](si_hyx_parts/utils/) |
| [edit_tab.py](edit_tab.py) | вкладка «Монтаж» | [si_hyx_parts/edit_tab/](si_hyx_parts/edit_tab/) |
| [edit_tab_widgets.py](edit_tab_widgets.py), [edit_tab_workers.py](edit_tab_workers.py), [edit_tab_dialogs.py](edit_tab_dialogs.py) | виджеты, потоки и диалоги «Монтажа» | `si_hyx_parts/edit_tab_*/` |
| [photo_tab.py](photo_tab.py) | вкладка «Фото» (LaMa, RMBG, холст) | [si_hyx_parts/photo_tab/](si_hyx_parts/photo_tab/) |
| [animepack.py](animepack.py) | генератор аниме-пака | [si_hyx_parts/animepack/](si_hyx_parts/animepack/) |
| [animepack_api.py](animepack_api.py) | клиенты Shikimori, AnisongDB, манги, вики | [si_hyx_parts/animepack_api/](si_hyx_parts/animepack_api/) |
| [animepack_tab.py](animepack_tab.py) | вкладка генерации пака | [si_hyx_parts/animepack_tab/](si_hyx_parts/animepack_tab/) |
| [animepack_upgrade.py](animepack_upgrade.py), [animepack_upgrade_tab.py](animepack_upgrade_tab.py) | апгрейд готового .siq и его вкладка | `si_hyx_parts/animepack_upgrade*/` |
| [shikimori_tab.py](shikimori_tab.py) | ShikimoriHYX | [si_hyx_parts/shikimori_tab/](si_hyx_parts/shikimori_tab/) |
| [siquester/](siquester/) | редактор паков | `si_hyx_parts/siquester/` — страница пакета и просмотр вопроса |

## Крупные классы

Методы лежат в теле класса или в миксинах рядом с ним.

- **EditTab** — [edit_tab.py](si_hyx_parts/edit_tab/edit_tab.py): создание,
  клавиши, настройки, завершение; [layout](si_hyx_parts/edit_tab/layout.py) —
  интерфейс и подгонка видео; [tracks](si_hyx_parts/edit_tab/tracks.py) —
  аудиодорожки и субтитры; [playback](si_hyx_parts/edit_tab/playback.py) —
  загрузка, прокси, плеер, полный экран; [timeline](si_hyx_parts/edit_tab/timeline.py) —
  волна, отметки, undo, покадровый шаг, предпрокрутка, звук скраба;
  [effects](si_hyx_parts/edit_tab/effects.py) — кадрирование, пикселизация,
  накладки, удаление объекта, трекинг; [export](si_hyx_parts/edit_tab/export.py) —
  кодировщик, обрезка, Smart Cut; [entrance_actions](si_hyx_parts/edit_tab/entrance_actions.py) — меню «⋯».
- **AnimePackGenerator** — [anime_pack_generator.py](si_hyx_parts/animepack/anime_pack_generator.py):
  создание, журнал, `run`/`assemble`, обновление базы;
  [generator_catalog](si_hyx_parts/animepack/generator_catalog.py) — исключения,
  списки, каталог и потоки кандидатов; [generator_selection](si_hyx_parts/animepack/generator_selection.py) —
  вид вопроса, уровни, средняя, квоты, `select_songs`, запись пакета;
  [generator_media](si_hyx_parts/animepack/generator_media.py) — загрузка и кодирование
  медиа. Роды вопросов — миксины в своих модулях: `ai_art_generation`,
  `pixiv_art_generation`, `manga_panel`, `sakuga_generation`, `episode_generation`,
  `dialogue_generation`, `description_question`; отчёт о недоборе — `shortage_report`.
- **AnimePackTab** — [anime_pack_tab.py](si_hyx_parts/animepack_tab/anime_pack_tab.py):
  создание, применение настроек, запуск и итог; [tab_layout](si_hyx_parts/animepack_tab/tab_layout.py),
  [tab_options](si_hyx_parts/animepack_tab/tab_options.py), шаблоны —
  [presets](si_hyx_parts/animepack_tab/presets.py), очередь —
  [generation_queue](si_hyx_parts/animepack_tab/generation_queue.py).
- **UnifiedWindow** — [unified_window.py](si_hyx_parts/main/unified_window.py):
  создание окна, отложенные вкладки, IPC, закрытие;
  [window_tabs](si_hyx_parts/main/window_tabs.py), [window_settings](si_hyx_parts/main/window_settings.py),
  [window_updates](si_hyx_parts/main/window_updates.py), [window_console](si_hyx_parts/main/window_console.py).
- **ProcessWorker** — [process_worker.py](si_hyx_parts/workers/process_worker.py):
  цикл обработки и `process_media`; [process_filters](si_hyx_parts/workers/process_filters.py) —
  аргументы ffmpeg и подбор CRF; [process_images](si_hyx_parts/workers/process_images.py) — картинки и AVIF.
- **MediaTab** — [media_tab.py](si_hyx_parts/tabs/media_tab.py) и
  [media_tab_settings](si_hyx_parts/tabs/media_tab_settings.py).
- **InpaintCanvas** — [inpaint_canvas.py](si_hyx_parts/photo_tab/inpaint_canvas.py),
  [canvas_editing](si_hyx_parts/photo_tab/canvas_editing.py), [canvas_objects](si_hyx_parts/photo_tab/canvas_objects.py).
- **ShikimoriTab** — [shikimori_tab.py](si_hyx_parts/shikimori_tab/shikimori_tab.py) и
  [search_results](si_hyx_parts/shikimori_tab/search_results.py). Просмотры и индекс
  популярности — [pack_index](si_hyx_parts/shikimori_tab/pack_index.py): тот же
  `SongCandidate.index` и та же база Shikimori, что у генератора пака; недостающие
  карточки дозапрашиваются в мешок `SHIKIMORIHYX_BUCKET`.
- **ResultPage**, **QuestionViewer** (SIQuester) — [result_page](si_hyx_parts/siquester/result_page/)
  с [editing](si_hyx_parts/siquester/result_page/editing.py),
  [widgets_question](si_hyx_parts/siquester/widgets_question/) с
  [question_items](si_hyx_parts/siquester/widgets_question/question_items.py).

## Карта функций

Ниже — где искать конкретное поведение. Пути проверяются `rg`; при переносе
кода обновляй ссылки здесь.

Загрузка: `si_hyx_parts/workers/download_result.py` — проверка результата и повторы;
`download_validation.py` — полнота дорожек, `download_network.py` — сетевые ошибки,
`download_process.py` — остановка дочерних процессов. Поведение и zapret:
[downloads](docs/downloads.md).

Караоке OP/ED/OST: [karaoke](karaoke/) — источники, проверка записи, ASS/TTML,
тайминги и рендер; интеграция — [karaoke_processing](si_hyx_parts/animepack/karaoke_processing.py),
интерфейс — [karaoke_controls](si_hyx_parts/animepack_tab/karaoke_controls.py).
Сеть и журнал генератора: [generation-reliability](docs/generation-reliability.md),
`media_transfer.py`, `frame_catalog.py`, `episode_collect.py` в частях аниме-пака;
общая консоль Python/Qt — `diagnostic_logging.py`.
Защита диска — `storage_guard.py`; планирование тяжёлых источников —
`si_hyx_parts/animepack/selection_resources.py`; атомарная запись SIQ —
`package_transaction.py`; качество старых релизов и пропуск релизов ниже
нужного разрешения — `episode_quality_policy.py`.
Описание и ограничения — [anime-karaoke](docs/anime-karaoke.md).
Поисковые запросы по песне/исполнителю/аниме — `karaoke/search.py`;
полный состав исполнителей и защита от подмены сольной/групповой версии —
`karaoke/performers.py`; локальный отказ от Kim — `karaoke/separator_health.py`;
PetitLyrics WSY/LSY — `karaoke/petitlyrics.py`, `karaoke/petit_timing.py`;
Uta-Net Romaji и перенос времени — `karaoke/uta_net.py`, `karaoke/text_alignment.py`,
`karaoke/phonetic_units.py`; связка и статистика — `karaoke/paired_lyrics.py`,
`karaoke/source_audit.py`. Версии/точные метаданные — `karaoke/identity.py`.
Обычная лирика без таймингов — `karaoke/lyrics.py`; сопоставление TV/full и чтений —
`karaoke/lyric_versions.py`; непрерывный подтверждённый фрагмент —
`karaoke/acoustic_excerpt.py`. Тестовый стенд — `tools/karaoke_generate.py`
(`--untimed-lyrics-only --confirmed-excerpts 20`).
Контрольные сохранения и перенос собственных подтверждённых роликов —
`tools/karaoke_checkpoints.py`, `tools/karaoke_checkpoint_reuse.py`;
проверка полной длительности внутри подтверждённых границ — `tools/karaoke_confirmed_verify.py`.
граница показа отрезка отделена от таймингов слогов (`Line.cutoff`).
Стиль и шрифт — `karaoke/style.py`, недельные отказы — `karaoke/rejections.py`,
предварительная загрузка песен — `si_hyx_parts/animepack/song_downloads.py`.
Распознавание и постоянный кэш вокала — `karaoke/recognition.py`;
окна аудио и повторный поиск строфы после пропусков — `karaoke/excerpt_alignment.py`;
замер без старых результатов — `tools/karaoke_generate.py --cold-cache`,
раскладка времени — `tools/karaoke_profile.py`, сравнение потоков CPU —
`tools/karaoke_cpu_benchmark.py`.
общий срок AI-попытки и измерения этапов — `karaoke/budget.py`;
совместимость контейнеров libsndfile/FFmpeg — `karaoke/input_audio.py`;
изолированный обработчик — `karaoke/asr_worker.py`;
языки original lyrics — `karaoke/languages.py`, объединение ASR — `karaoke/asr_passes.py`;
Kim ONNX/STFT — `karaoke/roformer.py`, `karaoke/stft.py`, `karaoke/audio_chunks.py`;
Vulkan — `karaoke/whisper_cpp.py`, устройства — `karaoke/hardware.py`;
ленивые зависимости и закреплённые веса — `karaoke/ai_runtime.py`, `karaoke/ai_assets.py`.
Один запрос на URL, повтор замены файла кэша и пауза хоста — `karaoke/files.py`,
`karaoke/http.py`; издания с другим вступлением/хвостом (`verified_span`) —
`karaoke/matching.py`. Подпись прогресса между вопросами —
`si_hyx_parts/animepack/progress_heartbeat.py`.
AnimeGO.online — `si_hyx_parts/animepack/episode_ru_animego.py`,
списки серий Alloha — `si_hyx_parts/animepack/episode_alloha_catalog.py`.

Видео песен — `si_hyx_parts/animepack/song_video.py` (выбор и фактическая
сводка роликов); галочка внутри «Песен» и перенос прежней доли видео —
`si_hyx_parts/animepack_tab/song_video_controls.py`.
Общие доли обычных песен, видеоряда, караоке и эффектов —
`si_hyx_parts/animepack_tab/song_presentation_controls.py`: одна полоса с границами
долей; слоты — `music_effects.py`.
Общий прогрессбар — `elapsed_progress.py`: прошедшее время в скобках (акцентом),
подпись по центру с тонким контуром и мягкой тенью, имя файла после «·»
приглушено; обновление раз в секунду и остановка таймера при завершении.
Средняя и её достижимость — `animepack/average_selection.py`, итог — `level_avg.py`.
Разброс уровней вокруг средней (не одни пятёрки при цели 5): выбор тянется к
нужному уровню ± случайный шаг (`SPREAD_WEIGHTS`, `aim_level`), а текущая
средняя может отойти от цели на `drift_limit` (≈2/√n, к концу ±0,25).
Приоритет недобранных песен и следующие песни тайтла — `animepack/song_supply.py`.
Предупреждения вместо запрета SIQ — `animepack/pack_completion.py`; автоматическая
упаковка после ошибок и резервные папки записи — `animepack/emergency_package.py`.
Очередь 20 кандидатов — `candidate_source.py`; ранние проверки — `candidate_availability.py`.
План книг фоном — `manga_plan_prefetch.py`; тайтлы, отложенные до освобождения
серии, — `AnimeCardFeed.held`; уступка средней ради полного пака — `average_selection.yields`.
Выбор нужных уровней из всего сохранённого каталога до HTTP —
`catalog_selection.py`; профили из карточек, франшиз и избранного —
`catalog_profiles.py`. Для общей рамки `level_inventory.py` проверяет точную
сумму уровней с учётом оставшегося запаса, чтобы ближайший кандидат не
закрыл путь к целевой средней. Учитываются готовые вопросы и загрузки в работе.
Добор сохранённой средней — `recovery_average.py`; короткий журнал — `run_log.py`.
AnimeThemes: `theme_stream.py` — копия отрезка под общей очередью, затем AV1 с диска;
`theme_http.py` — общая очередь, паузы и целый исходник; `theme_video.py` —
резервное локальное кодирование и проверка дорожек. Замеры:
[animethemes-downloads](docs/animethemes-downloads.md).

Полный ручной сбор манги из Shikimori, ReManga и MangaLib с резервной копией,
журналом и проверкой сохранённых данных — [manga_db_refresh](tools/manga_db_refresh.py).

Появление картинки: [image_entrance.py](image_entrance.py) — 25 эффектов в монтаже,
20 в генерации, русские подписи и составы;
[renderer](image_entrance_renderer.py), [motion](image_entrance_motion.py),
[reveal](image_entrance_reveal.py) — покадровые преобразования;
[entrance_controls](si_hyx_parts/animepack_tab/entrance_controls.py) — отдельная вкладка,
[preview](si_hyx_parts/animepack_tab/entrance_preview.py) — живой пример;
[processing](si_hyx_parts/animepack/entrance_processing.py),
[encoding](si_hyx_parts/animepack/entrance_encoding.py),
[content](si_hyx_parts/animepack/entrance_content.py) — применение к выбранным составам,
кодирование изображений/начала ролика и только готовые видео с таймером 5 секунд в SIQ.
Общее кодирование — [image_entrance_encoding](image_entrance_encoding.py).
В монтаже меню «⋯» содержит «Появление» и «Удалить исходный файл»:
[actions](si_hyx_parts/edit_tab/entrance_actions.py),
[dialog](si_hyx_parts/edit_tab/entrance_dialog.py),
[worker](si_hyx_parts/edit_tab/entrance_worker.py).

Раскрытие кадров аниме-пака: [frame_reveal.py](frame_reveal.py) — список эффектов и ступени;
отдельные эффекты на numpy — [tone](frame_reveal_tone.py) (темнота, пересвет),
[warp](frame_reveal_warp.py) (волны, полосы, спираль),
[layout](frame_reveal_layout.py) (миниатюра, пазл);
[encode_reveal](si_hyx_parts/animepack/generator_media.py) — кодирование;
[frame_effect_controls](si_hyx_parts/animepack_tab/frame_effect_controls.py) — панель выбора.
«DVD-заставка» — не ступени, а покадровая анимация 30 или 60 к/с:
[frame_reveal_dvd](frame_reveal_dvd.py) (движение и сглаженный след),
[frame_reveal_dvd_path](frame_reveal_dvd_path.py) (путь, открывающий кадр целиком),
[frame_reveal_dvd_media](frame_reveal_dvd_media.py) (картинки/видео из папки
пользователя в прямоугольнике), [encode_dvd](si_hyx_parts/animepack/generator_media.py)
(кадры в ffmpeg по трубе).

Анонсы в пак не идут ничем — [announced.py](si_hyx_parts/animepack/announced.py),
проверка в `filter_anime` и при поиске первого появления персонажа.
Ctrl+F в консоли — [console_find_bar.py](si_hyx_parts/main/console_find_bar.py).
Восстановление окна после сворачивания и смены мониторов —
[window_visibility](si_hyx_parts/main/window_visibility.py): запоминает только
видимую геометрию и не принимает служебную позицию свёрнутого окна за обычную.
Фоновое сканирование ленты последних файлов —
[recent_files_scan](si_hyx_parts/widgets/recent_files_scan.py).
Запись базы при генерации —
[generation_checkpoint](si_hyx_parts/animepack/generation_checkpoint.py):
API-пачки накапливаются в памяти, сохраняются после остановки рабочих потоков,
включая отмену и ошибки; ручное обновление сохраняет прежние контрольные точки.
Ключ категории `pixel` и прежние настройки `pixel_*` сохранены для совместимости.

ИИ-арты: [инструкция и карта модулей](docs/anime-ai-art.md).

Отрывки серий: [источники, настройки и карта native Kuhi](docs/anime-episode-clips.md).
Активные провайдеры — `kuhi/provider_policy.py`; режимы сабов —
`animepack/episode_caption_policy.py`; проверка готового видео — `episode_scene_check.py`;
общие метаданные релизов — `episode_release_cache.py`.
RU-sub каталоги AnimeGO/YummyAnime/AnimeLIB — `animepack/episode_ru_*.py`;
проверка и ограничение HLS/DASH — `animepack/episode_stream_quality.py`,
временная передача manifest FFmpeg — `animepack/episode_manifest.py`.
Живая сессия Alloha и локальный мост — `episode_ru_alloha.py`, `episode_alloha_proxy.py`.
Потоковая медиазагрузка — `episode_alloha_transport.py`, лимит браузеров —
`episode_browser_budget.py`; паузы сетевых провайдеров — `si_hyx_parts/kuhi/provider_health.py`.
Загрузки без унаследованных повторов — `network_attempt.py`; ограничение
страниц манги — `si_hyx_parts/animepack_api/manga_image_download.py`.
Синхронные RU-дорожки и один проход AV1 — `episode_captions.py`,
`episode_caption_text.py`; готовые провайдеры без ожидания всех —
`episode_fallback.py`, `si_hyx_parts/kuhi/batches.py`.
Полный прогон сохранённых настроек — `tools/episode_probe.py --current-settings`;
проверка видео и видимых сабов SIQ — `tools/episode_pack_audit.py`.
Память пригодности источников между паками (годный — первым, негодный и
молчавший — мимо, тайтл без ≥1080p — пропуск на трое суток) —
`episode_suitability.py`; ленивая проверка потоков — `_verified` в `episode_generation.py`.

Проверки картинок Gemini: [visual_batch](si_hyx_parts/animepack/visual_batch.py)
собирает до четырёх параллельных проверок кадров, Pixiv и манги с одинаковой моделью
в один запрос; каждый вердикт сопоставляется со своей картинкой по id.
Выбор моделей — `animepack_tab/gemini_groups.py`: «Изображения»,
«Сюжет/Диалоги», «Названия». Для визуальных проверок используется общий
клиент; итог показывает назначение запросов и число изображений в пачках.
Кадры и кадры с эффектами: [frame_visual_check](si_hyx_parts/animepack/frame_visual_check.py)
проверяет исходное изображение на название и наличие персонажей;
[frame_gemini_controls](si_hyx_parts/animepack_tab/frame_gemini_controls.py) — две галочки.
Студии используют ту же проверку обязательно и принимают только кадры с персонажами.
`pixiv_visual_check.py` дополнительно отклоняет крайне плохую рисовку; аккуратная
стилизация допустима. Вердикты хранятся в `pixiv_visual_v4`: модель отдельно
называет распознанное произведение и переписывает видимый текст; код сверяет
его с вариантами названия, даже если `has_title_text=false`. Старые разрешения
из v3 не используются. Теги Fate отсекаются локально, если ожидается другая
франшиза (например, самостоятельное аниме Gilgamesh, 2003).
Пачка копится, пока слот RPM модели занят (`QuotaBoard.wait_time`, до 12 с).
Запасная полоса [visual_spare](si_hyx_parts/animepack/visual_spare.py): проверки
кадров и видимого названия на странице манги при занятой или перегруженной
основной модели уходят в Gemma 4 31B со своей квотой (по одной, до трёх сразу;
отказ возвращает проверку основной модели). Выбор сцены манги Gemma не берёт.
Проверку сцен отрывков Gemma не берёт: звук она не принимает, а без звука
выдумывает реплики.
Визуальные клиенты и отрывки меняют модель только в пределах Gemini
(`fallback_gemma=False`): квота 3.1 Flash-Lite переводит на 3.5 Flash-Lite,
а 503 или квота не переводят 31B на 26B. Gemma с изображениями сначала использует
GenerateContent; резервный endpoint сохраняет ту же модель и инструкции.
Подробный журнал сохраняет исходный вердикт, теги, фактическую модель и хэши
изображения и инструкции.
Локальный OCR: [local_visual_ocr](si_hyx_parts/animepack/local_visual_ocr.py)
один раз находит текст и распознаёт crops PP-OCRv6 Small и кириллической
PP-OCRv5 Mobile; [local_title_match](si_hyx_parts/animepack/local_title_match.py)
сравнивает надписи с названиями. Первое использование загружает модели в
пользовательский кэш SI-HYX; далее OCR работает без сети. Вердикт OCR
кэшируется по хэшу изображения; сомнения уходят в существующий Gemini batch.

Арты Pixiv: [pixiv_art_api.py](pixiv_art_api.py) — клиент и отбор;
[pixiv_auth.py](pixiv_auth.py) — вход с повторами, сбой сети отдельно от отказа ключа;
[pixiv_art_api.py](pixiv_art_api.py) — три источника выдачи;
[pixiv_titles.py](pixiv_titles.py) — названия тайтлов в виде, сравнимом с
метками (по ним отсеиваются сборки сразу по нескольким сериалам);
[pixiv_art_match.py](pixiv_art_match.py) — локальное исключение артов с метками
чужих франшиз при совпадении неоднозначного названия;
[pixiv_art_tags.py](pixiv_art_tags.py) и [pixiv_tag_rules.py](pixiv_tag_rules.py) —
метки-исключения.

RU-популярность книг, ReManga и MangaLib: [формула, зеркала API и проверки](docs/manga-ru.md).
Расчёт — [ru_popularity_math](si_hyx_parts/animepack/ru_popularity_math.py),
memo/история — [ru_popularity_store](si_hyx_parts/animepack/ru_popularity_store.py),
обновление snapshots — [ru_popularity_refresh](si_hyx_parts/animepack/ru_popularity_refresh.py).
Полный внешний каталог и возобновляемые детали —
[ru_catalog_snapshot](si_hyx_parts/animepack/ru_catalog_snapshot.py);
меню отдельных источников в кнопке манги —
[manga_refresh_controls](si_hyx_parts/animepack_tab/manga_refresh_controls.py).
Параллельные детали — [ru_catalog_details](si_hyx_parts/animepack/ru_catalog_details.py);
одновременное обновление источников со сбором карточек Shikimori —
[db_source_refresh](si_hyx_parts/animepack/db_source_refresh.py);
темп, минутная квота и Retry-After —
[population_rate_limit](si_hyx_parts/animepack_api/population_rate_limit.py).

Страницы манги: [manga_panel](si_hyx_parts/animepack/manga_panel.py) — выбор и
загрузка; [manga_page_sources](si_hyx_parts/animepack_api/manga_page_sources.py) —
перебор выбранных сайтов; [manga_json_readers](si_hyx_parts/animepack_api/manga_json_readers.py) —
неофициальные API MangaFire и Comix.to;
[weebcentral_api](si_hyx_parts/animepack_api/weebcentral_api.py) — HTML API WeebCentral;
[mangalib_reader](si_hyx_parts/animepack_api/mangalib_reader.py) — русские страницы MangaLib;
[remanga_reader](si_hyx_parts/animepack_api/remanga_reader.py) — русские главы ReManga;
[manga_request_signing](si_hyx_parts/animepack_api/manga_request_signing.py) — подписи запросов;
[comix_image](si_hyx_parts/animepack_api/comix_image.py) — восстановление страниц Comix.to.
Приоритет точных локальных совпадений в каталогах выбранных русских источников —
[manga_source_candidates](si_hyx_parts/animepack/manga_source_candidates.py).
Фоновая запись деталей и ожидание окончательного сохранения —
[catalog_checkpoint](si_hyx_parts/animepack/catalog_checkpoint.py).
Галочки источников — [manga_source_controls](si_hyx_parts/animepack_tab/manga_source_controls.py).
[manga_visual_check](si_hyx_parts/animepack/manga_visual_check.py) —
проверка названия через Gemini или локальный OCR; выбор режима и модель —
[manga_gemini_controls](si_hyx_parts/animepack_tab/manga_gemini_controls.py).
Выбор сцены с персонажами — [manga_character_crop](si_hyx_parts/animepack/manga_character_crop.py):
манхва/маньхуа любой высоты и длинные ленты манги передаются Gemini
перекрывающимися фрагментами. [manga_page_context](si_hyx_parts/animepack/manga_page_context.py)
соединяет соседние куски главы, сохраняя параметры скачивания источника;
ранее использованные соседи всё равно доступны как контекст для целых реплик.
[manga_page_batch](si_hyx_parts/animepack/manga_page_batch.py) заранее скачивает
до четырёх страниц манхвы/маньхуа без повторной загрузки соседей;
[manga_page_reuse](si_hyx_parts/animepack/manga_page_reuse.py) хранит их (и
страницу обычной манги) до повтора тайтла после паузы Gemini;
[manga_scene_batch](si_hyx_parts/animepack/manga_scene_batch.py) выбирает
до трёх вариантов одним запросом и проверяет все вырезки второй общей пачкой.
Неверные координаты отсеиваются локально, без одиночных повторных запросов.
[manga_scene_bounds](si_hyx_parts/animepack/manga_scene_bounds.py) расширяет
выбор до пустых промежутков исходной ленты и сохраняет всю ширину панели;
[manga_margins](si_hyx_parts/animepack/manga_margins.py) удаляет только пустые
поля, сохраняя реплики и облачка за рамкой рисунка;
[manga_scene_review](si_hyx_parts/animepack/manga_scene_review.py) независимо проверяет
готовые пиксели и исходный контекст на цельность всех заметных лиц и реплик,
пустоту, обрубки панелей и название.
Книжные страницы японской манги сохраняются целиком; порог длинной ленты — в
[manga_crop](si_hyx_parts/animepack/manga_crop.py). Завершение каталога книг
сохраняет квоту, пока остаются отложенные ради средней сложности кандидаты.
Живой прогон с сохранёнными настройками и кадрами для просмотра —
[manga_pack_probe.py](tools/manga_pack_probe.py); повторная проверка всех
вырезок, замена плохих сцен и пересборка их появления —
[manga_pack_review.py](tools/manga_pack_review.py); проверка целостности пака,
ссылок на медиа и просмотр готового кадра всех видео-вопросов —
[manga_pack_verify.py](tools/manga_pack_verify.py).
Одна полоса долей манги/манхвы/маньхуа —
[manga_edition_controls](si_hyx_parts/animepack_tab/manga_edition_controls.py);
перенос старых настроек без ранобэ и романов, а также свои рамка и средняя
сложности у каждого издания (книжная средняя — их смесь по долям) —
[manga_editions](si_hyx_parts/animepack/manga_editions.py).

Строгие квоты и итоговая средняя —
[manga_targets](si_hyx_parts/animepack/manga_targets.py); предварительный баланс
по сохранённым метаданным —
[manga_candidate_plan](si_hyx_parts/animepack/manga_candidate_plan.py).
Курсоры читателей и общие сетевые ограничения —
[manga_reader_pool](si_hyx_parts/animepack_api/manga_reader_pool.py);
резервирование адреса после параллельного поиска —
[manga_parallel_page](si_hyx_parts/animepack/manga_parallel_page.py).
Поиск цельных полос рисунка —
[manga_scene_prefilter](si_hyx_parts/animepack/manga_scene_prefilter.py);
пачки вложенных ответов с отдельными id —
[visual_nested_batch](si_hyx_parts/animepack/visual_nested_batch.py).
Отдельное хранилище memo и обратимая миграция —
[db_memo_sqlite](si_hyx_parts/animepack/db_memo_sqlite.py),
[db_memo_migration](si_hyx_parts/animepack/db_memo_migration.py).
Сравнение 2/4/8 поисковых потоков —
[manga_source_benchmark](tools/manga_source_benchmark.py), итоговая проверка
состава, ответов и повторов — [manga_pack_audit](tools/manga_pack_audit.py).

Узнаваемость и цена вопроса: «в избранном» — вторая мера рядом со списками.
Число берётся у САМОГО Shikimori, со страницы тайтла
([title_favorites](si_hyx_parts/animepack_api/shikimori_api.py)):
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
[index_favorites_factor](shikimori_api.py), потолок в
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

Повторы персонажей — [character_repeat.py](si_hyx_parts/animepack/character_repeat.py):
ID и имена героя сохраняются в манифесте; старые паки читаются по ответам.
Название сезона и перекодирование портрета не меняют личность персонажа.
Первое появление выбирается по дате среди выпущенных произведений, независимо
от роли и TV-формата; рекламные PV/CM и музыкальные клипы пропускаются.

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
больше не ходят. Неполный каталог пишет об этом в журнал и догружает
недостающие части известных франшиз
([franchise_part_topup](si_hyx_parts/animepack/franchise_part_topup.py)).
Порядок каталога — «сначала франшиза, затем её часть», с памятью тайтлов
прежних паков ([title_rotation](si_hyx_parts/animepack/title_rotation.py));
короткие ответвления (фильм, спешл, OVA) наследуют узнаваемость серии лишь
наполовину по лесенке уровней
([franchise_part_weight](si_hyx_parts/animepack/franchise_part_weight.py)).

Возраст тайтла считается по ОБОИМ краям выпуска
([effective_age](shikimori_api.py)): выходящий сериал
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
их выборочная чистка — [db_cache.py](si_hyx_parts/animepack/db_cache.py);
сам сбор — [anime_pack_generator.py](si_hyx_parts/animepack/anime_pack_generator.py).
Максимальные порции обновления: [пределы и живые проверки](docs/db-refresh-requests.md);
Независимое обновление и фильтры отображения: [database-refresh](docs/database-refresh.md).
Полнота и восстановление — `animepack/db_refresh_report.py`,
`db_favorites_refresh.py`, `db_franchise_refresh.py`, `db_backup.py`;
фильтры таблиц — `animepack_tab/db_view_filters.py`, `db_filters.py`.
GraphQL-пачки — [shikimori_catalog](si_hyx_parts/animepack_api/shikimori_catalog.py),
общий обход — [catalog_pages](si_hyx_parts/animepack/catalog_pages.py).
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
Непесенный поток читает ОБЕ очереди в порядке каталога (тайтл с песней уходит
под кадр, пока песен впереди с запасом хватает). Сырые ответы AnisongDB
хранятся три дня: [anisong_cache](si_hyx_parts/animepack/anisong_cache.py).
Упаковка, упавшая после отбора, сохраняет готовые вопросы и медиа
([assembly_recovery](si_hyx_parts/animepack/assembly_recovery.py)); кнопка
«Собрать сохранённое» — [saved_attempt](si_hyx_parts/animepack_tab/saved_attempt.py).

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

Публичный клиент [gemini_api.py](gemini_api.py) подключает получение JSON и
переключение моделей из [gemini_client_generation.py](gemini_client_generation.py).
Восстановление после временной перегрузки —
[gemini_client_recovery.py](gemini_client_recovery.py): дневные квоты сохраняются.
При серверном отказе GenerateContent тот же запрос пробуется через Interactions.

Рамки узнаваемости по родам вопросов:
[pack_settings.py](si_hyx_parts/animepack/pack_settings.py) —
какой род вопросов какую рамку слушает;
[level_panel.py](si_hyx_parts/animepack_tab/level_panel.py) — все рамки одной
колонкой в группе «Аниме»; сами виджеты заводит
[level_controls.py](si_hyx_parts/animepack_tab/level_controls.py). Полоса с
границами и средней — [difficulty_range.py](si_hyx_parts/animepack_tab/difficulty_range.py),
очередь снимков настроек — [generation_queue.py](si_hyx_parts/animepack_tab/generation_queue.py).
Приоритет меняется во время генерации: лимиты рабочих задач и кодировщиков,
приоритет уже запущенных потоков и ffmpeg (включая AVIF) —
[generation_runtime.py](si_hyx_parts/animepack/generation_runtime.py), Windows API —
[generation_priority.py](si_hyx_parts/animepack/generation_priority.py).
Общие подсказки скрываются на время выбора в выпадающих списках —
[hover_tips.py](si_hyx_parts/widgets/hover_tips.py). Каждая новая
подсказка получает новое нативное окно: снова показанное окно Windows сначала
выводит свой прошлый кадр, то есть чужую подсказку —
[info_tip_frame.py](si_hyx_parts/widgets/info_tip_frame.py).
Превью AniList: короткий запрос и минутная пауза после сбоя; повторы запросов
списка пользователя учитывают лимит API — [ani_list_api.py](si_hyx_parts/animepack_api/ani_list_api.py).
Один кандидат запрашивается в фоне, пока принимаются готовые вопросы —
[candidate_source.py](si_hyx_parts/animepack/candidate_source.py),
[selection_results.py](si_hyx_parts/animepack/selection_results.py).
Узкие рамки получают подходящие тайтлы первыми —
[candidate_options.py](si_hyx_parts/animepack/candidate_options.py).
Неудачная форма вопроса и временно заполненные квоты сохраняют тайтл для
других форм — [candidate_reserve.py](si_hyx_parts/animepack/candidate_reserve.py);
при возврате из книжной скамейки кандидат удаляется из этого запаса;
перераспределение мест по оставшимся франшизам —
[quota_balance.py](si_hyx_parts/animepack/quota_balance.py).
Брони только реально показанных работ студии —
[studio_reservations.py](si_hyx_parts/animepack/studio_reservations.py).
После набора песенной доли MAL-каталог обходится без новых запросов песен;
известные неподходящие карточки отсеиваются до AnisongDB —
[anime_card_feed.py](si_hyx_parts/animepack/anime_card_feed.py).
Старые одноразовые песни и кадры из медиа-кэша убирает
[one_use_cache.py](si_hyx_parts/animepack/one_use_cache.py).
Ранний отсев точных повторов и бронь их ключей на время загрузки —
[early_repeat.py](si_hyx_parts/animepack/early_repeat.py); хеш готового медиа
остаётся финальной страховкой в `exact_repeat.py`. Фактический параллелизм,
раздельные замеры загрузок, кодирования и ожиданий —
[generation_diagnostics.py](si_hyx_parts/animepack/generation_diagnostics.py).
У кадров с эффектами свой `frame_preset` (включая DVD); старые настройки
переносят в него прежний `video_preset`, пресет сакуги остаётся независимым.

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
[song_candidate.py](si_hyx_parts/animepack/song_candidate.py).

Источники вопросов AniZip, Jimaku, MangaDex, MangaFire, Comix.to, WeebCentral и Sakugabooru:
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
`EditTab._ui_time_s` ([timeline.py](si_hyx_parts/edit_tab/timeline.py)):
`player.position()` во время прогрева уезжает на полсекунды назад, а на паузе
живёт по аудио-часам. Фильтр вшивания субтитров общий для обоих путей экспорта —
[tracks.py](si_hyx_parts/edit_tab/tracks.py).

Книжная часть пака: [manga_scale.py](si_hyx_parts/animepack/manga_scale.py)
(перевод книжного счёта на общую с аниме шкалу и его потолок — книга без
экранизации легче `MANGA_MIN_LEVEL` не бывает),
[manga_adaptation.py](si_hyx_parts/animepack/manga_adaptation.py)
(есть ли у книги аниме-экранизация — от неё берутся узнаваемость и цена) и
[manga_mix.py](si_hyx_parts/animepack/manga_mix.py) (доли экранизованных книг,
манхвы и маньхуа). «С аниме: Любое» отключает только долю экранизаций;
ввод слова и процентов — [manga_adaptation_control.py](si_hyx_parts/animepack_tab/manga_adaptation_control.py).
При первом заполнении манхва и маньхуа добираются отдельным
запросом — [manga_catalog_topup.py](si_hyx_parts/animepack/manga_catalog_topup.py):
в общем каталоге книг их почти нет. Сохранённый каталог книг генерация
использует без фонового добора; обновление — кнопкой «Обновить базу».
При пустом каталоге запас считается от квоты вопросов по манге —
[generator_catalog.py](si_hyx_parts/animepack/generator_catalog.py).
Длинная лента вебтуна режется до книжного разворота —
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
[pricing.py](si_hyx_parts/animepack/pricing.py): база — место
тайтла по индексу популярности, сверху надбавки за род вопроса.

Своя рамка и средняя сложность ПЕРСОНАЖЕЙ стоят под их же галочкой
(`level_controls.build_char`), а проверяются после выбора героя —
`generator_selection.py`. Вопрос по сюжету стоит
`PLOT_PRICE_MULT` цены кадра, в ответе ведущий называет номер серии
(`build_content_xml`), а в самом вопросе тайтл назван всегда
(`animepack_plot.name_title`). Вики тайтла, найденная по ОДНОМУ слову названия,
подтверждается поиском: `FandomApi._fits`.

Настройки состава аниме-пака: `si_hyx_parts/animepack_tab/composition_controls.py`
и `percentage_sliders.py` — настройки рода вопросов стоят прямо под его
галочкой. Свои рамки сложности у артов, книг и СЮЖЕТА — `level_controls.py`
на вкладке и `level_bounds` / `level_avg.py` в отборе. Уровень рассуждения
Gemini зависит от модели: «минимальный» умеет только Flash-Lite, а Gemma 4
знает лишь «минимальный» и «высокий» (`gemini_api.model_thinking_levels`).
Gemma 4 (`GEMMA_MODELS`) стоят в начале `MODELS` как самые слабые: к ним
`fallback_models` спускается раньше, чем поднимается к Flash. Вопрос по сюжету просит у Gemini до трёх вариантов за один запрос
(`animepack/plot_variants.py`); [plot_batch.py](si_hyx_parts/animepack/plot_batch.py)
объединяет до трёх параллельных сюжетных страниц в один запрос с отдельным id
для каждой. Итог расхода с расшифровкой по сюжету —
`log_gemini_spent`. База Shikimori читается и пишется порциями
(`animepack/db_json.py`), чтобы окно не вставало на двухстах мегабайтах JSON.
Пакетное преобразование названий через Gemini:
`si_hyx_parts/animepack/title_questions.py`; локальный расход запросов — `gemini_usage.py`.
Пределы бесплатного тарифа — [gemini_quota.py](gemini_quota.py): общая на оба
клиента одного ключа доска (слоты RPM и исчерпанные модели) и разбор 429.
Исчерпанная квота помнится СУТКИ. После двух последовательных серверных отказов
модель пропускается до конца прогона, сначала пробуется Flash-Lite. Транспорт
и повторы — [gemini_transport.py](gemini_transport.py). Ошибки 400/5xx и таймауты
входят в локальную оценку расхода; HTTP-коды и успешные ответы считаются отдельно.
Таймаут чтения не повторяется. Итог прогона печатает `log_gemini_spent`.
Названия аниме исключаются из развёрнутых сюжетных ответов в обоих режимах:
[plot_explanation.py](si_hyx_parts/animepack/plot_explanation.py) очищает написания
и русские падежи локально; короткие ответы для зачёта остаются отдельно.
Диалоги: отрывок ВСЕГДА выбирает Gemini, прочитав серию целиком
(`animepack/dialogue_gemini.py`: номера реплик от модели, текст — из самих
субтитров). Сначала русские субтитры SubDL (`animepack_api/subdl_api.py`,
`animepack/dialogue_subdl.py`), после его суточной квоты — Jimaku;
`animepack_api/jimaku_api.py` строго связывает тайтл по AniList ID,
`animepack/dialogue_questions.py` разбирает субтитры и проверяет построчный
перевод Gemini, `animepack/dialogue_generation.py` записывает номер серии и
источник. Все пары сложности «от/до» показываются одним `DifficultyRange`.
Точные повторы из готовых SIQ: `si_hyx_parts/animepack/exact_repeat.py`,
кэш отпечатков неизменившихся архивов — `exact_key_cache.py`; экземпляры
базы Shikimori с одним файлом делят разобранное содержимое — `db_cache_shared.py`;
авторы для устной реплики ответа: `si_hyx_parts/animepack/author_lookup.py`.
Виды загадок по названиям: `si_hyx_parts/animepack/title_kinds.py`
(«зашифрованное название» убрано — загадка решалась механически).
Анаграммы и эти четыре вида объединены в «По названию»:
`animepack_tab/title_composition.py` хранит галочки и внутренние доли;
`animepack/title_mix.py` распределяет квоту категории между вариантами.
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
`si_hyx_parts/animepack_tab/settings_columns.py`: «Списки» всегда сверху
второй колонки, даже при полностью выключенном составе. Фильтры окна базы
независимы от генерации — `animepack_tab/db_filters.py`. Приоритет задаёт
`animepack_tab/priority_slider.py`, долю манги с аниме —
`animepack_tab/manga_adaptation_control.py`. Таблица состава пака после
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
`generator_media.py`, доли способов подачи —
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
