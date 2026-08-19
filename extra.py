import os
import jwt
import models
from database import get_db
from pydantic import EmailStr, BaseModel, Field
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import re

load_dotenv()

router = APIRouter(prefix="/api", tags=["auth"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key_change_me")
ALGORITHM = "HS256"
security = HTTPBearer()

# --- Schemas ---
class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Min 8 chars, 1 uppercase, 1 number")
    confirm_password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# --- SIGNUP API - NEW ---
@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    # 1. Password match
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    # 2. Strong password
    if not re.search(r'[A-Z]', payload.password) or not re.search(r'[0-9]', payload.password):
        raise HTTPException(status_code=400, detail="Password must have 1 uppercase and 1 number")

    # 3. Check duplicate email - USE YOUR DB MODEL
    email_lower = payload.email.lower().strip()
    existing = db.query(models.User).filter(models.User.email == email_lower).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 4. Create user as non-admin
    new_user = models.User(
        email=email_lower,
        password_hash=pwd_context.hash(payload.password),
        is_admin=False,  # normal user
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "Signup successful",
        "user": {"id": new_user.id, "email": new_user.email, "is_admin": new_user.is_admin}
    }

# --- LOGIN API - FIXED TO ALLOW NORMAL USERS ---
@router.post("/login")
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email.lower()).first()
    
    if not user or not pwd_context.verify(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")

    # REMOVED admin-only check from login - admin check should only be in get_current_admin
    # if you want admin-only login, create separate /api/admin/login

    payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer", "is_admin": user.is_admin, "email": user.email}

# --- AUTH HELPERS (same as yours) ---
def get_current_user(credentials:HTTPAuthorizationCredentials = Depends(security), db:Session = Depends(get_db)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms = [ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code = 401, detail = "Invalid Token")
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail = "User not Found")
        if not user.is_active:
            raise HTTPException(status_code = 403, detail = "User deactivated")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code = 401, detail = "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code = 401, detail = "Invalid Token")

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code = 403, detail = "Admin access required")
    return current_user