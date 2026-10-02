# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Wire format of the readers' unofficial APIs, verified 2026-10-01.

Protocol references: keiyoushi/extensions-source VrfSigner.kt and Cipher.kt.
Comix material: public secure-tm5efk-B6Wo2GRC.js; no remote code is executed.
Keep substitutions here so a reader protocol update affects one module.
"""
import base64
import json


MANGAFIRE = (
    ("yINlmUNho8VYJT+ibTIP+9ESiULpVEtMOoD6U6lRE0R/xwXo/Xp9NrUgC4cw/Lmo33vUyjUE40kUoEWIr/fxfNNcq2s79ShQ5NhNrFnJ4hXPwOu/SuXzIbuTQKGFvfm08E9jvCfqAtoDqvQq3dVWPQFmJjgvkISBeXY3BgANR+yVnjGbcxZ47d6kLNfZPIayTq3/YGySb1KuVZodWp/WGNAO5pfMcpaK53Hhs0allBszaMaxuouOwdxbwgxIw6YunSsXjI05Yi0j9j4eHKfSXR8Ifo/Od+8iamRfCXTyvm7NGRGYdcQ0ywcK/u6RXhrbcCm4t2eCtrDgQVecJGkQ+A==",
     "0Ec58JOY3uBzJK9m3zqIOpdlF7UFiax9DmA=", 90),
    ("IUFltCxD3Oc2cwCgkJffthaOg9cgPUb0LgW6H/VtfcF0kc5F25t+aWj6JH9VOhOaY0rAFdUxlDnl5BLNvwEJvQtP5qcw7vdb/K+chnbwnspSHT8mz5lqwz41TezG0hkO06FTjJZhsyNuFLDpD2ZZxQj/QIRcF90zpmQ7Byu483WsQqUE0C342HL+JXngRB6fRzxRyVTaKu83h7UYTJ0QMt6ixFh6S3F8gqkKwrGTL3jHNBsD45UnifK8+RGtishQV2K3rujLKEkiZxpr2dYcudFW4oFsDKhad3CLBvuyTqsCo4B7mL5IKQ1vXo/MOOvq1I1d8ar9X6Ttu5KF4fZgiA==",
     "AAdjb1iPY8CiDmq9H34tKTBF8a3oDQ==", 53),
    ("NQHlu1/wVO5EmkwQymF810qqY2xG1k2obcas4Z9mCsPEIFl9pRIjFxbJ7ybMHbBckT5Ton85E0FOeHezbh/mjlEYpmpnlXOS8dgrqeq2KfxImTh1YK9y0PeMNhzA1OQzSY9brYOJq/l2QnE/hwOeZIhPixVSKIUlDb5vLcH6RWKxkIEMuP0bDwIqQ71AJJaEaMJL7A6YtyIwoRT+L5v4aZzodN/0+3nOGsfblFjgxSfPzVDjNFeNl5P26+kEC/8AHgdrpAbt3hHz3HrRN1Y6e+JHgF7ncFWnoF0y3THL1S71WgWGCa6KtSzTCCG58n68nTyj2T3Sshk7utqCtMi/ZQ==",
     "DELOJgPsVaCcblDtTGMdHzM=", 186),
)
COMIX = (
    ("gbicCvAMzfcXEtGAyjvvhmb2yCWzWhjqcxXZ7ZhpzANOzoQLo3nuPZ2vK9dkb9hJExC0Vni/hdQBceI+mw611gkhQFjBuf4bJg1TxYqM+SL4YDqtwjxiGSdeH7so7Fn1HiRo37Z+RNvl44twXWVhomtMjw+8bemfmv9XEXr7mS82MxaCOJZRR0oHd9PLI5O+gyBGT6hcLoduNa7yCObVVCk3bFWsoD+xcqTrBcP6dNJN/NB1Br2QGhSN2snHAqeRNKVFQiyeAFLPSKGwY8aq9EPgsi17qd4ywPMxiH8w6N1qX1tLKtzhOeemHWeJQfFQ5H23q7qSlJUcjgTEl3x2/Q==",
     "rafYl4oSAKQX+GYoic9oW4iGwiYpZzs0", 189),
    ("2lQehmgyYFAoWUi0haazZqHy5zZ34NN+VzlfsoB2Y1yY0IuMLjgVcV2xt8t4moH+AP0NMJ5qekW7DFIHEWKkOgIBIMhDdA8lbM6iHKjDlq6IChpb3CnA9NmsvQW/afdt1SfJjTdwcvpKqunCJLxBFmXX9hecm6tGb+HRxD7BC3njoxPxgnX5pdKP1IMSkd4/O3NRfZSE6DVLG2s9uexaipA05cpJzE8Qkv/z5jzHAwlEWOLd3yxA+0cvVbpOoJPFGc8f1lb4vu2HUxjuuEwEQk0GsPCVnyKvfOoh9TG2YYmZLV4I67UU2NsrrakqZ47k/O+ne25/DjPGZCMdnZcmzQ==",
     "2USAq+VTo5ht4bQn+K9DUcpUQRTtrB56", 133),
    ("+mhJSFwzaV+PQPDyKp2scO/S9SdFsy/7e56UWT8XHbK3E2+19nEPwfwOgE9uVCaDtOAWTobCZX+cBCXlIbBqyDyQB1beKLspW6kGPhBCV9x0jf0KUeFhHjmlMf7qMFIB41PfDFprZ3bJiK4YxrZDv+K6dcwJmggVO8f5ktrXTM0cZL4fer0SpnkbvNajPbHxfuTz5lVEBarOI4rdc+2V6zTsjpfQYjgN1MMr6EvA6eehN6dQ1bgUogt9rZOBbQBeNnLYY00uZqSoJBnFi5gthCJsWF33ykosn9v/9KB8udMCz0YRYImrA4VHr5mMgpH4xDXLeEHRd5vZOiAalofuMg==",
     "yNHlokVEnuecesDrB/lDhVuUNiheWc3a47VtkwZ2ENg=", 32),
)


def canonical_params(params):
    """Array keys use the same numbered representation as the web reader."""
    out = []
    for name, value in sorted(params.items()):
        values = value if isinstance(value, (list, tuple)) else [value]
        array = name.endswith("[]") or isinstance(value, (list, tuple))
        for index, item in enumerate(values):
            key = f"{name.removesuffix('[]')}[{index}]" if array else name
            out.append((key, str(item).strip()))
    return out


def sign(path, entries, stages):
    query = "&".join(f"{key}={value}" for key, value in entries)
    data = (path + ("?" + query if query else "")).encode("utf-8")
    for table64, key64, previous in stages:
        table, key = base64.b64decode(table64), base64.b64decode(key64)
        output = bytearray()
        for index, value in enumerate(data):
            previous = table[value ^ key[index % len(key)] ^ previous]
            output.append(previous)
        data = bytes(output)
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_comix(value):
    data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    for table64, key64, previous in reversed(COMIX):
        table, key = base64.b64decode(table64), base64.b64decode(key64)
        inverse = [0] * 256
        for index, value in enumerate(table):
            inverse[value] = index
        output = bytearray()
        for index, value in enumerate(data):
            output.append(inverse[value] ^ key[index % len(key)] ^ previous)
            previous = value
        data = bytes(output)
    return json.loads(data)
