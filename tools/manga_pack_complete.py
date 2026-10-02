# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Fill a reviewed diagnostic pack with independently generated questions."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

from manga_pack_probe import contact_sheets


def read_report(root):
    return json.loads((root / "report.json").read_text(encoding="utf-8"))


def merge_manifest(base, extra):
    merged = dict(base)
    for field in ("titles", "studios"):
        entries = list(base.get(field, []))
        for entry in extra.get(field, []):
            if entry not in entries:
                entries.append(entry)
        merged[field] = entries
    merged["version"] = max(base["version"], extra["version"])
    return json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")


def complete(root, extra_root, allow_partial=False):
    base, extra = read_report(root), read_report(extra_root)
    missing = base["requested"] - base["made"]
    used_ids = {row["mal"] for row in base["questions"]}
    selected = [index for index, row in enumerate(extra["questions"])
                if row["mal"] not in used_ids][:missing]
    if allow_partial:
        missing = min(missing, len(selected))
    if base["cancelled"] or missing < 1 or len(selected) < missing:
        raise RuntimeError("The additional pack must exactly fill the missing questions")
    extra_rows = [extra["questions"][index] for index in selected]
    rows = base["questions"] + extra_rows
    if ((not allow_partial and len(rows) != base["requested"])
            or len({r["mal"] for r in rows}) != len(rows)):
        raise RuntimeError("Question counts or title uniqueness do not match")
    final = root / "Проверка манхвы — целые панели.siq"
    staging = final.with_suffix(".completing.siq")
    with zipfile.ZipFile(base["pack"]) as first, zipfile.ZipFile(extra["pack"]) as second:
        xml, additions = (ET.fromstring(z.read("content.xml")) for z in (first, second))
        namespace = xml.tag.split("}")[0].lstrip("{")
        ns = {"s": namespace}
        if additions.tag != xml.tag:
            raise RuntimeError("Incompatible package XML namespaces")
        all_questions = additions.findall(".//s:question", ns)
        questions = [all_questions[index] for index in selected]
        if len(questions) != missing or len(xml.findall(".//s:question", ns)) != base["made"]:
            raise RuntimeError("The archives do not match their generation reports")
        themes = xml.findall(".//s:themes", ns)[-1]
        template = deepcopy(themes[-1])
        target = themes[-1].find("s:questions", ns)
        if target is None:
            raise RuntimeError("The last theme has no question collection")
        settings = json.loads((root / "settings.json").read_text(encoding="utf-8"))
        per_theme = int(settings["questions"])
        for question in questions:
            target = next((theme.find("s:questions", ns) for theme in themes
                           if len(theme.find("s:questions", ns)) < per_theme), None)
            if target is None:
                theme = deepcopy(template)
                target = theme.find("s:questions", ns)
                target.clear()
                themes.append(theme)
            target.append(deepcopy(question))
        ET.register_namespace("", namespace)
        extra_manifest = json.loads(second.read("si-hyx-pack.json"))
        ids = {row["mal"] for row in extra_rows}
        extra_manifest["titles"] = [entry for entry in extra_manifest["titles"]
                                    if entry.get("mal") in ids or entry.get("shikimori") in ids]
        special = {
            "content.xml": ET.tostring(xml, encoding="utf-8", xml_declaration=True),
            "si-hyx-pack.json": merge_manifest(
                json.loads(first.read("si-hyx-pack.json")),
                extra_manifest),
        }
        folders = {"image": "Images", "video": "Video", "audio": "Audio"}
        allowed_extra = set()
        for question in questions:
            for item in question.findall(".//s:item", ns):
                if str(item.get("isRef", "")).lower() == "true":
                    allowed_extra.add(folders[item.get("type")] + "/" + unquote(item.text or ""))
        extra_images = {"Images/" + row["frame"]:
                        (extra_root / "frames" / row["frame"]).read_bytes() for row in extra_rows}
        members = set(first.namelist())
        for name in allowed_extra:
            if name in members and first.read(name) != second.read(name):
                raise RuntimeError(f"Conflicting package resource: {name}")
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for member in first.infolist():
                output.writestr(member, special.get(member.filename, first.read(member)))
            for member in second.infolist():
                if member.filename in allowed_extra and member.filename not in members:
                    output.writestr(member, second.read(member))
            for name, payload in extra_images.items():
                if name not in members and name not in allowed_extra:
                    output.writestr(name, payload)
    staging.replace(final)
    for row in extra_rows:
        shutil.copy2(extra_root / "frames" / row["frame"], root / "frames" / row["frame"])
    with (root / "generation.log").open("a", encoding="utf-8") as stream:
        stream.write("\n" + (extra_root / "generation.log").read_text(encoding="utf-8"))
    base.update(pack=str(final), made=len(rows), questions=rows,
                seconds=base["seconds"] + extra["seconds"],
                components=base.get("components", [base["pack"]]) + [extra["pack"]],
                additional_generation=extra.get("gemini", {}),
                batch_generation=base.get("batch_generation", []) + [extra.get("gemini", {})],
                additional_component_cancelled=extra["cancelled"],
                visual_review=base.get("visual_review", []) + extra.get("visual_review", []))
    (root / "report.json").write_text(json.dumps(base, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    contact_sheets(rows, root)
    print(f"Completed {len(rows)} questions: {final}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Folder containing the partial reviewed pack")
    parser.add_argument("additional", help="Folder containing the additional questions")
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    complete(Path(args.output).resolve(), Path(args.additional).resolve(), args.partial)


if __name__ == "__main__":
    main()
