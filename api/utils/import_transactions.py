from datetime import datetime, timedelta
from googleapiclient.errors import HttpError
import re
import sys
from collections import defaultdict

from .categorize_transactions import fetch_categories, fetch_historical_expenses, categorize
from .helper import format_amount, format_date_short, get_column_range, get_sheets_service, load_csv, parse_date, find_expense_section


SPREADSHEET_ID = "1R-LLdpkVxjewiRD6LNer7sUF_AtJfx1_b6G1VPddc9k"
REFUND_WINDOW_DAYS = 14
SHEET_REFUND_WINDOW_DAYS = 60


def _name_tokens(name: str) -> set[str]:
    """Extract significant lowercase word tokens (≥4 chars) for fuzzy merchant matching."""
    skip = {"corp", "incorporated", "inc", "llc", "ltd", "com", "store", "online", "purchase"}
    return {w for w in re.findall(r"[a-z]{4,}", name.lower()) if w not in skip}


def _days_between(d1: str, d2: str) -> int:
    a = datetime.strptime(d1, "%Y-%m-%d")
    b = datetime.strptime(d2, "%Y-%m-%d")
    return abs((a - b).days)


def pair_refunds(transactions: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Greedy-match each CREDIT to one DEBIT (same merchant family, equal magnitude, ±14 days).

    Returns (kept_debits, refund_pairs, unmatched_credits).
    """
    debits = [t for t in transactions if t['amount'] < 0]
    credits = [t for t in transactions if t['amount'] > 0]

    paired_debits: set[int] = set()
    pairs: list[dict] = []
    unmatched_credits: list[dict] = []

    for credit in credits:
        c_tokens = _name_tokens(credit['name'])
        c_amount = abs(credit['amount'])
        match_idx = None
        for di, debit in enumerate(debits):
            if di in paired_debits:
                continue
            if abs(abs(debit['amount']) - c_amount) > 0.005:
                continue
            if _days_between(credit['date'], debit['date']) > REFUND_WINDOW_DAYS:
                continue
            if c_tokens and not (c_tokens & _name_tokens(debit['name'])):
                continue
            match_idx = di
            break

        if match_idx is None:
            unmatched_credits.append(credit)
        else:
            paired_debits.add(match_idx)
            pairs.append({'debit': debits[match_idx], 'credit': credit})

    kept_debits = [d for i, d in enumerate(debits) if i not in paired_debits]
    return kept_debits, pairs, unmatched_credits


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
                existing.add((row[0], row[1]))

    return existing


def group_transactions_by_year_and_month(transactions: list[dict]) -> dict[int, dict[int, list[dict]]]:
    """Group transactions by year, then by month."""
    by_year_month: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for txn in transactions:
        year, month, _ = parse_date(txn['date'])
        by_year_month[year][month].append(txn)

    return {year: dict(months) for year, months in by_year_month.items()}


def get_sheet_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    """Get the sheet ID for a given sheet name."""
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in spreadsheet['sheets']:
        if sheet['properties']['title'] == sheet_name:
            return sheet['properties']['sheetId']
    raise ValueError(f"Sheet '{sheet_name}' not found")


def rows_to_tsv(rows: list[list]) -> str:
    """Convert 2D array to tab-separated string."""
    return "\n".join("\t".join(str(cell) for cell in row) for row in rows)


def col_letter_to_index(col: str) -> int:
    """Convert column letter(s) to 0-based index."""
    result = 0
    for char in col:
        result = result * 26 + (ord(char.upper()) - ord('A') + 1)
    return result - 1


def paste_rows(service, spreadsheet_id: str, sheet_id: int, start_col: str, row_start: int, rows: list[list]):
    """Paste rows into the sheet at the given coordinate."""
    col_start_index = col_letter_to_index(start_col)
    requests = [{
        "pasteData": {
            "coordinate": {
                "sheetId": sheet_id,
                "rowIndex": row_start,
                "columnIndex": col_start_index,
            },
            "data": rows_to_tsv(rows),
            "type": "PASTE_NORMAL",
            "delimiter": "\t",
        }
    }]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def _match_credits_to_sheet(unmatched_credits: list[dict], existing: set[tuple], sheet_year: int) -> list[dict]:
    """Find unmatched credits whose (amount, ±60d) matches a row already in the sheet."""
    warnings = []
    existing_parsed = []
    for date_str, amount_str in existing:
        try:
            m, d = date_str.split("/")
            existing_parsed.append((datetime(sheet_year, int(m), int(d)), amount_str))
        except (ValueError, AttributeError):
            continue

    for credit in unmatched_credits:
        c_amount_fmt = format_amount(credit['amount'])
        c_date = datetime.strptime(credit['date'], "%Y-%m-%d")
        for ex_date, ex_amount in existing_parsed:
            if ex_amount != c_amount_fmt:
                continue
            if abs((ex_date - c_date).days) > SHEET_REFUND_WINDOW_DAYS:
                continue
            warnings.append({
                'credit_date': credit['date'],
                'credit_name': credit['name'],
                'credit_amount': c_amount_fmt,
                'sheet_date': ex_date.strftime("%-m/%-d"),
                'sheet_amount': ex_amount,
            })
            break
    return warnings


def preview_month(service, spreadsheet_id: str, sheet_name: str, month: int, transactions: list[dict], unmatched_credits: list[dict] | None = None) -> dict | None:
    """Build a preview for a single month without writing to the sheet.

    Returns a dict with target coordinates, classified rows, and the category list,
    or None if the month's Expense section can't be located.
    """
    start_col, end_col = get_column_range(month)
    range_name = f"{sheet_name}!{start_col}:{end_col}"

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_name
        ).execute()
        values = result.get('values', [])
    except HttpError as e:
        print(f"Error reading sheet: {e}")
        return None

    header_row, last_expense_row = find_expense_section(values)
    if header_row is None:
        return None

    existing = get_existing_expenses(values, header_row, last_expense_row)

    transactions = sorted(transactions, key=lambda t: t['date'], reverse=True)

    new_txns = []
    duplicates = []
    for txn in transactions:
        date_short = format_date_short(txn['date'])
        amount_fmt = format_amount(txn['amount'])
        entry = {
            'date_short': date_short,
            'amount_fmt': amount_fmt,
            'raw_name': txn['name'],
        }
        if (date_short, amount_fmt) in existing:
            duplicates.append({**entry, 'status': 'duplicate', 'expense_name': '', 'category': ''})
        else:
            new_txns.append(entry)

    valid_categories = fetch_categories(spreadsheet_id, sheet_name)

    classified_rows = []
    if new_txns:
        historical = fetch_historical_expenses(spreadsheet_id, sheet_name)
        names = [t['raw_name'] for t in new_txns]
        categorized = categorize(names, valid_categories, historical)

        for txn, cat in zip(new_txns, categorized):
            classified_rows.append({
                'date_short': txn['date_short'],
                'amount_fmt': txn['amount_fmt'],
                'raw_name': txn['raw_name'],
                'expense_name': cat['expense_name'],
                'category': cat['category'],
                'status': 'needs_manual' if cat['category'] == 'NEED MANUAL ENTRY' else 'new',
            })

    insert_row = (last_expense_row + 1) if last_expense_row else (header_row + 1)

    sheet_refund_warnings = _match_credits_to_sheet(
        unmatched_credits or [], existing, int(sheet_name)
    ) if unmatched_credits else []

    return {
        'sheet_name': sheet_name,
        'month': month,
        'start_col': start_col,
        'insert_row': insert_row,
        'categories': valid_categories,
        'rows': classified_rows + duplicates,
        'sheet_refund_warnings': sheet_refund_warnings,
    }


def commit_month(service, spreadsheet_id: str, sheet_name: str, start_col: str, insert_row: int, rows: list[dict]) -> int:
    """Write user-approved rows to the sheet. Returns count written."""
    if not rows:
        return 0

    sheet_id = get_sheet_id(service, spreadsheet_id, sheet_name)
    table = [
        [r['date_short'], r['amount_fmt'], r['expense_name'], r['category']]
        for r in rows
    ]
    paste_rows(service, spreadsheet_id, sheet_id, start_col, insert_row, table)
    return len(table)


def preview_all_transactions(transactions: list[dict]) -> dict:
    """Build previews for all months across all years in the CSV."""
    if not transactions:
        return {"previews": [], "refunds_paired": []}

    kept_debits, refund_pairs, unmatched_credits = pair_refunds(transactions)
    by_year_month = group_transactions_by_year_and_month(kept_debits)
    service = get_sheets_service()

    previews = []
    for year in sorted(by_year_month.keys(), reverse=True):
        sheet_name = str(year)
        credits_for_year = [c for c in unmatched_credits if parse_date(c['date'])[0] == year]
        for month in sorted(by_year_month[year].keys(), reverse=True):
            credits_for_month = [
                c for c in credits_for_year if parse_date(c['date'])[1] == month
            ]
            preview = preview_month(
                service, SPREADSHEET_ID, sheet_name, month,
                by_year_month[year][month],
                credits_for_month or None,
            )
            if preview is None:
                previews.append({
                    'sheet_name': sheet_name,
                    'month': month,
                    'error': f"Could not locate Expense section in sheet '{sheet_name}' for month {month}",
                    'rows': [],
                    'sheet_refund_warnings': [],
                })
            else:
                previews.append(preview)

    return {
        "previews": previews,
        "refunds_paired": [
            {
                'debit_date': p['debit']['date'],
                'debit_name': p['debit']['name'],
                'credit_date': p['credit']['date'],
                'credit_name': p['credit']['name'],
                'amount': format_amount(p['debit']['amount']),
            }
            for p in refund_pairs
        ],
    }


def commit_all_previews(previews: list[dict]) -> dict:
    """Commit user-approved previews to the sheet."""
    service = get_sheets_service()
    results = []
    total = 0

    for preview in previews:
        rows = [r for r in preview.get('rows', []) if r.get('status') in ('new', 'needs_manual')]
        added = commit_month(
            service,
            SPREADSHEET_ID,
            preview['sheet_name'],
            preview['start_col'],
            preview['insert_row'],
            rows,
        )
        results.append({
            'sheet_name': preview['sheet_name'],
            'month': preview['month'],
            'added': added,
        })
        total += added

    return {"total_added": total, "results": results}


def main(csv_path: str):
    """CLI entry point: preview + auto-commit (no manual review)."""
    print(f"Reading CSV: {csv_path}")
    transactions = load_csv(csv_path)
    print(f"Found {len(transactions)} purchase transactions")
    if not transactions:
        return

    preview = preview_all_transactions(transactions)
    result = commit_all_previews(preview["previews"])
    print(f"\n=== Done! Added {result['total_added']} total transactions ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_transactions.py <csv_file_path>")
        sys.exit(1)
    main(sys.argv[1])
