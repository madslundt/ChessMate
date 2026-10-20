#!/usr/bin/env python3
"""Import an exercise JSON list only after fresh legal/objective/engine checks.

Format: see src/backend/exercise_library.json. Supply attribution in
`evidence.provenance` for licensed external content. Imports are idempotent.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_exercises import validate_library
from src.backend.database import SessionLocal
from src.backend.training_models import Exercise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--replace", action="store_true", help="Replace existing public exercises with matching IDs")
    args = parser.parse_args()
    validated = validate_library(args.path)
    with SessionLocal() as db:
        for item in validated:
            existing = db.get(Exercise, item["id"])
            if existing:
                if existing.owner_id:
                    raise ValueError("Cannot overwrite a private game-derived exercise")
                if args.replace:
                    existing.data, existing.category = item, item["category"]
            else:
                db.add(Exercise(id=item["id"], category=item["category"], data=item))
        db.commit()
    print(f"Imported {len(validated)} verified exercises.")


if __name__ == "__main__":
    main()
