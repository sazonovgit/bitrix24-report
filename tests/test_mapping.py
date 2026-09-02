from report_generator.bitrix import BitrixClientError, parse_webhook_url
from report_generator.mapping import (
    EntityMap,
    find_type,
    match_deal_year_field,
    match_year_fields,
    normalize_title,
    relation_fields,
)
from tests.conftest import load_json


def test_parse_webhook_url():
    domain, token = parse_webhook_url("https://portal.bitrix24.ru/rest/1/secretcode/")
    assert domain == "portal.bitrix24.ru"
    assert token == "1/secretcode"


def test_parse_webhook_rejects_empty():
    try:
        parse_webhook_url(" ")
    except BitrixClientError as exc:
        assert "вебхук" in str(exc).casefold()
    else:
        raise AssertionError("expected BitrixClientError")


def test_normalize_and_year_fields():
    fields = load_json("fields_modules.json")["fields"]
    prices = match_year_fields(fields, 2026)
    assert prices.price_po == "ufCrm7PricePo2026"
    assert prices.price_impl == "ufCrm7PriceImpl2026"
    assert prices.amount == "ufCrm7Amount2026"

    prices_2025 = match_year_fields(fields, 2025)
    assert prices_2025.price_po == "ufCrm7PricePo2025"
    assert prices_2025.amount == "ufCrm7Amount2025"


def test_match_deal_year_field_prefers_deal_uf():
    field = match_deal_year_field(
        {
            "ufCrm8_1": {"type": "string", "title": "Год"},
            "ufCrm_1766154539253": {"type": "double", "title": "Год"},
            "begindate": {"type": "date", "title": "Дата начала"},
        }
    )
    assert field == "ufCrm_1766154539253"


def test_find_type_exact_modules():
    types = load_json("types.json")["types"]
    row = find_type(types, "модули")
    assert row is not None
    assert row["entityTypeId"] == 128
    planned = find_type(types, "планируемые продажи")
    assert planned["entityTypeId"] == 140


def test_relation_fields():
    fields = load_json("fields_planned.json")["fields"]
    rel = relation_fields(fields, 128)
    assert rel["module"] == "parentId128"
    assert rel["deal"] == "parentId2"
    assert rel["company"] == "companyId"


def test_normalize_title_strips_quotes():
    assert normalize_title("ЦЕНА ВНЕДРЕНИЯ (2026)") == "цена внедрения 2026"


def test_entity_map_year_roundtrip():
    entity = EntityMap(entity_type_id=140, title="Планируемые продажи")
    prices = match_year_fields(load_json("fields_planned.json")["fields"], 2026)
    entity.set_prices(2026, prices)
    loaded = entity.prices_for(2026)
    assert loaded.price_po == "ufCrm9PricePo2026"
