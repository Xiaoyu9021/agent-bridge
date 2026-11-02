from __future__ import annotations

import secrets
import threading
import time
from collections import deque

from codex_bridge.models import DeviceInput, PairInput
from codex_bridge.storage.store import BridgeError, Store


class HostControl:
    """Only local UI/console can open pairing, approve devices, or revoke access."""

    def __init__(self, store: Store, host: DeviceInput):
        self.store, self.host = store, host
        self.token = store.register(host, "host")
        self.lock = threading.RLock()
        self.code = ""
        self.expires = 0.0
        self.requests: dict[str, dict] = {}
        self.failures: deque[float] = deque(maxlen=100)

    def open_pairing(self) -> str:
        with self.lock:
            self.code = f"{secrets.randbelow(100000000):08d}"
            self.expires = time.monotonic() + self.store.settings.pair_ttl
            return self.code

    def close_pairing(self):
        with self.lock:
            self.code = ""
            self.expires = 0
            self.requests.clear()

    def request(self, model: PairInput) -> str:
        with self.lock:
            now = time.monotonic()
            while self.failures and now - self.failures[0] > 60:
                self.failures.popleft()
            if len(self.failures) >= 5:
                raise BridgeError("rate_limited", "配对尝试过于频繁，请稍后再试", 429)
            if not self.code or now >= self.expires or not secrets.compare_digest(self.code, model.code):
                self.failures.append(now)
                raise BridgeError("invalid_pairing", "配对码错误、已使用或已过期", 403)
            self.requests = {key: val for key, val in self.requests.items() if val["expires"] > now}
            if len(self.requests) >= 20:
                raise BridgeError("pairing_full", "待确认配对过多，请在主机处理", 429)
            key = secrets.token_urlsafe(32)
            self.requests[key] = {"device": DeviceInput(**model.model_dump(exclude={"code"})),
                                  "expires": now + self.store.settings.pair_ttl, "status": "pending"}
            self.code = ""
            return key

    def pending(self) -> list[dict]:
        with self.lock:
            now = time.monotonic()
            return [{"request_id": key, **value["device"].model_dump()} for key, value in self.requests.items()
                    if value["status"] == "pending" and value["expires"] > now]

    def approve(self, request_id: str, accepted: bool = True):
        with self.lock:
            req = self.requests.get(request_id)
            if not req or req["expires"] <= time.monotonic() or req["status"] != "pending":
                raise BridgeError("expired", "配对请求已处理或已过期", 410)
            if accepted:
                req["token"] = self.store.register(req["device"])
            req["status"] = "approved" if accepted else "rejected"

    def poll(self, request_id: str) -> dict:
        with self.lock:
            req = self.requests.get(request_id)
            if not req or req["expires"] <= time.monotonic():
                self.requests.pop(request_id, None)
                raise BridgeError("expired", "配对请求已过期，请重新发起", 410)
            response = {"status": req["status"]}
            if req["status"] == "approved":
                response.update(token=req["token"], device_id=req["device"].id,
                                host_device_id=self.host.id)
                del self.requests[request_id]
            return response
