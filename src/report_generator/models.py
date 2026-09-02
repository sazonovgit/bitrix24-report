"""Строка отчёта и описание колонок Excel."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


WON_STAGE_NAME = "Выиграли закупку"
PLAN_LABEL = "План"
FACT_LABEL = "Факт"

COLUMN_HEADERS = {
    "title": "Название",
    "year": "Год",
    "deal_id": "Сделка",
    "company": "Компания",
    "price_po": "ЦЕНА ПО {year}",
    "price_impl": "ЦЕНА ВНЕДРЕНИЯ ({year})",
    "amount": "СУММА ({year})",
    "plan_fact": "План/Факт",
}

COLUMN_LABELS = {
    "title": "Название",
    "year": "Год",
    "deal_id": "Сделка",
    "company": "Компания",
    "price_po": "Цена ПО",
    "price_impl": "Цена внедрения",
    "amount": "Сумма",
    "plan_fact": "План / факт",
}

MONEY_COLUMNS = frozenset({"price_po", "price_impl", "amount"})


@dataclass(frozen=True)
class YearPriceFields:
    price_po: str = ""
    price_impl: str = ""
    amount: str = ""

    def missing(self) -> list[str]:
        gaps: list[str] = []
        if not self.price_po:
            gaps.append("цена по")
        if not self.price_impl:
            gaps.append("цена внедрения")
        if not self.amount:
            gaps.append("сумма")
        return gaps


@dataclass
class ReportRow:
    title: str
    year: int
    deal_id: int | None
    company: str
    price_po: Decimal | None
    price_impl: Decimal | None
    amount: Decimal | None
    plan_fact: str

    def value(self, key: str) -> str | int | Decimal | None:
        return getattr(self, key)


def column_header(key: str, year: int) -> str:
    template = COLUMN_HEADERS[key]
    return template.format(year=year)
