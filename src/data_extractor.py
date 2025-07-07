import csv
import json
import os
import time
from typing import List, Dict, Any

import requests # type: ignore

# Base directory where the project resides (one level above this file)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_URL = "https://apiba.prgapp.kz/CompanyFullInfo?id={}&lang=ru"
INPUT_DIR = os.path.join(BASE_DIR, "parser", "regions")
OUTPUT_DIR = os.path.join(BASE_DIR, "parser", "extracted")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

CSV_HEADERS = [
    "BIN",
    "location",
    "tax_payment_2021",
    "tax_payment_2022",
    "tax_payment_2023",
    "tax_payment_2024",
    "tax_payment_2025",
    "degreeofrisk",
    "executive",
    "phone",
    "email",
]

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataExtractor/1.0; +https://example.com)"
}


def safe_get(dictionary: Dict[str, Any], *keys: str, default: str = "") -> Any:
    """Safely navigate nested dictionaries returning default on KeyError/TypeError."""
    current: Any = dictionary
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current if current not in (None, "null") else default


def extract_company_info(bin_value: str) -> List[Any]:
    """Fetch and parse company info for the given BIN."""
    url = BASE_URL.format(bin_value)
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"[WARN] Failed to fetch or parse data for BIN {bin_value}: {exc}")
        # Return BIN with empty placeholders
        return [bin_value] + ["" for _ in range(len(CSV_HEADERS) - 1)]

    # Location heuristics
    location = (
        safe_get(data, "basicInfo", "legalAddress")
        or safe_get(data, "basicInfo", "factAddress")
        or safe_get(data, "basicInfo", "address")
        or safe_get(data, "address")
    )

    # Tax payments mapping
    tax_graph = safe_get(data, "taxes", "taxGraph", default=[])
    if not isinstance(tax_graph, list):
        tax_graph = []
    taxes_by_year = {entry.get("year"): entry.get("value") for entry in tax_graph if isinstance(entry, dict)}
    tax_2021 = taxes_by_year.get(2021, "")
    tax_2022 = taxes_by_year.get(2022, "")
    tax_2023 = taxes_by_year.get(2023, "")
    tax_2024 = taxes_by_year.get(2024, "")
    tax_2025 = taxes_by_year.get(2025, "")

    degree_of_risk = safe_get(data, "degreeOfRisk", "value")
    executive = safe_get(data, "ceo", "value", "title")

    # Contact information (may vary by structure)
    phone = safe_get(data, "contacts", "phone") or ", ".join(
        safe_get(data, "contacts", "phones", default=[])
    )
    email = safe_get(data, "contacts", "email")

    return [
        bin_value,
        location,
        tax_2021,
        tax_2022,
        tax_2023,
        tax_2024,
        tax_2025,
        degree_of_risk,
        executive,
        phone,
        email,
    ]


def process_csv(input_path: str, output_path: str) -> None:
    """Read BINs from input CSV and write extracted data to output CSV."""
    print(f"[INFO] Processing {os.path.basename(input_path)} → {os.path.basename(output_path)}")
    with open(input_path, newline="", encoding="utf-8") as infile, open(
        output_path, "w", newline="", encoding="utf-8"
    ) as outfile:
        # Attempt to use header if present
        sample_line = infile.readline()
        infile.seek(0)
        has_header = sample_line.lower().startswith("bin")
        reader = csv.reader(infile)
        # Skip header row if it exists
        if has_header:
            next(reader, None)
        writer = csv.writer(outfile)
        writer.writerow(CSV_HEADERS)

        for row in reader:
            if not row:
                continue
            bin_value = row[0].strip().strip("\ufeff")  # Remove BOM if present
            if not bin_value.isdigit():
                continue
            writer.writerow(extract_company_info(bin_value))
            # Gentle rate limiting
            time.sleep(0.3)


def main() -> None:
    csv_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".csv")]
    if not csv_files:
        print(f"[ERROR] No CSV files found in {INPUT_DIR}.")
        return

    for filename in csv_files:
        input_path = os.path.join(INPUT_DIR, filename)
        output_filename = filename.rsplit(".", 1)[0] + "_extracted.csv"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        process_csv(input_path, output_path)

    print("[DONE] Extraction complete. Output CSVs are located in:", OUTPUT_DIR)


if __name__ == "__main__":
    main() 