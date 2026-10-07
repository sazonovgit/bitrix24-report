"""Клиент REST Битрикс24: вебхук, списки, поля, стадии."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

DEAL_ENTITY_TYPE_ID = 2
COMPANY_ENTITY_TYPE_ID = 4
LIST_PAGE_SIZE = 50
MAX_LIST_PAGES = 400
ID_FILTER_KEYS = ("@id", "id", "ID")

WEBHOOK_RE = re.compile(
    r"^https?://(?P<domain>[^/]+)/rest/(?P<user>\d+)/(?P<code>[^/]+)/?",
    re.IGNORECASE,
)


class BitrixClientError(Exception):
    """Ошибка, которую можно показать пользователю."""


def parse_webhook_url(url: str) -> tuple[str, str]:
    raw = (url or "").strip()
    if not raw:
        raise BitrixClientError("Укажите URL входящего вебхука в настройках.")

    match = WEBHOOK_RE.match(raw)
    if match:
        domain = match.group("domain")
        token = f"{match.group('user')}/{match.group('code')}"
        return domain, token

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.netloc and parsed.path:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "rest" and parts[1].isdigit():
            return parsed.netloc, f"{parts[1]}/{parts[2]}"

    raise BitrixClientError(
        "Некорректный URL вебхука. Ожидается вид "
        "https://portal.bitrix24.ru/rest/1/xxxxxxxx/."
    )


def deal_details_url(domain: str, deal_id: int) -> str:
    host = (domain or "").strip().rstrip("/")
    if not host:
        return ""
    return f"https://{host}/crm/deal/details/{deal_id}/"


def _norm_key(key: str) -> str:
    return str(key).lower().replace("_", "")


def pick(data: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not data:
        return default
    normalized = {_norm_key(key): value for key, value in data.items()}
    for key in keys:
        value = normalized.get(_norm_key(key))
        if value not in (None, ""):
            return value
    return default


def as_int(value: Any, default: int = 0) -> int:
    if value in (None, "", False):
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (list, tuple)) and value:
        return as_int(value[0], default)
    if isinstance(value, dict):
        return as_int(pick(value, "id", "ID", "value", "VALUE"), default)
    text = str(value).strip()
    match = re.search(r"(\d+)", text.replace(" ", ""))
    if not match:
        return default
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return default


def unwrap_item(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        if isinstance(result.get("item"), dict):
            return result["item"]
        return result
    return {}


def coerce_next(value: Any) -> int | None:
    """Следующий start для списка. 0 / пусто / нечисло — конец."""
    if value is None or value is False or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def page_fingerprint(items: list[Any]) -> tuple[Any, ...]:
    sample: list[str] = [str(len(items))]
    probe = items[:2] + items[-2:] if len(items) > 2 else items
    for item in probe:
        if isinstance(item, dict):
            sample.append(str(pick(item, "id", "ID", "STATUS_ID", "statusId", default="")))
        else:
            sample.append(str(item)[:48])
    return tuple(sample)


def unwrap_list(result: Any, *keys: str) -> list[Any]:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, list):
                return value
        if all(str(key).isdigit() for key in result.keys()):
            return list(result.values())
    return []


def _friendly_sdk_error(exc: Exception) -> BitrixClientError:
    try:
        from b24pysdk.errors import BitrixAPIError, BitrixRequestError, BitrixRequestTimeout
    except Exception:
        return BitrixClientError(str(exc) or "Неизвестная ошибка Битрикс24.")

    if isinstance(exc, BitrixRequestTimeout):
        return BitrixClientError("Битрикс24 не ответил вовремя. Попробуйте ещё раз.")
    if isinstance(exc, BitrixRequestError):
        return BitrixClientError("Нет соединения с Битрикс24. Проверьте интернет.")
    if isinstance(exc, BitrixAPIError):
        error = str(getattr(exc, "error", "") or "").lower()
        description = str(getattr(exc, "error_description", "") or "")
        blob = f"{error} {description.lower()}"
        if "not found" in blob:
            return BitrixClientError("Объект в Битрикс24 не найден.")
        if "access denied" in blob:
            return BitrixClientError("Нет прав на чтение CRM. Проверьте права вебхука.")
        if "no_auth" in blob or "credential" in blob or "unauthorized" in blob:
            return BitrixClientError("Неверный вебхук. Проверьте URL в настройках.")
        if "insufficient_scope" in blob:
            return BitrixClientError(
                "У вебхука нет прав CRM. Добавьте право «CRM» входящему вебхуку."
            )
        return BitrixClientError(f"Ошибка Битрикс24: {description or error or exc}")
    return BitrixClientError(str(exc) or "Неизвестная ошибка Битрикс24.")


class BitrixClient:
    def __init__(self, webhook_url: str):
        self.domain, self.webhook_token = parse_webhook_url(webhook_url)
        try:
            from b24pysdk import BitrixWebhook, Client
        except ImportError as exc:
            raise BitrixClientError(
                "Не установлен пакет b24pysdk. Выполните pip install -r requirements.txt."
            ) from exc

        self._token = BitrixWebhook(domain=self.domain, webhook_token=self.webhook_token)
        self._client = Client(self._token)

    @classmethod
    def for_tests(cls, handler: Callable[[str, dict[str, Any] | None], Any]) -> BitrixClient:
        """Клиент без вебхука: handler(method, params) -> raw REST-ответ."""
        client = object.__new__(cls)
        client.domain = "test.bitrix24.ru"
        client.webhook_token = "1/test"
        client._handler = handler  # type: ignore[attr-defined]
        client._token = None
        client._client = None
        return client

    def _call_raw(self, api_method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        handler = getattr(self, "_handler", None)
        if handler is not None:
            response = handler(api_method, params)
            if not isinstance(response, dict):
                return {"result": response}
            return response
        try:
            response = self._token.call_method(api_method=api_method, params=params or {})
        except BitrixClientError:
            raise
        except Exception as exc:
            raise _friendly_sdk_error(exc) from exc

        if not isinstance(response, dict):
            return {"result": response}
        if response.get("error"):
            dummy = Exception(str(response.get("error_description") or response.get("error")))
            dummy.error = response.get("error")  # type: ignore[attr-defined]
            dummy.error_description = response.get("error_description")  # type: ignore[attr-defined]
            raise _friendly_sdk_error(dummy)
        return response

    def call_method(self, api_method: str, params: dict[str, Any] | None = None) -> Any:
        raw = self._call_raw(api_method, params)
        return raw.get("result", raw)

    def list_all(
        self,
        api_method: str,
        params: dict[str, Any] | None = None,
        *result_keys: str,
    ) -> list[Any]:
        collected: list[Any] = []
        start = 0
        seen_starts: set[int] = set()
        seen_pages: set[tuple[Any, ...]] = set()
        base = dict(params or {})
        for _ in range(MAX_LIST_PAGES):
            if start in seen_starts:
                break
            seen_starts.add(start)
            payload = dict(base)
            payload["start"] = start
            raw = self._call_raw(api_method, payload)
            result = raw.get("result", raw)
            items = unwrap_list(result, *result_keys)
            fingerprint = page_fingerprint(items)
            if items and fingerprint in seen_pages:
                break
            if items:
                seen_pages.add(fingerprint)
            collected.extend(item for item in items if item is not None)
            if not items:
                break
            nxt = coerce_next(raw.get("next"))
            if nxt is not None:
                if nxt <= start:
                    break
                start = nxt
                continue
            if len(items) < LIST_PAGE_SIZE:
                break
            start += LIST_PAGE_SIZE
        return collected

    def list_types(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.list_all("crm.type.list", {}, "types")
            if isinstance(row, dict)
        ]

    def item_fields(self, entity_type_id: int) -> dict[str, Any]:
        result = self.call_method(
            "crm.item.fields",
            {"entityTypeId": entity_type_id, "useOriginalUfNames": "N"},
        )
        if isinstance(result, dict):
            fields = result.get("fields", result)
            if isinstance(fields, dict):
                return fields
        return {}

    def list_items(
        self,
        entity_type_id: int,
        *,
        select: list[str] | None = None,
        filt: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "entityTypeId": entity_type_id,
            "select": select or ["*"],
            "order": {"id": "ASC"},
        }
        if filt:
            params["filter"] = filt
        unique: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in self.list_all("crm.item.list", params, "items"):
            if not isinstance(row, dict):
                continue
            item_id = as_int(pick(row, "id", "ID"))
            if item_id:
                if item_id in seen:
                    continue
                seen.add(item_id)
            unique.append(row)
        return unique

    def _list_items_one_page(
        self,
        entity_type_id: int,
        *,
        select: list[str],
        filt: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raw = self._call_raw(
            "crm.item.list",
            {
                "entityTypeId": entity_type_id,
                "select": select,
                "filter": filt,
                "start": 0,
            },
        )
        result = raw.get("result", raw)
        return [row for row in unwrap_list(result, "items") if isinstance(row, dict)]

    def _try_batch_get(
        self,
        entity_type_id: int,
        ids: list[int],
        found: dict[int, dict[str, Any]],
    ) -> bool:
        if not ids:
            return True
        cmd = {
            f"e{index}": f"crm.item.get?entityTypeId={entity_type_id}&id={item_id}"
            for index, item_id in enumerate(ids)
        }
        try:
            result = self.call_method("batch", {"halt": 0, "cmd": cmd})
        except BitrixClientError:
            return False
        payloads: Any = result
        if isinstance(result, dict) and isinstance(result.get("result"), dict):
            payloads = result["result"]
        if not isinstance(payloads, dict):
            return False
        got_any = False
        for value in payloads.values():
            item = unwrap_item(value)
            item_id = as_int(pick(item, "id", "ID"))
            if item_id:
                found[item_id] = item
                got_any = True
        return got_any

    def _fetch_missing_items(
        self,
        entity_type_id: int,
        ids: list[int],
        found: dict[int, dict[str, Any]],
    ) -> None:
        pending = [item_id for item_id in ids if item_id not in found]
        if not pending:
            return
        if self._try_batch_get(entity_type_id, pending, found):
            pending = [item_id for item_id in ids if item_id not in found]
            if not pending:
                return
        for item_id in pending:
            try:
                result = self.call_method(
                    "crm.item.get",
                    {"entityTypeId": entity_type_id, "id": item_id},
                )
            except BitrixClientError:
                continue
            item = unwrap_item(result)
            got_id = as_int(pick(item, "id", "ID"))
            if got_id:
                found[got_id] = item

    def get_items_by_ids(
        self,
        entity_type_id: int,
        ids: list[int],
        *,
        select: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
        label: str = "записей CRM",
    ) -> dict[int, dict[str, Any]]:
        unique = [item_id for item_id in dict.fromkeys(ids) if item_id > 0]
        found: dict[int, dict[str, Any]] = {}
        if not unique:
            return found
        fields = select or ["id", "title", "stageId", "companyId"]
        chunk_size = 50
        total = len(unique)
        for offset in range(0, total, chunk_size):
            chunk = unique[offset : offset + chunk_size]
            wanted = set(chunk)
            for key in ID_FILTER_KEYS:
                try:
                    rows = self._list_items_one_page(
                        entity_type_id,
                        select=fields,
                        filt={key: chunk},
                    )
                except BitrixClientError:
                    continue
                matched = 0
                for row in rows:
                    item_id = as_int(pick(row, "id", "ID"))
                    if item_id in wanted:
                        found[item_id] = row
                        matched += 1
                if matched:
                    break
            missing = [item_id for item_id in chunk if item_id not in found]
            if missing:
                self._fetch_missing_items(entity_type_id, missing, found)
            if progress:
                progress(f"Загрузка {label}: {min(offset + len(chunk), total)}/{total}…")
        return found

    def list_deal_stage_names(self) -> dict[str, str]:
        """STATUS_ID / stageId → название стадии сделки."""
        names: dict[str, str] = {}
        try:
            raw = self._call_raw("crm.status.list", {})
        except BitrixClientError:
            return names
        statuses = unwrap_list(raw.get("result", raw), "statuses")
        nxt = coerce_next(raw.get("next"))
        if nxt:
            extra = self.list_all("crm.status.list", {}, "statuses")
            seen_ids = {
                str(pick(row, "STATUS_ID", "statusId", "id", default="") or "")
                for row in statuses
                if isinstance(row, dict)
            }
            for row in extra:
                if not isinstance(row, dict):
                    continue
                status_id = str(pick(row, "STATUS_ID", "statusId", "id", default="") or "")
                if status_id and status_id not in seen_ids:
                    statuses.append(row)
                    seen_ids.add(status_id)

        for row in statuses:
            if not isinstance(row, dict):
                continue
            entity = str(pick(row, "ENTITY_ID", "entityId", default="") or "")
            if entity and not entity.upper().startswith("DEAL"):
                continue
            status_id = str(pick(row, "STATUS_ID", "statusId", "id", default="") or "")
            name = str(pick(row, "NAME", "name", default="") or "")
            if status_id and name:
                names[status_id] = name
                names[status_id.upper()] = name
        return names
