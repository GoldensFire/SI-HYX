"""Run every collected test in bounded processes to isolate native Qt state."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = []
    for line in args.collection.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"(tests[\\/].+\.py): (\d+)", line)
        if match:
            rows.append((match[1], int(match[2])))
    if not rows:
        parser.error("No collected file counts found.")
    args.output.mkdir(parents=True, exist_ok=True)
    batches, current, count = [], [], 0
    for path, size in rows:
        if current and (len(current) >= 15 or count + size > 250):
            batches.append(current)
            current, count = [], 0
        current.append(path)
        count += size
    if current:
        batches.append(current)
    results = []
    prior = {}
    if args.resume and (args.output / "result.json").is_file():
        saved = json.loads((args.output / "result.json").read_text(encoding="utf-8"))
        prior = {row["batch"]: row for row in saved["batches"] if row["exit_code"] == 0}
    for number, files in enumerate(batches, 1):
        if number in prior and prior[number]["files"] == files:
            results.append(prior[number])
            continue
        prefix = args.output / f"batch-{number:02d}"
        xml = prefix.with_suffix(".xml")
        with tempfile.TemporaryDirectory(prefix="sihyx-test-batch-") as temporary:
            command = [sys.executable, "-m", "pytest", "-q", *files,
                       "--basetemp=" + str(Path(temporary) / "pytest"), "--junitxml=" + str(xml)]
            with prefix.with_suffix(".log").open("wb") as stream:
                code = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT).returncode
        result = {"batch": number, "files": files, "exit_code": code}
        if xml.is_file():
            suite = ET.parse(xml).getroot().find("testsuite")
            result.update({key: int(suite.get(key, 0))
                           for key in ("tests", "failures", "errors", "skipped")})
        results.append(result)
        summary = {"collected": sum(size for _, size in rows), "files": len(rows),
                   "batches": results, "complete": len(results) == len(batches)}
        (args.output / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Batch {number}/{len(batches)}: exit {code}; {result.get('tests', 'native failure')} tests",
              flush=True)
    raise SystemExit(1 if any(row["exit_code"] for row in results) else 0)


if __name__ == "__main__":
    main()
