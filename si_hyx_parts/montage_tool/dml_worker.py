# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сеанс onnxruntime на DirectML в Python отдельной среды
(vision.WorkerSession): у приложения onnxruntime без DirectML, а пакеты ORT
делят одно имя модуля и вместе не ставятся. Здесь — только numpy и
onnxruntime-directml.

    python -I -X utf8 dml_worker.py <модель.onnx> [потоки]

Обмен — кадрами в stdin/stdout: 4 байта длины (little-endian) и данные.
Первый кадр ответа — JSON {provider, inputs, outputs, meta} (provider пуст —
сеанс не создан, error — почему). Запрос — JSON {"inputs": [имена]} и по
кадру .npy на каждый вход; ответ — JSON {"ok": true, "n"} и n кадров .npy
(выходы по порядку) или {"ok": false, "error"}. Конец stdin — выход."""
import io
import json
import os
import struct
import sys

import numpy as np


def _read(f):
    head = f.read(4)
    if len(head) < 4:
        return None
    n = struct.unpack("<I", head)[0]
    data = f.read(n)
    return data if len(data) == n else None


def _write(f, data):
    f.write(struct.pack("<I", len(data)))
    f.write(data)


def _npy(a):
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(a), allow_pickle=False)
    return buf.getvalue()


def _message(e):
    """Текст ошибки ORT: сообщение Windows приходит в кодировке системы, и
    pybind11 падает на нём с UnicodeDecodeError — тогда декодируем сами."""
    if isinstance(e, UnicodeDecodeError) and isinstance(e.object, bytes):
        return e.object.decode("mbcs" if os.name == "nt" else "utf-8", "replace")
    return str(e)


def _own_stdout():
    """Протокол — в свою копию stdout, а stdout процесса — в stderr:
    нативный код ORT/DirectML печатает в него напрямую (в Windows — по
    GetStdHandle, мимо дескриптора 1) и иначе ломает кадры."""
    sys.stdout.flush()
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    if os.name == "nt":
        import ctypes
        import msvcrt
        ctypes.windll.kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(2))   # STD_OUTPUT_HANDLE
    return out


def main():
    model = sys.argv[1]
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    out = _own_stdout()
    inp = sys.stdin.buffer
    import onnxruntime as ort            # после подмены stdout: DLL берёт его при загрузке
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.log_severity_level = 3
    # DirectML требует последовательного исполнения и без шаблонов памяти.
    so.enable_mem_pattern = False
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    try:
        sess = ort.InferenceSession(model, sess_options=so,
                                    providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        info = {"provider": sess.get_providers()[0],
                "inputs": [{"name": i.name, "shape": i.shape} for i in sess.get_inputs()],
                "outputs": [{"name": o.name, "shape": o.shape} for o in sess.get_outputs()],
                "meta": dict(sess.get_modelmeta().custom_metadata_map)}
    except Exception as e:               # noqa: BLE001 — причина уходит в ответ
        sess, info = None, {"provider": "", "error": str(e)}
    _write(out, json.dumps(info).encode("utf-8"))
    out.flush()
    if sess is None:
        return
    while True:
        req = _read(inp)
        if not req:
            return
        feeds = {}
        for name in json.loads(req.decode("utf-8"))["inputs"]:
            data = _read(inp)
            if data is None:
                return
            feeds[name] = np.load(io.BytesIO(data), allow_pickle=False)
        try:
            res = sess.run(None, feeds)
        except Exception as e:           # noqa: BLE001 — ошибка уходит в ответ
            _write(out, json.dumps({"ok": False, "error": _message(e)}).encode("utf-8"))
        else:
            _write(out, json.dumps({"ok": True, "n": len(res)}).encode("utf-8"))
            for r in res:
                _write(out, _npy(r))
        out.flush()


if __name__ == "__main__":
    main()
