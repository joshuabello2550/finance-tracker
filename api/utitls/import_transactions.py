from typing import Any


from googleapiclient.errors import HttpError
import sys
from collections import defaultdict

from scripts.categorize_transactions import fetch_categories, fetch_historical_expenses, categorize
from scripts.helper import format_amount, format_date_short, get_column_range, get_sheets_service, load_csv, parse_date


SPREADSHEET_ID = "1R-LLdpkVxjewiRD6LNer7sUF_AtJfx1_b6G1VPddc9k"


def get_year_from_transactions(transactions: list[dict]) -> int:
    """Extract the latest year from transactions."""
    years = set()
    for txn in transactions:
        year, _, _ = parse_date(txn['date'])
        years.add(year)
    return max(years)


def find_expense_section(values: list[list]) -> tuple[int, int]:
    """
    Find the Expense section in the column data.
    Returns (header_row_index, last_expense_row_index).
    """
    expense_header_row = None
    last_expense_row = None

    for i, row in enumerate(values):
        # Look for the Expense header row
        if len(row) >= 3 and row[0] == "Date" and row[2] == "Expense":
            expense_header_row = i
            continue

        # If we found the header, look for expense entries
        if expense_header_row is not None and i > expense_header_row:
            # Check if this row has data (date in first column)
            if len(row) >= 1 and row[0] and row[0] != "Total":
                last_expense_row = i
            # If we hit "Total" or empty section, stop
            elif len(row) >= 1 and row[0] == "Total":
                break

    return expense_header_row, last_expense_row


def get_existing_expenses(values: list[list], header_row: int | None, last_row: int | None) -> set[tuple]:
    """Extract existing expenses for duplicate checking (date, amount)."""
    existing = set()

    if header_row is None:
        return existing

    start = header_row + 1
    end = (last_row + 1) if last_row else start

    for i in range(start, end + 1):
        if i < len(values):
            row = values[i]
            if len(row) >= 2 and row[0] and row[0] != "Total":
                date = row[0]  # Already in M/D format
                amount = row[1]  # Already in $X.XX format
                existing.add((date, amount))

    return existing


def group_transactions_by_year_and_month(transactions: list[dict]) -> dict[int, dict[int, list[dict]]]:
    """Group transactions by year, then by month."""
    by_year_month: dict[int, dict[int, list[dict]]
                        ] = defaultdict(lambda: defaultdict(list))
    for txn in transactions:
        year, month, _ = parse_date(txn['date'])
        by_year_month[year][month].append(txn)

    # Convert to regular dicts
    return {year: dict[int, list[dict]](months) for year, months in by_year_month.items()}


def get_sheet_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    """Get the sheet ID for a given sheet name."""
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id).execute()
    for sheet in spreadsheet['sheets']:
        if sheet['properties']['title'] == sheet_name:
            return sheet['properties']['sheetId']
    raise ValueError(f"Sheet '{sheet_name}' not found")


def rows_to_tsv(rows: list[list]) -> str:
    """Convert 2D array to tab-separated string."""
    return "\n".join("\t".join(str(cell) for cell in row) for row in rows)


