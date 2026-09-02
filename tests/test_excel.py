from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from report_generator.excel import write_report
from report_generator.models import ReportRow


def _row(**kwargs) -> ReportRow:
    data = dict(
        title='Модуль "Витрина данных ГИСОГД"',
        year=2026,
        deal_id=479,
        company="Курганская область",
        price_po=Decimal("3000000"),
        price_impl=Decimal("450000"),
        amount=Decimal("3450000"),
        plan_fact="Факт",
    )
    data.update(kwargs)
    return ReportRow(**data)


def test_write_report_headers_and_numbers(tmp_path: Path):
    path = write_report(
        tmp_path / "report.xlsx",
        [
            _row(),
            _row(
                company="Омская область",
                deal_id=None,
                plan_fact="План",
                price_impl=None,
            ),
        ],
        year=2026,
    )
    sheet = load_workbook(path).active
    headers = [cell.value for cell in sheet[1]]
    assert headers == [
        "Название",
        "Год",
        "Сделка",
        "Компания",
        "ЦЕНА ПО 2026",
        "ЦЕНА ВНЕДРЕНИЯ (2026)",
        "СУММА (2026)",
        "План/Факт",
    ]
    assert sheet["C2"].value == 479
    assert sheet["C3"].value is None
    assert sheet["E2"].value == 3000000
    assert sheet["H2"].value == "Факт"
    assert sheet["H3"].value == "План"


def test_write_report_selected_columns(tmp_path: Path):
    path = write_report(
        tmp_path / "subset.xlsx",
        [_row()],
        year=2025,
        columns=["title", "year", "amount", "plan_fact"],
    )
    sheet = load_workbook(path).active
    assert [cell.value for cell in sheet[1]] == [
        "Название",
        "Год",
        "СУММА (2025)",
        "План/Факт",
    ]
    assert sheet["C2"].value == 3450000
