"""Сбор строк отчёта из модулей и связанных продаж."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from report_generator.bitrix import (
    COMPANY_ENTITY_TYPE_ID,
    DEAL_ENTITY_TYPE_ID,
    BitrixClient,
    as_int,
    pick,
)
from report_generator.mapping import (
    PortalSchema,
    EntityMap,
    effective_price_fields,
    ensure_year_fields,
    normalize_title,
)
from report_generator.models import (
    FACT_LABEL,
    PLAN_LABEL,
    EXCLUDED_DEAL_STAGE_NAME,
    WON_STAGE_NAME,
    ReportRow,
    YearPriceFields,
)


SaleSource = Literal["planned", "actual"]


def parse_money(value: Any) -> Decimal | None:
    if value is None or value is False or value == "":
        return None
    if isinstance(value, dict):
        value = pick(value, "value", "VALUE", "amount", "AMOUNT", default=value)
        if isinstance(value, dict):
            return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip()
    if "|" in text:
        text = text.split("|", 1)[0]
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def crm_id(value: Any) -> int:
    if value in (None, "", False, [], {}):
        return 0
    if isinstance(value, (list, tuple)):
        for item in value:
            found = crm_id(item)
            if found:
                return found
        return 0
    return as_int(value)


def item_value(item: dict[str, Any], field_name: str) -> Any:
    if not field_name:
        return None
    if field_name in item:
        return item[field_name]
    lower = {str(key).casefold(): key for key in item}
    real = lower.get(field_name.casefold())
    if real is not None:
        return item[real]
    return pick(item, field_name)


def parse_year_value(value: Any) -> int | None:
    if value is None or value is False or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = parse_year_value(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        return parse_year_value(pick(value, "value", "VALUE", "id", "ID", default=None))
    if isinstance(value, int):
        return value if 1990 <= value <= 2100 else None
    if isinstance(value, float):
        year = int(value)
        return year if year == value and 1990 <= year <= 2100 else None
    text = str(value).strip()
    match = re.search(r"(20\d{2}|\d{4})", text)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1990 <= year <= 2100 else None


def deal_matches_year(deal: dict[str, Any] | None, year: int, year_field: str) -> bool:
    if not deal:
        return False
    parsed = parse_year_value(item_value(deal, year_field) if year_field else None)
    return parsed == year


def classify_plan_fact(source: SaleSource, deal_stage_name: str | None) -> str:
    if source == "actual":
        return FACT_LABEL
    if deal_stage_name and normalize_title(deal_stage_name) == normalize_title(WON_STAGE_NAME):
        return FACT_LABEL
    return PLAN_LABEL


def _prices_from(item: dict[str, Any] | None, fields: YearPriceFields) -> tuple[
    Decimal | None, Decimal | None, Decimal | None
]:
    if not item:
        return None, None, None
    return (
        parse_money(item_value(item, fields.price_po)) if fields.price_po else None,
        parse_money(item_value(item, fields.price_impl)) if fields.price_impl else None,
        parse_money(item_value(item, fields.amount)) if fields.amount else None,
    )


def coalesce_prices(
    sale: dict[str, Any],
    module: dict[str, Any] | None,
    sale_fields: YearPriceFields,
    module_fields: YearPriceFields,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    sale_po, sale_impl, sale_amount = _prices_from(sale, sale_fields)
    mod_po, mod_impl, mod_amount = _prices_from(module, module_fields)
    return (
        sale_po if sale_po is not None else mod_po,
        sale_impl if sale_impl is not None else mod_impl,
        sale_amount if sale_amount is not None else mod_amount,
    )


def _index_by_id(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        item_id = as_int(pick(row, "id", "ID"))
        if item_id:
            indexed[item_id] = row
    return indexed


def _stage_name(deal: dict[str, Any] | None, stages: dict[str, str]) -> str | None:
    if not deal:
        return None
    stage_id = str(pick(deal, "stageId", "STAGE_ID", default="") or "")
    if not stage_id:
        return None
    return stages.get(stage_id) or stages.get(stage_id.upper()) or stage_id


def deal_stage_excluded(deal: dict[str, Any] | None, stages: dict[str, str]) -> bool:
    stage_name = _stage_name(deal, stages)
    if not stage_name:
        return False
    excluded = normalize_title(EXCLUDED_DEAL_STAGE_NAME)
    return normalize_title(stage_name) == excluded


def sale_to_row(
    *,
    sale: dict[str, Any],
    source: SaleSource,
    year: int,
    entity: EntityMap,
    modules: dict[int, dict[str, Any]],
    companies: dict[int, dict[str, Any]],
    deals: dict[int, dict[str, Any]],
    stages: dict[str, str],
    module_prices: YearPriceFields,
    deal_year_field: str = "",
) -> ReportRow | None:
    module_id = crm_id(item_value(sale, entity.module_field))
    module = modules.get(module_id)
    title = str(pick(module, "title", "TITLE", default="") or pick(sale, "title", "TITLE", default="") or "")
    title = " ".join(title.replace("\r", " ").replace("\n", " ").split())
    if not title:
        return None

    company_id = crm_id(item_value(sale, entity.company_field))
    company = companies.get(company_id)
    company_name = str(
        pick(company, "title", "TITLE", default="")
        or pick(sale, "companyTitle", "COMPANY_TITLE", default="")
        or ""
    )
    company_name = " ".join(company_name.replace("\r", " ").replace("\n", " ").split())
    if not company_name:
        return None

    deal_id = crm_id(item_value(sale, entity.deal_field)) or None
    if not deal_id:
        return None
    deal = deals.get(deal_id)
    if not deal_matches_year(deal, year, deal_year_field):
        return None
    if deal_stage_excluded(deal, stages):
        return None
    plan_fact = classify_plan_fact(source, _stage_name(deal, stages))

    deal_name = str(pick(deal, "title", "TITLE", default="") or "")
    deal_name = " ".join(deal_name.replace("\r", " ").replace("\n", " ").split())
    if not deal_name:
        deal_name = f"Сделка {deal_id}"

    price_po, price_impl, amount = coalesce_prices(
        sale,
        module,
        effective_price_fields(entity, year),
        module_prices,
    )
    return ReportRow(
        title=title,
        year=year,
        deal_id=deal_id,
        deal_name=deal_name,
        company=company_name,
        price_po=price_po,
        price_impl=price_impl,
        amount=amount,
        plan_fact=plan_fact,
    )


def _row_key(row: ReportRow) -> tuple[str, str, int | None]:
    deal = int(row.deal_id) if row.deal_id else None
    return (normalize_title(row.title), normalize_title(row.company), deal)


def dedupe_rows(rows: list[ReportRow]) -> list[ReportRow]:
    """Одна строка на модуль + компанию + сделку; при конфликте оставляем Факт."""
    chosen: dict[tuple[str, str, int | None], ReportRow] = {}
    order: list[tuple[str, str, int | None]] = []
    for row in rows:
        key = _row_key(row)
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = row
            order.append(key)
            continue
        if existing.plan_fact != FACT_LABEL and row.plan_fact == FACT_LABEL:
            chosen[key] = row
    return [chosen[key] for key in order]


def build_rows_from_loaded(
    *,
    year: int,
    schema: PortalSchema,
    modules: dict[int, dict[str, Any]],
    planned: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    companies: dict[int, dict[str, Any]],
    deals: dict[int, dict[str, Any]],
    stages: dict[str, str],
) -> list[ReportRow]:
    rows: list[ReportRow] = []
    module_prices = effective_price_fields(schema.modules, year)
    for sale in actual:
        row = sale_to_row(
            sale=sale,
            source="actual",
            year=year,
            entity=schema.actual,
            modules=modules,
            companies=companies,
            deals=deals,
            stages=stages,
            module_prices=module_prices,
            deal_year_field=schema.deal_year_field,
        )
        if row:
            rows.append(row)
    for sale in planned:
        row = sale_to_row(
            sale=sale,
            source="planned",
            year=year,
            entity=schema.planned,
            modules=modules,
            companies=companies,
            deals=deals,
            stages=stages,
            module_prices=module_prices,
            deal_year_field=schema.deal_year_field,
        )
        if row:
            rows.append(row)
    rows = dedupe_rows(rows)
    rows.sort(key=lambda item: (item.title.casefold(), item.company.casefold(), item.plan_fact))
    return rows


def collect_related_ids(
    sales: list[dict[str, Any]],
    entity: EntityMap,
) -> tuple[list[int], list[int], list[int]]:
    modules: list[int] = []
    companies: list[int] = []
    deals: list[int] = []
    for sale in sales:
        module_id = crm_id(item_value(sale, entity.module_field))
        company_id = crm_id(item_value(sale, entity.company_field))
        deal_id = crm_id(item_value(sale, entity.deal_field))
        if module_id:
            modules.append(module_id)
        if company_id:
            companies.append(company_id)
        if deal_id:
            deals.append(deal_id)
    return modules, companies, deals


def build_report(
    client: BitrixClient,
    schema: PortalSchema,
    year: int,
    progress: Callable[[str], None] | None = None,
) -> list[ReportRow]:
    ensure_year_fields(schema, year)

    def notify(message: str) -> None:
        if progress:
            progress(message)

    notify("Загрузка модулей…")
    modules = _index_by_id(client.list_items(schema.modules.entity_type_id)) if schema.modules.entity_type_id else {}

    planned: list[dict[str, Any]] = []
    actual: list[dict[str, Any]] = []
    if schema.actual.entity_type_id:
        notify("Загрузка фактических продаж…")
        actual = client.list_items(schema.actual.entity_type_id)
    if schema.planned.entity_type_id:
        notify("Загрузка планируемых продаж…")
        planned = client.list_items(schema.planned.entity_type_id)

    module_ids, company_ids, deal_ids = [], [], []
    for sales, entity in ((actual, schema.actual), (planned, schema.planned)):
        m_ids, c_ids, d_ids = collect_related_ids(sales, entity)
        module_ids.extend(m_ids)
        company_ids.extend(c_ids)
        deal_ids.extend(d_ids)

    missing_modules = [item_id for item_id in dict.fromkeys(module_ids) if item_id not in modules]
    if missing_modules and schema.modules.entity_type_id:
        notify("Догрузка карточек модулей…")
        modules.update(
            client.get_items_by_ids(
                schema.modules.entity_type_id,
                missing_modules,
                select=["*", "id", "title"],
            )
        )

    notify("Загрузка компаний…")
    companies = client.get_items_by_ids(
        COMPANY_ENTITY_TYPE_ID,
        company_ids,
        select=["id", "title"],
        progress=notify,
        label="компаний",
    )
    notify("Загрузка сделок…")
    deal_select = ["id", "title", "stageId", "companyId"]
    if schema.deal_year_field:
        deal_select.append(schema.deal_year_field)
    deals = client.get_items_by_ids(
        DEAL_ENTITY_TYPE_ID,
        deal_ids,
        select=deal_select,
        progress=notify,
        label="сделок",
    )
    notify("Загрузка стадий сделок…")
    stages = client.list_deal_stage_names()

    notify("Сборка строк отчёта…")
    return build_rows_from_loaded(
        year=year,
        schema=schema,
        modules=modules,
        planned=planned,
        actual=actual,
        companies=companies,
        deals=deals,
        stages=stages,
    )
