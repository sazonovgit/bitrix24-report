"""Поиск смарт-процессов и полей года по названиям в Битрикс24."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from report_generator.bitrix import (
    COMPANY_ENTITY_TYPE_ID,
    DEAL_ENTITY_TYPE_ID,
    BitrixClient,
    BitrixClientError,
    as_int,
    pick,
)
from report_generator.config import mapping_path
from report_generator.models import YearPriceFields


TYPE_TITLES = {
    "modules": ("модули",),
    "planned": ("планируемые продажи",),
    "actual": ("фактические продажи",),
}


def normalize_title(value: str) -> str:
    text = (value or "").casefold().replace("ё", "е")
    text = re.sub(r"[«»\"'`]+", " ", text)
    text = re.sub(r"[\s_\-–—()\[\].,:;]+", " ", text)
    return " ".join(text.split())


def field_title(spec: Any) -> str:
    if not isinstance(spec, dict):
        return ""
    return str(pick(spec, "title", "formLabel", "listLabel", "label", default="") or "")


def field_type(spec: Any) -> str:
    if not isinstance(spec, dict):
        return ""
    return str(pick(spec, "type", "userTypeId", default="") or "").casefold()


def _year_needles(year: int) -> dict[str, tuple[str, ...]]:
    y = str(year)
    return {
        "price_po": (f"цена по {y}",),
        "price_impl": (f"цена внедрения {y}",),
        "amount": (f"сумма {y}",),
    }


def match_deal_year_field(fields: dict[str, Any]) -> str:
    """Поле сделки «Год»: предпочитаем числовой UF_CRM, не поля смарт-процессов."""
    ranked: list[tuple[int, str]] = []
    for code, spec in fields.items():
        title = normalize_title(field_title(spec) or str(code))
        if title != "год":
            continue
        name = str(code)
        score = 0
        ftype = field_type(spec)
        if ftype in {"double", "integer", "int", "number"}:
            score += 2
        if re.match(r"^(ufCrm|UF_CRM)_\d+$", name):
            score += 3
        if re.match(r"^(ufCrm|UF_CRM)\d+_", name):
            score -= 2
        ranked.append((score, name))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][1]


def match_year_fields(fields: dict[str, Any], year: int) -> YearPriceFields:
    needles = _year_needles(year)
    found: dict[str, str] = {}
    for code, spec in fields.items():
        title = normalize_title(field_title(spec) or str(code))
        if not title:
            continue
        for key, variants in needles.items():
            if key in found:
                continue
            if any(title == variant or title.endswith(variant) for variant in variants):
                found[key] = str(code)
    return YearPriceFields(
        price_po=found.get("price_po", ""),
        price_impl=found.get("price_impl", ""),
        amount=found.get("amount", ""),
    )


def find_type(types: list[dict[str, Any]], *wanted: str) -> dict[str, Any] | None:
    wanted_n = [normalize_title(item) for item in wanted]
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for row in types:
        title = normalize_title(str(pick(row, "title", "TITLE", default="") or ""))
        if not title:
            continue
        if title in wanted_n:
            exact.append(row)
        elif any(item in title for item in wanted_n):
            partial.append(row)
    pool = exact or partial
    if not pool:
        return None
    pool.sort(key=lambda row: as_int(pick(row, "id", "ID")))
    return pool[0]


def _entity_type_id(row: dict[str, Any] | None) -> int:
    if not row:
        return 0
    return as_int(pick(row, "entityTypeId", "entityTypeID", "ENTITY_TYPE_ID"))


def _pick_relation_field(
    fields: dict[str, Any],
    *,
    preferred_names: tuple[str, ...],
    title_needles: tuple[str, ...],
    type_needles: tuple[str, ...],
) -> str:
    by_name = {normalize_title(name): name for name in fields}
    for preferred in preferred_names:
        if preferred in fields:
            return preferred
        key = normalize_title(preferred)
        if key in by_name:
            return by_name[key]

    for code, spec in fields.items():
        ftype = field_type(spec)
        title = normalize_title(field_title(spec) or code)
        if any(needle in ftype for needle in type_needles):
            if not title_needles or any(needle in title for needle in title_needles):
                return str(code)
        if any(needle in title for needle in title_needles):
            return str(code)
    return ""


def relation_fields(fields: dict[str, Any], modules_entity_type_id: int) -> dict[str, str]:
    module_parent = f"parentId{modules_entity_type_id}" if modules_entity_type_id else ""
    return {
        "module": _pick_relation_field(
            fields,
            preferred_names=(module_parent, f"parentid{modules_entity_type_id}"),
            title_needles=("модул",),
            type_needles=("crm",),
        ),
        "deal": _pick_relation_field(
            fields,
            preferred_names=(f"parentId{DEAL_ENTITY_TYPE_ID}", "parentId2"),
            title_needles=("сделк",),
            type_needles=("crm_deal", "deal"),
        ),
        "company": _pick_relation_field(
            fields,
            preferred_names=(
                "companyId",
                f"parentId{COMPANY_ENTITY_TYPE_ID}",
                "parentId4",
            ),
            title_needles=("компани", "клиент"),
            type_needles=("crm_company", "company"),
        ),
    }


@dataclass
class EntityMap:
    entity_type_id: int = 0
    title: str = ""
    module_field: str = ""
    deal_field: str = ""
    company_field: str = ""
    year_fields: dict[str, dict[str, str]] = field(default_factory=dict)

    def prices_for(self, year: int) -> YearPriceFields:
        packed = self.year_fields.get(str(year), {})
        return YearPriceFields(
            price_po=packed.get("price_po", ""),
            price_impl=packed.get("price_impl", ""),
            amount=packed.get("amount", ""),
        )

    def set_prices(self, year: int, prices: YearPriceFields) -> None:
        self.year_fields[str(year)] = {
            "price_po": prices.price_po,
            "price_impl": prices.price_impl,
            "amount": prices.amount,
        }


@dataclass
class PortalSchema:
    modules: EntityMap = field(default_factory=EntityMap)
    planned: EntityMap = field(default_factory=EntityMap)
    actual: EntityMap = field(default_factory=EntityMap)
    deal_year_field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PortalSchema:
        if not data:
            return cls()

        def load(key: str) -> EntityMap:
            raw = data.get(key) or {}
            if not isinstance(raw, dict):
                return EntityMap()
            years = raw.get("year_fields") or {}
            if not isinstance(years, dict):
                years = {}
            return EntityMap(
                entity_type_id=as_int(raw.get("entity_type_id")),
                title=str(raw.get("title") or ""),
                module_field=str(raw.get("module_field") or ""),
                deal_field=str(raw.get("deal_field") or ""),
                company_field=str(raw.get("company_field") or ""),
                year_fields={
                    str(year): {
                        "price_po": str((values or {}).get("price_po") or ""),
                        "price_impl": str((values or {}).get("price_impl") or ""),
                        "amount": str((values or {}).get("amount") or ""),
                    }
                    for year, values in years.items()
                    if isinstance(values, dict)
                },
            )

        return cls(
            modules=load("modules"),
            planned=load("planned"),
            actual=load("actual"),
            deal_year_field=str(data.get("deal_year_field") or ""),
        )


def load_cached_schema() -> PortalSchema | None:
    path = mapping_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    schema = PortalSchema.from_dict(data)
    if schema.modules.entity_type_id:
        return schema
    return None


def save_schema(schema: PortalSchema) -> None:
    path = mapping_path()
    path.write_text(
        json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _fill_entity(
    client: BitrixClient,
    types: list[dict[str, Any]],
    role: str,
    modules_entity_type_id: int,
    year: int,
) -> EntityMap:
    row = find_type(types, *TYPE_TITLES[role])
    if not row:
        if role == "modules":
            raise BitrixClientError(
                "В Битрикс24 не найден смарт-процесс «Модули». "
                "Проверьте название типа или права вебхука."
            )
        return EntityMap()

    entity_type_id = _entity_type_id(row)
    if not entity_type_id:
        return EntityMap()

    fields = client.item_fields(entity_type_id)
    relations = relation_fields(fields, modules_entity_type_id or entity_type_id)
    prices = match_year_fields(fields, year)
    entity = EntityMap(
        entity_type_id=entity_type_id,
        title=str(pick(row, "title", "TITLE", default="") or ""),
        module_field=relations["module"],
        deal_field=relations["deal"],
        company_field=relations["company"],
    )
    entity.set_prices(year, prices)
    return entity


def discover_schema(client: BitrixClient, year: int, *, force: bool = False) -> PortalSchema:
    cached = None if force else load_cached_schema()
    types: list[dict[str, Any]] | None = None

    def types_list() -> list[dict[str, Any]]:
        nonlocal types
        if types is None:
            types = client.list_types()
        return types

    if cached is None:
        schema = PortalSchema()
        schema.modules = _fill_entity(client, types_list(), "modules", 0, year)
        schema.planned = _fill_entity(
            client, types_list(), "planned", schema.modules.entity_type_id, year
        )
        schema.actual = _fill_entity(
            client, types_list(), "actual", schema.modules.entity_type_id, year
        )
    else:
        schema = cached
        for entity in (schema.modules, schema.planned, schema.actual):
            if not entity.entity_type_id:
                continue
            if entity.prices_for(year).price_po and entity.prices_for(year).amount:
                continue
            fields = client.item_fields(entity.entity_type_id)
            if not entity.module_field or not entity.company_field:
                relations = relation_fields(fields, schema.modules.entity_type_id)
                entity.module_field = entity.module_field or relations["module"]
                entity.deal_field = entity.deal_field or relations["deal"]
                entity.company_field = entity.company_field or relations["company"]
            entity.set_prices(year, match_year_fields(fields, year))

    if not schema.planned.entity_type_id and not schema.actual.entity_type_id:
        raise BitrixClientError(
            "Не найдены смарт-процессы «Планируемые продажи» и «Фактические продажи». "
            "Нажмите «Обновить схему полей» или проверьте названия в Битрикс24."
        )

    if force or not schema.deal_year_field:
        deal_fields = client.item_fields(DEAL_ENTITY_TYPE_ID)
        schema.deal_year_field = match_deal_year_field(deal_fields)

    save_schema(schema)
    return schema


def ensure_year_fields(schema: PortalSchema, year: int) -> None:
    sources: list[str] = []
    for entity in (schema.planned, schema.actual, schema.modules):
        if not entity.entity_type_id:
            continue
        missing = entity.prices_for(year).missing()
        if len(missing) < 3:
            return
        sources.append(entity.title or str(entity.entity_type_id))
    raise BitrixClientError(
        f"Не найдены поля цен за {year} год "
        f"(цена по, цена внедрения, сумма) в: {', '.join(sources) or 'смарт-процессах'}. "
        "Нажмите «Обновить схему полей» в настройках."
    )
