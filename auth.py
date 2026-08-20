import os
import jwt
import models
from database import get_db
from pydantic import EmailStr
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

# Setup and Settings:
router = APIRouter(prefix="/api", tags=["auth"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key_change_me")
ALGORITHM = "HS256"
security = HTTPBearer()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class UserUpdateByAdmin(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    is_admin: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_active: bool
    is_verified: bool
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# --- SIGNUP FOR USERS ---
@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = pwd_context.hash(payload.password)
    new_user = models.User(
        email=payload.email,
        password_hash=hashed,
        is_admin=False,
        is_active=True,
        is_verified=True # default true as you asked
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully", "user_id": new_user.id, "email": new_user.email, "is_verified": new_user.is_verified}


# --- USER LOGIN ---
@router.post("/user/login")
def user_login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="incorrect email")
    if not pwd_context.verify(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="incorrect password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="user not verified error")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified by admin")

    payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=10)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "is_admin": user.is_admin, "email": user.email}


# --- ADMIN LOGIN ---
@router.post("/admin/login")
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()

    if not user or not pwd_context.verify(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="not admin")

    # Create token
    payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    # Give the pass to the user:
    return {"access_token": token, "token_type": "bearer", "is_admin": user.is_admin}


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


# --- USERS LIST ---
@router.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), admin = Depends(get_current_admin)):
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    return users


# --- ADMIN: Update user ---
@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdateByAdmin, db: Session = Depends(get_db), admin = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        # check duplicate email
        exists = db.query(models.User).filter(models.User.email == data["email"], models.User.id!= user_id).first()
        if exists:
            raise HTTPException(status_code=400, detail="Email already in use")

    for key, value in data.items():
        setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return {"message": "User updated", "user": {"id": user.id, "email": user.email, "is_verified": user.is_verified, "is_active": user.is_active, "is_admin": user.is_admin}}