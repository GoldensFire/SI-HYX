"""Listen to every generated episode clip and compare its visible caption mode."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gemini_api as gemini
from utils import load_settings

SCHEMA = {"type": "object", "properties": {
    "audio_language": {"type": "string", "enum": ["ja", "ru", "en", "other", "none", "uncertain"]},
    "russian_captions_visible": {"type": "boolean"},
    "foreign_captions_visible": {"type": "boolean"},
    "sync": {"type": "string", "enum": ["ok", "mismatch", "uncertain", "absent"]},
    "translation": {"type": "string", "enum": ["ok", "mismatch", "uncertain", "absent"]},
    "opening_or_ending": {"type": "boolean"},
    "obvious_wrong_title": {"type": "boolean"},
    "heard_example": {"type": "string"}, "visible_example": {"type": "string"},
    "reason": {"type": "string"}}, "required": [
        "audio_language", "russian_captions_visible", "foreign_captions_visible", "sync",
        "translation", "opening_or_ending", "obvious_wrong_title", "heard_example",
        "visible_example", "reason"]}

PROMPT = (
    "Проверь реальный 15-секундный отрывок аниме. Определи язык СЛЫШИМОЙ речи, "
    "не делай вывод по метаданным. Отсутствие речи отмечай none; нельзя считать "
    "музыку или междометие подтверждением языка. Читай только реально видимые "
    "субтитры. Надписи в самом рисунке и имена собственные латиницей не считай "
    "иностранными сабами. Проверь, что это сцена серии, а не OP/ED. Если явно "
    "узнаёшь другое аниме, отметь obvious_wrong_title; недостаток узнаваемых "
    "персонажей не означает другой тайтл. Для русских сабов проверь смысл "
    "перевода и синхронность (погрешность до 0.5 с); срезанная началом/концом "
    "фраза и короткое остаточное отображение после речи нормальны. Приведи "
    "короткий heard_example на языке речи и visible_example с кадра с временем. "
    "Если сравнить смысл достоверно нельзя, укажи uncertain. Если есть проблема, "
    "укажи конкретное время и наблюдение в reason."
)


def inspect(client, source, mode, row, data):
    started = time.monotonic()
    mode_text = ("Нужны японская речь и видимые русские субтитры."
                 if mode == "ru" else "Нужна японская речь без русских сабов; английские разрешены.")
    prompt = f"{PROMPT}\nОжидаемый тайтл: {row['title']}. {mode_text}"
    body = {"model": client.model, "contents": [{"parts": [
        {"inlineData": {"mimeType": "video/mp4", "data": base64.b64encode(data).decode("ascii")}},
        {"text": prompt}]}], "generationConfig": {
            "thinkingConfig": {"thinkingLevel": str(client.thinking or "high").upper()},
            "responseMimeType": "application/json", "responseSchema": gemini._generate_schema(SCHEMA)}}
    value = gemini._json_from_text(gemini._extract_text(client._post(body)))
    passed = (value.get("audio_language") == "ja" and not value.get("opening_or_ending")
              and not value.get("obvious_wrong_title"))
    if mode == "ru":
        passed = (passed and value.get("russian_captions_visible")
                  and not value.get("foreign_captions_visible")
                  and value.get("sync") == "ok" and value.get("translation") == "ok")
    else:
        passed = passed and not value.get("russian_captions_visible")
    return {"source": source, "mode": mode, "file": row["file"], "mal": row["mal"],
            "title": row["title"], "passed": bool(passed),
            "seconds": round(time.monotonic() - started, 3), **value}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    summary = json.loads((args.root / "summary.json").read_text(encoding="utf-8"))
    out = args.root / "semantic.json"
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"questions": []}
    completed = {(r["source"], r["mode"], r["file"]) for r in report["questions"]
                 if "error" not in r}
    raw = load_settings()
    settings = raw.get("animepack") or {}
    client = gemini.GeminiClient(str(raw.get("api_keys", {}).get("gemini") or ""),
                                 model=settings.get("gemini_model"),
                                 thinking=settings.get("gemini_thinking"), timeout=60, log=print)
    report["model"] = client.model
    log_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {}
        for source in summary["sources"]:
            for mode, result in source.get("modes", {}).items():
                if not result.get("package"):
                    continue
                with zipfile.ZipFile(result["package"]) as archive:
                    for row in result["questions"]:
                        key = (source["source"], mode, row["file"])
                        if key in completed:
                            continue
                        jobs[pool.submit(inspect, client, *key[:2], row,
                                         archive.read("Video/" + row["file"]))] = (key, row)
        for future in as_completed(jobs):
            key, row = jobs[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"source": key[0], "mode": key[1], "file": key[2],
                          "mal": row["mal"], "title": row["title"],
                          "passed": False, "error": str(error)}
            with log_lock:
                report["questions"] = [r for r in report["questions"]
                                       if (r["source"], r["mode"], r["file"]) != key]
                report["questions"].append(result)
                report["questions"].sort(key=lambda r: (r["source"], r["mode"], r["file"]))
                out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
