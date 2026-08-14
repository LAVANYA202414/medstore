import os
import models
from dotenv import load_dotenv
from passlib.context import CryptContext
from database import SessionLocal, engine, Base

load_dotenv()

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
Base.metadata.create_all(bind=engine)
db = SessionLocal()

MY_PASSWORD = os.getenv("ADMIN_PASSWORD")
EMAIL = os.getenv("ADMIN_EMAIL")

if not EMAIL or not MY_PASSWORD:
    print("ERROR: .env missing ADMIN_EMAIL / ADMIN_PASSWORD")
    exit(1)

# YOUR IDEA: Check instead of delete
existing = db.query(models.User).filter(models.User.email == EMAIL).first()

if existing:
    print(f" User already exists: {EMAIL}")
    print(f"   is_admin={existing.is_admin}, is_active={existing.is_active}")
    print("   If you want to reset password, delete manually or use update script.")
else:
    hashed = pwd_context.hash(MY_PASSWORD)
    admin = models.User(
        email=EMAIL,
        password_hash=hashed,
        is_admin=True,
        is_active=True
    )
    db.add(admin)
    db.commit()
    print(f" Admin created: {EMAIL}")

db.close()