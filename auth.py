import os
import jwt
import models
from database import get_db
from dotenv import load_dotenv
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

@router.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    # Check the password:
    if not user or not pwd_context.verify(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Check if account is active:
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")

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