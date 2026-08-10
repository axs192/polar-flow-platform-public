import json
from pathlib import Path

BASE_DIR = Path("src/data/files")


def load_json(filename: str):
    filepath = BASE_DIR / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Sample file {filename} not found in {BASE_DIR}")

    with open(filepath, encoding="utf-8") as f:
        return json.load(f)
