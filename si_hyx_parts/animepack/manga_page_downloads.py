"""Concurrent page downloads with one in-flight fetch per shared neighbor."""
from concurrent.futures import Future
import threading


class PageDownloads:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}

    def fetch(self, address, action):
        with self.lock:
            future = self.pending.get(address)
            owner = future is None
            if owner:
                future = self.pending[address] = Future()
        if owner:
            try:
                future.set_result(action())
            except Exception as error:
                future.set_exception(error)
        return future.result()
