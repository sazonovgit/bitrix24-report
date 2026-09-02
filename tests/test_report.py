from decimal import Decimal

from report_generator.mapping import EntityMap, PortalSchema, match_year_fields
from report_generator.models import FACT_LABEL, PLAN_LABEL, ReportRow
from report_generator.report import (
    build_rows_from_loaded,
    classify_plan_fact,
    dedupe_rows,
    parse_money,
)
from tests.conftest import load_json


def _schema() -> PortalSchema:
    planned_fields = load_json("fields_planned.json")["fields"]
    module_fields = load_json("fields_modules.json")["fields"]
    planned = EntityMap(
        entity_type_id=140,
        title="Планируемые продажи",
        module_field="parentId128",
        deal_field="parentId2",
        company_field="companyId",
    )
    planned.set_prices(2026, match_year_fields(planned_fields, 2026))
    actual = EntityMap(
        entity_type_id=142,
        title="Фактические продажи",
        module_field="parentId128",
        deal_field="parentId2",
        company_field="companyId",
    )
    actual.set_prices(2026, match_year_fields(planned_fields, 2026))
    modules = EntityMap(entity_type_id=128, title="Модули")
    modules.set_prices(2026, match_year_fields(module_fields, 2026))
    return PortalSchema(
        modules=modules,
        planned=planned,
        actual=actual,
        deal_year_field="year",
    )


def _loaded():
    data = load_json("portal.json")
    companies = {int(key): value for key, value in data["companies"].items()}
    deals = {int(key): value for key, value in data["deals"].items()}
    modules = {row["id"]: row for row in data["modules"]}
    return data, modules, companies, deals


def test_classify_plan_fact():
    assert classify_plan_fact("actual", None) == FACT_LABEL
    assert classify_plan_fact("actual", "В работе") == FACT_LABEL
    assert classify_plan_fact("planned", "В работе") == PLAN_LABEL
    assert classify_plan_fact("planned", "Выиграли закупку") == FACT_LABEL
    assert classify_plan_fact("planned", "выиграли  закупку") == FACT_LABEL


def test_parse_money_variants():
    assert parse_money("1 400 000|RUB") == Decimal("1400000")
    assert parse_money({"value": "450000"}) == Decimal("450000")
    assert parse_money("") is None
    assert parse_money(0) == Decimal("0")


def test_build_rows_plan_fact_and_prices():
    data, modules, companies, deals = _loaded()
    rows = build_rows_from_loaded(
        year=2026,
        schema=_schema(),
        modules=modules,
        planned=data["planned"],
        actual=data["actual"],
        companies=companies,
        deals=deals,
        stages=data["stages"],
    )
    by_company = {row.company: row for row in rows}
    assert "План без компании" not in {row.title for row in rows}
    assert len(rows) == 3
    assert all(row.deal_id for row in rows)

    komi = by_company["Республика Коми"]
    assert komi.plan_fact == PLAN_LABEL
    assert komi.deal_id == 805
    assert komi.price_po == Decimal("4000000")
    assert komi.amount == Decimal("4450000")

    khab = by_company["Хабаровский край"]
    assert khab.plan_fact == FACT_LABEL
    assert khab.deal_id == 950
    assert khab.title.startswith("Модуль \"API")
    assert khab.price_po == Decimal("1400000")
    assert khab.price_impl is None
    assert khab.amount == Decimal("1400000")

    kurgan = by_company["Курганская область"]
    assert kurgan.plan_fact == FACT_LABEL
    assert kurgan.deal_id == 479
    assert "Амурская область" not in by_company


def test_dedupe_prefers_fact_for_same_deal():
    fact = ReportRow(
        title='Модуль "Витрина данных ГИСОГД"',
        year=2026,
        deal_id=139,
        company="Архангельская область",
        price_po=Decimal("3000000"),
        price_impl=Decimal("450000"),
        amount=Decimal("3450000"),
        plan_fact=FACT_LABEL,
    )
    plan = ReportRow(
        title='Модуль "Витрина данных ГИСОГД"',
        year=2026,
        deal_id=139,
        company="Архангельская область",
        price_po=Decimal("3000000"),
        price_impl=Decimal("450000"),
        amount=Decimal("3450000"),
        plan_fact=PLAN_LABEL,
    )
    other = ReportRow(
        title='Модуль "Витрина данных ГИСОГД"',
        year=2026,
        deal_id=148,
        company="Хабаровский край",
        price_po=Decimal("3000000"),
        price_impl=Decimal("450000"),
        amount=Decimal("3450000"),
        plan_fact=FACT_LABEL,
    )
    rows = dedupe_rows([plan, fact, other, fact])
    with_139 = [row for row in rows if row.deal_id == 139]
    assert len(with_139) == 1
    assert with_139[0].plan_fact == FACT_LABEL
    assert len(rows) == 2


def test_dedupe_collapses_identical_fact_rows():
    row = ReportRow(
        title='Модуль "Реестровые записи"',
        year=2026,
        deal_id=130,
        company="ЯНАО",
        price_po=Decimal("10600000"),
        price_impl=Decimal("1800000"),
        amount=Decimal("12400000"),
        plan_fact=FACT_LABEL,
    )
    copy = ReportRow(
        title='Модуль «Реестровые записи»\n',
        year=2026,
        deal_id=130,
        company="ЯНАО",
        price_po=Decimal("10600000"),
        price_impl=Decimal("1800000"),
        amount=Decimal("12400000"),
        plan_fact=FACT_LABEL,
    )
    rows = dedupe_rows([row, copy])
    assert len(rows) == 1
    assert rows[0].deal_id == 130


def test_same_deal_on_both_tabs_is_one_row():
    data, modules, companies, deals = _loaded()
    planned = list(data["planned"]) + [
        {
            "id": 99,
            "title": "Дубль плана",
            "parentId128": 1,
            "parentId2": 479,
            "companyId": 22,
            "ufCrm9PricePo2026": "3000000",
            "ufCrm9PriceImpl2026": "450000",
            "ufCrm9Amount2026": "3450000",
        }
    ]
    rows = build_rows_from_loaded(
        year=2026,
        schema=_schema(),
        modules=modules,
        planned=planned,
        actual=data["actual"],
        companies=companies,
        deals=deals,
        stages=data["stages"],
    )
    with_479 = [row for row in rows if row.deal_id == 479]
    assert len(with_479) == 1
    assert with_479[0].plan_fact == FACT_LABEL
    assert with_479[0].company == "Курганская область"


def test_parse_year_value():
    from report_generator.report import parse_year_value

    assert parse_year_value(2026) == 2026
    assert parse_year_value(2026.0) == 2026
    assert parse_year_value("2026") == 2026
    assert parse_year_value("2025-03-01T00:00:00") == 2025
    assert parse_year_value("") is None


def test_only_deals_of_selected_year():
    data, modules, companies, deals = _loaded()
    deals[805]["year"] = 2025
    rows = build_rows_from_loaded(
        year=2026,
        schema=_schema(),
        modules=modules,
        planned=data["planned"],
        actual=data["actual"],
        companies=companies,
        deals=deals,
        stages=data["stages"],
    )
    assert 805 not in {row.deal_id for row in rows}
    assert {row.deal_id for row in rows} == {950, 479}
