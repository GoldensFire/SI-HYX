"""Second opinion on audible Japanese versus Russian captions in each SIQ clip."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gemini_api as gemini
from utils import load_settings


SCHEMA = {"type": "object", "properties": {
    "japanese_audio": {"type": "boolean"},
    "russian_captions_visible": {"type": "boolean"},
    "foreign_captions_visible": {"type": "boolean"},
    "sync": {"type": "string", "enum": ["ok", "mismatch", "uncertain"]},
    "translation": {"type": "string", "enum": ["ok", "mismatch", "uncertain"]},
    "heard_example": {"type": "string"},
    "visible_example": {"type": "string"},
    "reason": {"type": "string"}}, "required": ["japanese_audio", "russian_captions_visible",
    "foreign_captions_visible", "sync", "translation", "heard_example", "visible_example", "reason"]}

PROMPT = (
    "Проверь этот 15-секундный отрывок аниме. Слушай японскую речь и читай "
    "РЕАЛЬНО ВИДИМЫЕ субтитры, не опирайся на предполагаемый текст. Проверь, "
    "что озвучка японская, сабы русские, нет английских сабов, перевод соответствует "
    "услышанному, реплики появляются синхронно (погрешность до 0.5 с). "
    "Короткое остаточное отображение после конца речи нормально. Начало/конец "
    "ролика может срезать фразу — это не рассинхрон. Надписи в самом рисунке "
    "и имена собственные латиницей не считай иностранными сабами. "
    "Если есть конкретное несоответствие, приведи время и услышанную/видимую "
    "реплики в reason. Если достоверно сравнить речь не получается, укажи uncertain. "
    "Верни heard_example на японском и visible_example с кадра для одной "
    "проверенной реплики, с временем внутри клипа."
)


def check(client, video, row, number):
    started = time.monotonic()
    body = {"model": client.model, "contents": [{"parts": [
        {"inlineData": {"mimeType": "video/mp4", "data": base64.b64encode(video).decode("ascii")}},
        {"text": PROMPT}]}], "generationConfig": {
        "thinkingConfig": {"thinkingLevel": str(client.thinking or "high").upper()},
        "responseMimeType": "application/json", "responseSchema": gemini._generate_schema(SCHEMA)}}
    response = gemini._json_from_text(gemini._extract_text(client._post(body)))
    passed = (response.get("japanese_audio") and response.get("russian_captions_visible")
              and not response.get("foreign_captions_visible")
              and response.get("sync") == "ok" and response.get("translation") == "ok")
    return {"number": number, "file": row["file"], "passed": bool(passed),
            "seconds": round(time.monotonic() - started, 2), **response}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--numbers", default="")
    args = parser.parse_args()
    saved = load_settings()
    settings = saved.get("animepack") or {}
    client = gemini.GeminiClient(str((saved.get("api_keys") or {}).get("gemini") or ""),
        model=settings.get("gemini_model"), thinking=settings.get("gemini_thinking"), log=print)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {"package": str(args.package.resolve()), "model": client.model, "questions": []}
    wanted = {int(n) for n in args.numbers.split(",") if n.strip()}
    with zipfile.ZipFile(args.package) as archive, ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = json.loads(archive.read("episodes.json"))
        pending = {pool.submit(check, client, archive.read("Video/" + row["file"]), row, number): number
                   for number, row in enumerate(rows, 1) if not wanted or number in wanted}
        for future in as_completed(pending):
            try:
                result = future.result()
            except Exception as error:
                result = {"number": pending[future], "passed": False, "error": str(error)}
            report["questions"].append(result)
            report["questions"].sort(key=lambda row: row["number"])
            report["passed"] = len(report["questions"]) == len(pending) and all(
                row["passed"] for row in report["questions"])
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
