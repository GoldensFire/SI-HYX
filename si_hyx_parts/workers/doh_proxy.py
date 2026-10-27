# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Обход подменённого DNS провайдера для yt-dlp.

Некоторые провайдеры отвечают на запрос сайта адресом-заглушкой, а AAAA-запрос
роняют — системный getaddrinfo тогда падает с 11001/11003 («Failed to resolve»),
хотя сам сайт по настоящему адресу доступен. yt-dlp.exe — отдельный процесс, и
подменить ему резолвер можно только через --proxy. Поэтому здесь крошечный
локальный HTTP-прокси: адрес хоста он берёт по DNS-over-HTTPS (Cloudflare,
Google — по IP, без системного DNS) и дальше просто перекладывает байты.
"""
import json
import socket
import threading
import time
import urllib.parse
import urllib.request

# Ответ DoH по IP-адресу резолвера: сертификаты 1.1.1.1 и 8.8.8.8 выписаны и на IP.
_DOH_URLS = (
    "https://1.1.1.1/dns-query?name={}&type=A",
    "https://8.8.8.8/resolve?name={}&type=A",
)
_ALLOWED_PORTS = (80, 443)
# Сколько ждать первого ответа сервера, прежде чем счесть адрес мёртвым.
_FIRST_REPLY_TIMEOUT = 8
_good_addr = {}
_cache = {}
_cache_lock = threading.Lock()
_proxy = None
_proxy_lock = threading.Lock()
# Хосты, на которых системный DNS уже подвёл: следующие загрузки с них сразу
# идут через прокси, без заведомо провальной первой попытки.
_bypass_hosts = set()

DNS_ERROR_TOKENS = (
    "failed to resolve", "getaddrinfo failed", "errno 11001", "errno 11003",
    "name or service not known", "nodename nor servname",
)


def is_dns_error(detail):
    low = str(detail).lower()
    return any(token in low for token in DNS_ERROR_TOKENS)


def remember_host(host):
    if host:
        _bypass_hosts.add(host.lower())


def host_needs_bypass(host):
    return bool(host) and host.lower() in _bypass_hosts


def doh_resolve(host, timeout=8):
    """IPv4-адреса хоста по DNS-over-HTTPS; пустой список, если резолверы молчат."""
    host = host.strip().rstrip(".").lower()
    now = time.time()
    with _cache_lock:
        hit = _cache.get(host)
        if hit and hit[0] > now:
            return list(hit[1])
    for url in _DOH_URLS:
        req = urllib.request.Request(
            url.format(urllib.parse.quote(host)),
            headers={"Accept": "application/dns-json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError):
            continue
        answers = [a for a in data.get("Answer") or () if a.get("type") == 1]
        addrs = [a["data"] for a in answers if a.get("data")]
        if addrs:
            ttl = min(int(a.get("TTL") or 60) for a in answers)
            with _cache_lock:
                _cache[host] = (now + max(30, min(ttl, 3600)), addrs)
            return addrs
    return []


def _open_upstream(host, port, first):
    """Соединение с хостом, который реально ответил на первые байты клиента.

    Часть адресов из DNS принимает TCP, но молчит на TLS (у rutube.ru один из
    двух так и висит), поэтому «подключился» ещё не значит «работает»: шлём
    ClientHello/запрос и ждём первый ответ, иначе берём следующий адрес.
    Возвращает (сокет, первые байты ответа)."""
    addrs = doh_resolve(host) or [host]
    good = _good_addr.get((host, port))
    if good in addrs:
        addrs = [good] + [a for a in addrs if a != good]
    last = None
    for addr in addrs:
        sock = None
        try:
            sock = socket.create_connection((addr, port), timeout=10)
            sock.sendall(first)
            sock.settimeout(_FIRST_REPLY_TIMEOUT)
            reply = sock.recv(65536)
            if reply:
                _good_addr[(host, port)] = addr
                return sock, reply
            last = OSError(f"{addr} закрыл соединение")
        except OSError as e:
            last = e
        if sock is not None:
            sock.close()
    raise last or OSError(f"не удалось подключиться к {host}")


def _read_tls_record(conn, data):
    """Дочитывает первую TLS-запись (ClientHello) целиком: без неё сервер молчит,
    и живой адрес выглядел бы мёртвым."""
    while len(data) < 5:
        chunk = conn.recv(65536)
        if not chunk:
            return data
        data += chunk
    if data[0] != 0x16:
        return data
    need = 5 + int.from_bytes(data[3:5], "big")
    while len(data) < need:
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
    return data


def _pipe(src, dst):
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _read_head(conn):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            return None, b""
        buf += chunk
        if len(buf) > 65536:
            return None, b""
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def _split_target(target, default_port):
    host, sep, port = target.rpartition(":")
    if not sep or not port.isdigit():
        return target, default_port
    return host.strip("[]"), int(port)


def _handle(conn):
    upstream = None
    try:
        conn.settimeout(60)
        head, rest = _read_head(conn)
        if not head:
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = (lines[0].split(" ") + ["", "", ""])[:3]
        if method.upper() == "CONNECT":
            host, port = _split_target(target, 443)
            if port not in _ALLOWED_PORTS:
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            first = _read_tls_record(conn, rest)
            if not first:
                return
            upstream, reply = _open_upstream(host, port, first)
        else:
            # Обычный HTTP через прокси: в строке запроса абсолютный URL.
            parts = urllib.parse.urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            port = parts.port or 80
            if port not in _ALLOWED_PORTS:
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            kept = [ln for ln in lines[1:]
                    if not ln.lower().startswith(("proxy-connection:", "connection:"))]
            request = "\r\n".join([f"{method} {path} {version}", *kept,
                                   "Connection: close", "", ""])
            upstream, reply = _open_upstream(
                parts.hostname, port, request.encode("latin-1") + rest)
        conn.sendall(reply)
        conn.settimeout(None)
        upstream.settimeout(None)
        back = threading.Thread(target=_pipe, args=(upstream, conn), daemon=True)
        back.start()
        _pipe(conn, upstream)
        back.join()
    except OSError:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
    finally:
        for s in (conn, upstream):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def _serve(server):
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


def proxy_url():
    """Адрес общего прокси вида http://127.0.0.1:PORT (запускается при первом вызове)."""
    global _proxy
    with _proxy_lock:
        if _proxy is None:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            server.listen(64)
            threading.Thread(target=_serve, args=(server,), daemon=True,
                             name="doh-proxy").start()
            _proxy = server
        return f"http://127.0.0.1:{_proxy.getsockname()[1]}"