def col_letter_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, ..., Z=25, AA=26, etc."""
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1


def paste_rows(
    service, spreadsheet_id: str, sheet_id: int, sheet_name: str,
    start_col: str, row_start: int, rows: list[list], source_validation_cell: str
):
    """Paste data, apply non-bold formatting, and set validation - all in one batch."""
    col_start_index = col_letter_to_index(start_col)

    requests = [
        {
            "pasteData": {
                "coordinate": {
                    "sheetId": sheet_id,
                    "rowIndex": row_start,
                    "columnIndex": col_start_index
                },
                "data": rows_to_tsv(rows),
                "type": "PASTE_NORMAL",
                "delimiter": "\t"
            }
        },
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()


def process_month(service, spreadsheet_id: str, sheet_name: str, month: int, transactions: list[dict], historical_year: int):
    """Process transactions for a single month."""
    start_col, end_col = get_column_range(month)
    range_name = f"{sheet_name}!{start_col}:{end_col}"

    print(f"\nProcessing month {month} (columns {start_col}:{end_col})...")

    # Read current month data
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
    except HttpError as e:
        print(f"Error reading sheet: {e}")
        return 0

    # Find expense section
    header_row, last_expense_row = find_expense_section(values)

    if header_row is None:
        print(f"  Could not find Expense section for month {month}")
        return 0

    print(f"  Found Expense header at row {header_row + 1}")
    if last_expense_row:
        print(f"  Last expense at row {last_expense_row + 1}")

    # Get existing expenses for dedup
    existing = get_existing_expenses(values, header_row, last_expense_row)
    print(f"  Found {len(existing)} existing expenses")

    # Filter duplicates first
    new_transactions = []
    for txn in transactions:
        date_short = format_date_short(txn['date'])
        amount_fmt = format_amount(txn['amount'])
        key = (date_short, amount_fmt)

        if key in existing:
            print(
                f"  Skipping duplicate: {date_short} {amount_fmt} {txn['name'][:30]}")
            continue

        new_transactions.append({
            'date_short': date_short,
            'amount_fmt': amount_fmt,
            'name': txn['name']
        })

    if not new_transactions:
        print(f"  No new transactions to add for month {month}")
        return 0

    # Fetch valid categories from sheet dropdown
    print(f"  Fetching categories from sheet...")
    valid_categories = fetch_categories(spreadsheet_id, sheet_name)
    print(f"  Found {len(valid_categories)} valid categories")

    # Fetch historical expenses for context (try previous year, fall back to current)
    print(f"  Fetching historical expenses from {historical_year}...")
    try:
        historical_expenses = fetch_historical_expenses(
            spreadsheet_id, str(historical_year))
    except Exception:
        print(
            f"  Sheet {historical_year} not found, using current year for historical context")
        historical_expenses = fetch_historical_expenses(
            spreadsheet_id, sheet_name)
    print(f"  Found {len(historical_expenses)} historical expense entries")

    # Categorize all transactions at once using Claude
    print(
        f"  Categorizing {len(new_transactions)} transactions with Claude...")
    transaction_names = [t['name'] for t in new_transactions]
    categorized = categorize(
        transaction_names, valid_categories, historical_expenses)
    print("categorized: ", categorized)

    # Build rows with categorized results
    new_rows = []
    for i, txn in enumerate(new_transactions):
        category = categorized[i]['category']
        expense_name = categorized[i]['expense_name']
        new_rows.append(
            [txn['date_short'], txn['amount_fmt'], expense_name, category])
        print(
            f"  Adding: {txn['date_short']} | {txn['amount_fmt']:>10} | {expense_name[:35]:<35} | {category}")

    # Calculate insert position (after last expense, or after header if no expenses)
    insert_row = (last_expense_row +
                  1) if last_expense_row else (header_row + 1)

    # Get sheet ID and source validation cell
    sheet_id = get_sheet_id(service, spreadsheet_id, sheet_name)
    category_col = chr(ord(start_col[0]) + 3) if len(
        start_col) == 1 else start_col[0] + chr(ord(start_col[1]) + 3)
    source_validation_cell = f"{category_col}{header_row + 2}"

    # Paste data, apply formatting and validation in one batch
    print(f"  Pasting {len(new_rows)} rows at row {insert_row + 1}...")
    paste_rows(
        service, spreadsheet_id, sheet_id, sheet_name,
        start_col, insert_row, new_rows, source_validation_cell
    )

    print(f"  Successfully added {len(new_rows)} transactions")
    return len(new_rows)


def process_all_transactions(transactions: list[dict]) -> dict:
    """Process all transactions, grouping by year and month.

    Returns dict with total_added and results list.
    """
    if not transactions:
        return {"total_added": 0, "results": []}

    by_year_month = group_transactions_by_year_and_month(transactions)
    service = get_sheets_service()

    results = []
    total_added = 0

    for year in sorted(by_year_month.keys()):
        print(f"\n---------------- Processing year {year} ----------------")
        sheet_name = str(year)
        historical_year = year - 1
        months = by_year_month[year]

        for month in sorted(months.keys()):
            added = process_month(
                service, SPREADSHEET_ID, sheet_name, month, months[month], historical_year)
            results.append({"year": year, "month": month, "added": added})
            total_added += added

    return {"total_added": total_added, "results": results}


def main(csv_path: str):
    """Main entry point."""
    print(f"Reading CSV: {csv_path}")

    transactions = load_csv(csv_path)
    print(f"Found {len(transactions)} purchase transactions")

    if not transactions:
        print("No purchase transactions found in CSV")
        return

    result = process_all_transactions(transactions)
    print(f"\n=== Done! Added {result['total_added']} total transactions ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_transactions.py <csv_file_path>")
        sys.exit(1)

    main(sys.argv[1])
