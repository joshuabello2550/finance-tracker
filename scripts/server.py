"""FastAPI server for finance tracker."""

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from scripts.helper import parse_csv_content
from scripts.import_transactions import process_all_transactions
import os

load_dotenv()

app = FastAPI(root_path="/api")

origins = []

if os.getenv("ENV") == "development":
    origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"Python": "on Vercel"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/import")
async def import_transactions_endpoint(file: UploadFile):
    """Import transactions from uploaded CSV."""
    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(400, "File must be a CSV")

    try:
        content = (await file.read()).decode('utf-8')
        transactions = parse_csv_content(content)
        return process_all_transactions(transactions)

    except Exception as e:
        raise HTTPException(500, str(e))
