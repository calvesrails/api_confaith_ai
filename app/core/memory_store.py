from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any


class LocalTestMemoryStore:
    def __init__(
        self,
        max_test_requests: int = 20,
        max_whatsapp_sends: int = 20,
        max_logs: int = 100,
    ) -> None:
        self.max_test_requests = max_test_requests
        self.max_whatsapp_sends = max_whatsapp_sends
        self.max_logs = max_logs
        self._lock = Lock()
        self._test_requests: list[dict[str, Any]] = []
        self._whatsapp_sends: list[dict[str, Any]] = []
        self._logs: list[dict[str, Any]] = []
        self._last_webhook_payload: dict[str, Any] | None = None
        self._last_webhook_event: dict[str, Any] | None = None
        self._batch_realtime_profiles: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self._test_requests.clear()
            self._whatsapp_sends.clear()
            self._logs.clear()
            self._last_webhook_payload = None
            self._last_webhook_event = None
            self._batch_realtime_profiles.clear()

    def add_log(
        self,
        stage: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        log_entry = {
            "timestamp": _iso_now(),
            "stage": stage,
            "message": message,
            "data": deepcopy(data) if data is not None else None,
        }
        with self._lock:
            self._logs.insert(0, log_entry)
            del self._logs[self.max_logs :]

    def upsert_test_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        request_id = str(request_data["request_id"])
        with self._lock:
            index = self._find_request_index(lambda item: item["request_id"] == request_id)
            if index is None:
                self._test_requests.insert(0, deepcopy(request_data))
                stored_index = 0
            else:
                self._test_requests[index] = deepcopy(request_data)
                stored_index = index
            del self._test_requests[self.max_test_requests :]
            return deepcopy(self._test_requests[stored_index])

    def record_whatsapp_send(self, send_data: dict[str, Any]) -> None:
        with self._lock:
            self._whatsapp_sends.insert(0, deepcopy(send_data))
            del self._whatsapp_sends[self.max_whatsapp_sends :]

    def update_request_by_phone(
        self,
        phone_normalized: str,
        updates: dict[str, Any],
        *,
        only_waiting_whatsapp: bool = False,
    ) -> dict[str, Any] | None:
        def matches(item: dict[str, Any]) -> bool:
            if item.get("phone_normalized") != phone_normalized:
                return False
            if not only_waiting_whatsapp:
                return True
            return item.get("business_status") == "waiting_whatsapp_reply"

        return self._update_request(matches, updates)

    def update_request_by_message_id(
        self,
        meta_message_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        return self._update_request(
            lambda item: item.get("meta_message_id") == meta_message_id,
            updates,
        )

    def set_last_webhook(
        self,
        payload: dict[str, Any],
        event_summary: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            self._last_webhook_payload = deepcopy(payload)
            self._last_webhook_event = deepcopy(event_summary)

    def set_batch_realtime_profile(
        self,
        batch_id: str,
        profile: dict[str, Any],
    ) -> None:
        with self._lock:
            self._batch_realtime_profiles[str(batch_id)] = deepcopy(profile)

    def get_batch_realtime_profile(self, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            profile = self._batch_realtime_profiles.get(str(batch_id))
            return deepcopy(profile) if profile is not None else None

    def clear_batch_realtime_profile(self, batch_id: str) -> None:
        with self._lock:
            self._batch_realtime_profiles.pop(str(batch_id), None)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "recent_requests": deepcopy(self._test_requests),
                "recent_whatsapp_sends": deepcopy(self._whatsapp_sends),
                "logs": deepcopy(self._logs),
                "last_webhook_payload": deepcopy(self._last_webhook_payload),
                "last_webhook_event": deepcopy(self._last_webhook_event),
            }

    def _update_request(
        self,
        predicate,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._lock:
            index = self._find_request_index(predicate)
            if index is None:
                return None
            updated_record = deepcopy(self._test_requests[index])
            updated_record.update(deepcopy(updates))
            self._test_requests[index] = updated_record
            return deepcopy(updated_record)

    def _find_request_index(self, predicate) -> int | None:
        for index, item in enumerate(self._test_requests):
            if predicate(item):
                return index
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_memory_store = LocalTestMemoryStore()


def get_memory_store() -> LocalTestMemoryStore:
    return _memory_store
