from report_generator.bitrix import (
    BitrixClient,
    COMPANY_ENTITY_TYPE_ID,
    coerce_next,
    deal_details_url,
)


def test_deal_details_url():
    assert deal_details_url("portal.bitrix24.ru", 479) == (
        "https://portal.bitrix24.ru/crm/deal/details/479/"
    )
    assert deal_details_url("", 1) == ""


def test_coerce_next():
    assert coerce_next(None) is None
    assert coerce_next(0) is None
    assert coerce_next(False) is None
    assert coerce_next("50") == 50
    assert coerce_next(50) == 50


def test_list_all_stops_when_page_repeats():
    calls: list[int] = []

    def handler(method, params):
        calls.append(int((params or {}).get("start") or 0))
        items = [{"id": index, "ENTITY_ID": "DEAL_STAGE", "STATUS_ID": f"S{index}", "NAME": "x"} for index in range(80)]
        return {"result": items}

    client = BitrixClient.for_tests(handler)
    rows = client.list_all("crm.status.list", {}, "statuses")
    assert len(rows) == 80
    assert len(calls) <= 2


def test_list_all_follows_next():
    def handler(method, params):
        start = int((params or {}).get("start") or 0)
        if start == 0:
            return {
                "result": {"items": [{"id": i} for i in range(1, 51)]},
                "next": 50,
            }
        if start == 50:
            return {"result": {"items": [{"id": i} for i in range(51, 61)]}}
        raise AssertionError(f"unexpected start {start}")

    client = BitrixClient.for_tests(handler)
    rows = client.list_all("crm.item.list", {}, "items")
    assert [row["id"] for row in rows] == list(range(1, 61))


def test_list_items_drops_overlap_ids():
    def handler(method, params):
        start = int((params or {}).get("start") or 0)
        if start == 0:
            return {
                "result": {"items": [{"id": i} for i in range(1, 51)]},
                "next": 49,
            }
        if start == 49:
            return {"result": {"items": [{"id": i} for i in range(49, 61)]}}
        raise AssertionError(f"unexpected start {start}")

    client = BitrixClient.for_tests(handler)
    rows = client.list_items(1040)
    ids = [row["id"] for row in rows]
    assert ids == list(range(1, 61))
    assert len(ids) == len(set(ids))


def test_get_items_by_ids_does_not_dump_catalog():
    calls: list[tuple[str, dict]] = []

    def handler(method, params):
        params = params or {}
        calls.append((method, params))
        if method == "crm.item.list":
            return {"result": {"items": [{"id": i, "title": f"C{i}"} for i in range(1, 51)]}}
        if method == "batch":
            return {
                "result": {
                    "e0": {"item": {"id": 100, "title": "Нужная"}},
                    "e1": {"item": {"id": 101, "title": "Ещё"}},
                }
            }
        raise AssertionError(method)

    client = BitrixClient.for_tests(handler)
    found = client.get_items_by_ids(COMPANY_ENTITY_TYPE_ID, [100, 101], select=["id", "title"])
    assert found[100]["title"] == "Нужная"
    assert found[101]["title"] == "Ещё"
    list_calls = [item for item in calls if item[0] == "crm.item.list"]
    assert len(list_calls) <= 3
    assert not any(item[0] == "crm.item.get" for item in calls)


def test_list_deal_stage_names_single_call_without_next():
    calls: list[str] = []

    def handler(method, params):
        calls.append(method)
        items = [
            {"ENTITY_ID": "DEAL_STAGE", "STATUS_ID": "WON_CUSTOM", "NAME": "Выиграли закупку"},
            {"ENTITY_ID": "STATUS", "STATUS_ID": "NEW", "NAME": "Другое"},
        ] + [
            {"ENTITY_ID": "DEAL_STAGE", "STATUS_ID": f"S{i}", "NAME": f"Стадия {i}"}
            for i in range(70)
        ]
        return {"result": items}

    client = BitrixClient.for_tests(handler)
    names = client.list_deal_stage_names()
    assert names["WON_CUSTOM"] == "Выиграли закупку"
    assert calls.count("crm.status.list") == 1
