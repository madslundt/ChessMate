#!/usr/bin/env python3
"""Provision or reset an authenticated profile locally; passwords never enter argv."""
import argparse
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete, func, select
from src.backend.database import SessionLocal
from src.backend.models import AuthSession, User
from src.backend.profile_security import password_hash
from src.backend.schemas import Preferences


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Existing profile name, or new name with --create")
    parser.add_argument("--create", action="store_true", help="Create a profile if the name is absent")
    args = parser.parse_args()
    name = args.name.strip()
    if not 1 <= len(name) <= 40: parser.error("Name must be 1–40 characters")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.name) == name.casefold()))
        if user is None and not args.create: parser.error("No profile found; use --create for a new profile")
        password = getpass("New password (12–256 characters): ")
        if password != getpass("Repeat password: "): parser.error("Passwords do not match")
        encoded = password_hash(password)
        if user is None:
            user = User(name=name, preferences=Preferences().model_dump())
            db.add(user)
            db.flush()
        user.password_hash = encoded
        db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        db.commit()
    print("Password saved; previous sessions revoked. Enable SECURE_DEPLOYMENT and use HTTPS for untrusted networks.")


if __name__ == "__main__": main()
