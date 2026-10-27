# -*- coding: utf-8 -*-
"""Замер моделей индекса montage_tool: CPU против DirectML.

Запускать Python'ом отдельной среды с onnxruntime-directml (у приложения
onnxruntime без DirectML, а пакеты ORT делят одно имя модуля):

    uv venv %USERPROFILE%\\.cache\\si-hyx-montage\\dml-venv --python 3.11
    uv pip install --python <venv>\\Scripts\\python.exe onnxruntime-directml==1.24.4 numpy
    <venv>\\Scripts\\python.exe -I tools\\montage_dml_bench.py [--runs 10] [--eva02]

Модели берутся из кэша montage_tool (~/.cache/si-hyx-montage), вход —
случайный, той же формы и пачки, что у index (vision.py, shots.py). Ответ —
JSON: мс на вызов у CPU (6 потоков) и DirectML, ускорение и наибольшее
расхождение выходов."""
import argparse
import json
import os
import sys
import time

import numpy as np
import onnxruntime as ort

ROOT = os.environ.get("SIHYX_MONTAGE_CACHE") or os.path.join(
    os.path.expanduser("~"), ".cache", "si-hyx-montage")
# имя → (файл в кэше, форма входа, масштаб значений); пачки — как у index.
MODELS = {
    "transnetv2": ("shots/transnetv2.onnx", (1, 100, 27, 48, 3), 255.0),
    "face": ("anime/face_detect_v1.4_n.onnx", (1, 3, 640, 640), 1.0),
    "head": ("anime/head_detect_v2.0_n.onnx", (1, 3, 640, 640), 1.0),
    "person": ("anime/person_detect_v1.1_n.onnx", (1, 3, 640, 640), 1.0),
    "ccip": ("anime/ccip_feat.onnx", (4, 3, 384, 384), 1.0),
    "wd-vit": ("tagger/wd-vit-v3.onnx", (4, 448, 448, 3), 255.0),
    "wd-eva02": ("tagger/wd-eva02-large-v3.onnx", (4, 448, 448, 3), 255.0),
}


def _session(path, provider):
    so = ort.SessionOptions()
    so.intra_op_num_threads = 6
    so.inter_op_num_threads = 1
    so.log_severity_level = 3
    if provider == "DmlExecutionProvider":
        # DirectML требует последовательного исполнения и без шаблонов памяти.
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(path, sess_options=so, providers=[provider, "CPUExecutionProvider"])


def _time(sess, feed, runs):
    for _ in range(2):
        out = sess.run(None, feed)
    t = time.perf_counter()
    for _ in range(runs):
        sess.run(None, feed)
    return (time.perf_counter() - t) * 1000.0 / runs, out


def bench(name, runs):
    rel, shape, scale = MODELS[name]
    path = os.path.join(ROOT, *rel.split("/"))
    if not os.path.isfile(path):
        return {"model": name, "error": f"нет файла {path}"}
    rng = np.random.default_rng(0)
    x = (rng.random(shape, dtype=np.float32) * scale).astype(np.float32)
    row = {"model": name, "input": list(shape)}
    outs = {}
    for label, prov in (("cpu", "CPUExecutionProvider"), ("dml", "DmlExecutionProvider")):
        try:
            t0 = time.perf_counter()
            sess = _session(path, prov)
            row[f"{label}_load_s"] = round(time.perf_counter() - t0, 2)
            ms, out = _time(sess, {sess.get_inputs()[0].name: x}, runs)
            row[f"{label}_ms"] = round(ms, 1)
            row[f"{label}_providers"] = sess.get_providers()[:1]
            outs[label] = out
            del sess
        except Exception as e:           # noqa: BLE001 — провайдер не поднялся: так и пишем
            row[f"{label}_error"] = f"{type(e).__name__}: {e}"[:300]
    if "cpu_ms" in row and "dml_ms" in row:
        row["speedup"] = round(row["cpu_ms"] / row["dml_ms"], 2)
        row["max_abs_diff"] = round(max(float(np.max(np.abs(a.astype(np.float64) - b)))
                                        for a, b in zip(outs["cpu"], outs["dml"])), 5)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--eva02", action="store_true", help="ещё WD EVA02 (1,2 ГБ)")
    ap.add_argument("--only", default="", help="модели через запятую")
    args = ap.parse_args()
    names = [n for n in (args.only.split(",") if args.only else MODELS) if n]
    if not args.eva02 and not args.only:
        names.remove("wd-eva02")
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for n in names:
        rows.append(bench(n, args.runs))
        print(json.dumps(rows[-1], ensure_ascii=False), file=sys.stderr, flush=True)
    print(json.dumps({"onnxruntime": ort.__version__, "providers": ort.get_available_providers(),
                      "models": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
