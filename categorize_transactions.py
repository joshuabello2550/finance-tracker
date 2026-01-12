"""Transaction categorization using Claude with enforced category enums."""

import json

import anthropic
import google.auth
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()


def get_sheets_service():
    """Initialize Google Sheets API service."""
    creds, _ = google.auth.default()
    return build("sheets", "v4", credentials=creds)


def fetch_categories(spreadsheet_id: str, worksheet_name: str) -> list[str]:
    """Fetch valid categories from cell D15's data validation dropdown."""
    service = get_sheets_service()

    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=True,
        ranges=f"{worksheet_name}!D15",
    ).execute()

    sheets = response.get("sheets", [])
    if not sheets:
        raise ValueError("No sheets found")

    grid_data = sheets[0].get("data", [])
    if not grid_data:
        raise ValueError("No grid data found")

    row_data = grid_data[0].get("rowData", [])
    if not row_data:
        raise ValueError("No row data found")

    cell_data = row_data[0].get("values", [])
    if not cell_data:
        raise ValueError("No cell data found")

    data_validation = cell_data[0].get("dataValidation", {})
    condition = data_validation.get("condition", {})

    if condition.get("type") != "ONE_OF_LIST":
        raise ValueError("Cell D15 is not a dropdown")

    values = condition.get("values", [])
    return [v.get("userEnteredValue", "") for v in values]


def categorize(transactions: list[str], valid_categories: list[str]) -> list[dict]:
    """Categorize transactions using Claude with structured outputs."""
    if not transactions:
        return []

    schema = {
        "type": "object",
        "properties": {
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "actual_name": {"type": "string"},
                        "expense_name": {"type": "string"},
                        "category": {"type": "string", "enum": valid_categories},
                    },
                    "required": ["actual_name", "expense_name", "category"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["transactions"],
        "additionalProperties": False,
    }

    prompt = f"""Categorize these transactions.

VALID CATEGORIES (must use exactly one):
{json.dumps(valid_categories)}

TRANSACTIONS:
{json.dumps(transactions)}

Return actual_name (exact original), expense_name (short readable name), and category.

IMPORTANT: If you are unsure about the category for a transaction, use "NEED MANUAL ENTRY" instead of guessing."""

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        betas=["structured-outputs-2025-11-13"],
        messages=[{"role": "user", "content": prompt}],
        output_format={"type": "json_schema", "schema": schema},
    )

    result = json.loads(response.content[0].text)
    return result["transactions"]
