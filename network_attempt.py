"""Borrow session identity without inheriting multi-minute retry adapters."""
from contextlib import contextmanager

import requests


@contextmanager
def single_attempt_session(source):
    if not isinstance(source, requests.Session):
        yield source
        return
    with requests.Session() as session:
        session.headers.update(source.headers)
        session.cookies.update(source.cookies)
        session.proxies.update(source.proxies)
        session.auth, session.verify, session.cert = source.auth, source.verify, source.cert
        session.trust_env = source.trust_env
        try:
            yield session
        finally:
            source.cookies.update(session.cookies)
