import os
import re
import jwt
import models
from database import get_db
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

router = APIRouter(prefix="/api", tags=["users"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key_change_me")
ALGORITHM = "HS256"
security = HTTPBearer()

# --- Schemas ---
class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

# --- 1. USER SIGNUP - Normal users (not admin) ---
@router.post("/user/signup", status_code=201)
@router.post("/signup", status_code=201)  # alias so both work
def user_signup(payload: UserSignupRequest, db: Session = Depends(get_db)):
    # Check password match
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Strong password: 1 uppercase, 1 number
    if not re.search(r'[A-Z]', payload.password) or not re.search(r'[0-9]', payload.password):
        raise HTTPException(status_code=400, detail="Password must contain at least 1 uppercase letter and 1 number")

    email_lower = payload.email.lower().strip()
    
    # Check duplicate
    existing = db.query(models.User).filter(models.User.email == email_lower).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create as normal user
    new_user = models.User(
        email=email_lower,
        password_hash=pwd_context.hash(payload.password),
        is_admin=False,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Create token directly after signup
    token_payload = {
        "user_id": new_user.id,
        "is_admin": False,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "message": "User signup successful",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "is_admin": new_user.is_admin
        },
        "access_token": token,
        "token_type": "bearer"
    }

# --- 2. USER LOGIN - Normal users ---
@router.post("/user/login")
def user_login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    email_lower = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")

    if user.is_admin:
        raise HTTPException(status_code=403, detail="This is user login. Please use /api/admin/login for admin")

    token_payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "message": "User login successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "is_admin": user.is_admin
        }
    }

# --- 3. ADMIN LOGIN (kept separate) ---
@router.post("/admin/login")
def admin_login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    email_lower = payload.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email_lower).first()

    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")

    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    token_payload = {
        "user_id": user.id,
        "is_admin": True,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "message": "Admin login successful",
        "access_token": token,
        "token_type": "bearer",
        "is_admin": True
    }

# --- 4. GET CURRENT USER PROFILE ---
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid Token")
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User deactivated")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid Token")

def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# --- 5. ME endpoint to test token ---
@router.get("/user/me")
def get_user_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_admin": current_user.is_admin,
        "is_active": current_user.is_active
    }

@router.get("/admin/me")
def get_admin_me(current_user: models.User = Depends(get_current_admin)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_admin": current_user.is_admin
    }























import re
import math
import models
from typing import List
from html import unescape
from sqlalchemy import or_, func
from fastapi import status
from database import get_db
from typing import Optional
from pydantic import BaseModel
from fastapi import Query, APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from auth import *


router = APIRouter()


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def to_slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')


def normalize(text: str):
    return " > ".join([p.strip().lower() for p in str(text).split(">")]).strip()


@router.get("/products")
def get_products(
    category: Optional[str] = Query(None),
    product: Optional[str] = Query(None, description="Product name or slug"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
    ):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        visited = set()
        while curr and curr.id not in visited:
            visited.add(curr.id)
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    base_q = db.query(models.Product).options(joinedload(models.Product.categories)).filter(
        models.Product.published == True,
        models.Product.visibility == True
    )

    # === If searching by product name/slug ===
    if product:
        prod_norm = product.strip().lower()
        prod_slug = to_slug(prod_norm)
        prod_root = prod_norm[:-1] if prod_norm.endswith('s') and len(prod_norm) > 3 else prod_norm
        prod_tokens = [t for t in re.findall(r'\w+', prod_norm) if len(t) >= 3]

        db_products = base_q.filter(
            or_(
                models.Product.name.ilike(f"%{prod_norm}%"),
                models.Product.slug.ilike(f"%{prod_slug}%"),
                models.Product.tags.ilike(f"%{prod_norm}%")
            )
        ).all()
        if not db_products:
            db_products = base_q.all()

        matched = []
        for p in db_products:
            cat_paths = [get_path(c) for c in p.categories]
            raw_cats = ", ".join(cat_paths)
            name_lower = p.name.lower()

            def contains_all(text):
                for qt in prod_tokens:
                    qt_root = qt[:-1] if qt.endswith('s') and len(qt) > 3 else qt
                    if qt not in text and qt_root not in text:
                        return False
                return True

            is_match = False
            if contains_all(name_lower):
                is_match = True
            if not is_match:
                for path in raw_cats.split(","):
                    if contains_all(path.lower()):
                        is_match = True
                        break
            if not is_match:
                slug = p.slug or to_slug(p.name)
                if prod_norm in slug or prod_root in slug or prod_slug in slug:
                    is_match = True

            if is_match:
                try:
                    price = float(p.regular_price or p.sale_price or 0)
                except:
                    price = 0
                short_desc = p.short_description or ""
                if not short_desc:
                    short_desc = (p.description or "")[:150]

                if cat_paths:
                    last_path = cat_paths[-1]
                    last_part = last_path.split(">")[-1].strip()
                    cat_id = to_slug(last_part)
                    cat_name = last_part
                else:
                    cat_id = "uncategorized"
                    cat_name = "Uncategorized"

                matched.append({
                    "id": p.id,
                    "name": p.name,
                    "slug": p.slug or to_slug(p.name),
                    "description": strip_html(short_desc),
                    "longDescription": strip_html(p.description or ""),
                    "categoryId": [cat_id],
                    "categoryName": [cat_name],
                    "price": price,
                    "brand": p.brand or "Generic",
                    "inStock": bool(p.in_stock),
                    "rating": 4.5,
                    "tint": "#dceef7",
                    "icon": cat_id.split('-')[0],
                    "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
                    "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
                    "specifications": {"Model": p.model or ""},
                    "_raw_categories": raw_cats
                })

        if not matched:
            return {"error": f"Product '{product}' not found"}
        if len(matched) == 1:
            clean = {k: v for k, v in matched[0].items() if not k.startswith("_")}
            return clean

        total_items = len(matched)
        total_pages = math.ceil(total_items / limit) if total_items > 0 else 1
        start = (page - 1) * limit
        paginated = matched[start:start+limit]
        paginated = [{k: v for k, v in p.items() if not k.startswith("_")} for p in paginated]
        return {
            "metadata": {"total_items": total_items, "total_pages": total_pages, "current_page": page, "limit": limit},
            "products": paginated
        }

    # === Category filter ===
    matching_cat_ids = set()  #defined here so count_q can always reference it
    if category:
        cat_norm = normalize(category).lower()
        for c in all_cats:
            path = get_path(c).lower()
            parts = [s.strip() for s in path.split(">")]
            if cat_norm == path or cat_norm in parts or f" > {cat_norm}" in path or f"{cat_norm} >" in path or cat_norm == c.name.lower() or cat_norm == c.slug.lower():
                matching_cat_ids.add(c.id)

        if matching_cat_ids:
            to_process = list(matching_cat_ids)
            while to_process:
                parent_id = to_process.pop()
                for child in all_cats:
                    if child.parent_id == parent_id and child.id not in matching_cat_ids:
                        matching_cat_ids.add(child.id)
                        to_process.append(child.id)
            base_q = base_q.filter(models.Product.categories.any(models.Category.id.in_(matching_cat_ids)))
        else:
            return {"metadata": {"total_items": 0, "total_pages": 1, "current_page": page, "limit": limit}, "products": []}

    # Separate count query without joinedload to avoid SQLAlchemy InvalidRequestError
    count_q = db.query(func.count(models.Product.id)).filter(
        models.Product.published == True,
        models.Product.visibility == True
    )
    if matching_cat_ids:
        count_q = count_q.filter(
            models.Product.categories.any(models.Category.id.in_(matching_cat_ids))
        )
    total_items = count_q.scalar()

    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1

    db_products = base_q.offset((page - 1) * limit).limit(limit).all()

    result = []
    for p in db_products:
        cat_paths = [get_path(c) for c in p.categories]
        primary = cat_paths[0] if cat_paths else "uncategorized"
        parts = [s.strip() for s in primary.split(">")]
        top = parts[0] if len(parts) > 0 else "uncategorized"
        sub = parts[1] if len(parts) > 1 else ""
        try:
            price = float(p.regular_price or p.sale_price or 0)
        except:
            price = 0
        short_desc = p.short_description or ""
        if not short_desc:
            short_desc = (p.description or "")[:150]

        result.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug or to_slug(p.name),
            "description": strip_html(short_desc),
            "longDescription": strip_html(p.description or ""),
            "categoryId": to_slug(top),
            "subcategoryId": to_slug(sub) if sub else "",
            "categoryName": top,
            "subcategoryName": sub,
            "price": price,
            "brand": p.brand or "Generic",
            "inStock": bool(p.in_stock),
            "rating": 4.5,
            "tint": "#dceef7",
            "icon": to_slug(sub).split('-')[0] if sub else to_slug(top).split('-')[0],
            "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
            "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
            "specifications": {"Model": p.model or ""},
        })

    return {
        "metadata": {"total_items": total_items, "total_pages": total_pages, "current_page": page, "limit": limit},
        "products": result
    }


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    children_map = {}
    for c in all_cats:
        children_map.setdefault(c.parent_id, []).append(c)

    def build_tree(parent_id):
        nodes = children_map.get(parent_id, [])
        nodes = sorted(nodes, key=lambda x: x.name.lower())
        out = []
        for node in nodes:
            if node.name.isdigit():
                continue
            if not re.search(r'[a-zA-Z]', node.name):
                continue
            child_nodes = build_tree(node.id)
            out.append({
                "id": node.slug or to_slug(node.name),
                "db_id": node.id,
                "name": node.name,
                "slug": node.slug or to_slug(node.name),
                "subcategories": [ch["name"] for ch in child_nodes],
                "children": child_nodes
            })
        return out

    return build_tree(None)


@router.get("/products/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        while curr:
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}

    if not p.published:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found...")

    # hide if no visibility
    if not getattr(p, 'visibility', None):
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found - no visibility")

    cat_paths = [get_path(c) for c in p.categories]

    if not cat_paths:
        leafIds, leafNames = [], []
    else:
        last_path = cat_paths[-1]
        last_part = last_path.split(">")[-1].strip()
        leafIds = [to_slug(last_part)]
        leafNames = [last_part]

    try:
        price = float(p.regular_price or p.sale_price or 0)
    except:
        price = 0

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug or to_slug(p.name),
        "description": strip_html(p.short_description or (p.description or "")[:150]),
        "longDescription": strip_html(p.description or ""),
        "categoryId": leafIds,
        "categoryName": leafNames,
        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "published": p.published,
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
    }


@router.get("/admin/products")
def get_admin_products(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        visited = set()
        while curr and curr.id not in visited:
            visited.add(curr.id)
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    base_q = db.query(models.Product).options(
        joinedload(models.Product.categories)
    ).order_by(models.Product.id.desc())

    total_items = db.query(func.count(models.Product.id)).scalar()
    total_pages = math.ceil(total_items / limit) if total_items else 1

    products = base_q.offset((page - 1) * limit).limit(limit).all()

    result = []
    for p in products:
        try:
            price = float(p.sale_price or p.regular_price or 0)
        except:
            price = 0

        short_desc = p.short_description or ""
        if not short_desc:
            short_desc = (p.description or "")[:150]

        cat_paths = [get_path(c) for c in p.categories] if p.categories else []
        raw_cats = ", ".join(cat_paths)

        if cat_paths:
            last_path = cat_paths[-1]
            last_part = last_path.split(">")[-1].strip()
            cat_id = to_slug(last_part)
            cat_name = last_part
        else:
            cat_id = "uncategorized"
            cat_name = "Uncategorized"
            raw_cats = "Uncategorized"

        result.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug or to_slug(p.name),
            "description": strip_html(short_desc),
            "longDescription": strip_html(p.description or ""),
            "categoryId": [cat_id],
            "categoryName": [cat_name],
            "price": price,
            "brand": p.brand or "Generic",
            "inStock": bool(p.in_stock),
            "published": bool(p.published),
            "visibility": bool(p.visibility),
            "is_featured": bool(p.is_featured),
            "rating": 4.5,
            "tint": "#dceef7",
            "icon": cat_id.split('-')[0],
            "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
            "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
            "specifications": {"Model": p.model or ""},
            "_raw_categories": raw_cats
        })

    # remove _raw_categories before returning if you want clean output like get_products
    # clean_result = [{k: v for k, v in prod.items() if not k.startswith("_")} for prod in result]

    return {
        "metadata": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit,
        },
        "products": result,
    }


# New Product Data
class ProductCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    short_description: Optional[str] = ""
    description: Optional[str] = ""
    regular_price: float = 0
    sale_price: float = 0
    in_stock: bool = True
    is_featured: bool = False
    published: bool = True
    visibility: bool = True
    brand: str = "Generic"
    model: Optional[str] = ""
    images: Optional[str] = ""
    tags: Optional[str] = ""
    category_ids: List[int] = []


# --- CREATE ---
@router.post("/create-products", status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), admin = Depends(get_current_admin)):
    # check duplicate slug
    slug = payload.slug or to_slug(payload.name)
    existing = db.query(models.Product).filter(models.Product.slug == slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product with same slug already exists")

    categories = []
    if payload.category_ids:
        categories = db.query(models.Category).filter(models.Category.id.in_(payload.category_ids)).all()
        if len(categories)!= len(payload.category_ids):
            raise HTTPException(status_code=400, detail="One or more category_ids not found")

    new_product = models.Product(
        name=payload.name,
        slug=slug,
        short_description=payload.short_description,
        description=payload.description,
        regular_price=payload.regular_price,
        sale_price=payload.sale_price,
        in_stock=payload.in_stock,
        is_featured=payload.is_featured,
        published=payload.published,
        visibility = payload.visibility,
        brand=payload.brand,
        model=payload.model,
        images=payload.images,
        tags=payload.tags,
        categories=categories
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return {"message": "Product created", "id": new_product.id, "slug": new_product.slug}


# New Updated Data
class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    regular_price: Optional[float] = None
    sale_price: Optional[float] = None
    in_stock: Optional[bool] = None
    published: Optional[bool] = None
    visibility: Optional[bool] = None
    is_featured: Optional[bool] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    images: Optional[str] = None
    tags: Optional[str] = None
    category_ids: Optional[List[int]] = None

    class Config:
        extra = "ignore"

    
# --- UPDATE ---
@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    admin = Depends(get_current_admin)
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    update_data = payload.model_dump(exclude_unset=True)  # ONLY sent fields

    if not update_data:
        raise HTTPException(400, "No fields to update")

    if "category_ids" in update_data:
        cat_ids = update_data.pop("category_ids")
        if cat_ids is not None:
            categories = db.query(models.Category).filter(models.Category.id.in_(cat_ids)).all()
            if len(categories) != len(cat_ids):
                raise HTTPException(400, "category not found")
            product.categories = categories

    for key, value in update_data.items():
        setattr(product, key, value)

    if "name" in update_data and "slug" not in update_data:
        product.slug = to_slug(update_data["name"])

    db.commit()
    db.refresh(product)
    return {"message": "Product updated successfully", "id": product.id, "updated_fields": list(update_data.keys())}


# # --- DELETE ---
# @router.delete("/products/{product_id}")
# def delete_product(product_id: int, db: Session = Depends(get_db), admin = Depends(get_current_admin)):
#     product = db.query(models.Product).filter(models.Product.id == product_id).first()
#     if not product:
#         raise HTTPException(status_code=404, detail="Product not found")
#     db.delete(product)
#     db.commit()
#     return {"message": f"Product {product_id} deleted"}


# --- ACTIVATE PRODUCT ---
@router.patch("/products/{product_id}/activate")
def activate_product(
    product_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)):
    
    # Search product by id in database.
    product = (db.query(models.Product).filter(models.Product.id == product_id).first())
    if not product:
        raise HTTPException(status_code=404,detail="Product not found")

    # Set the published status to True to show it to shoppers again
    product.published = True
    db.commit()
    db.refresh(product)

    return {
        "message": "Product activated successfully",
        "id": product.id,
        "name": product.name,
        "published": product.published
    }


# --- DEACTIVATE PRODUCT ---
@router.patch("/products/{product_id}/deactivate")
def deactivate_product(
    product_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)):
    # Search product by id
    product = (db.query(models.Product).filter(models.Product.id == product_id).first())
    if not product:raise HTTPException(status_code=404,detail="Product not found")

    # Set the published status to False to hide it from shoppers
    product.published = False
    db.commit()
    db.refresh(product)

    return {
        "message": "Product deactivated successfully",
        "id": product.id,
        "name": product.name,
        "published": product.published
    }


# --- CREATE CATEGORY ---
class CategoryCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    parent_id: Optional[int] = None


@router.post("/create-category", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate,db: Session = Depends(get_db),admin=Depends(get_current_admin)):

    # Remove extra spaces from the category name
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400,detail="Category name is required")

    # Use the provided web URL slug or create one automatically from the name
    slug = payload.slug.strip().lower() if payload.slug else to_slug(name)

    # Check duplicate name
    existing_name = (db.query(models.Category).filter(models.Category.name.ilike(name)).first())
    if existing_name:
        raise HTTPException(status_code=400,detail="Category with this name already exists")

    # Check duplicate slug
    existing_slug = (db.query(models.Category).filter(models.Category.slug == slug).first())
    if existing_slug:
        raise HTTPException(status_code=400,detail="Category with this slug already exists")

    # If parent_id is provided, verify parent exists
    parent = None
    if payload.parent_id is not None:
        parent = (
            db.query(models.Category)
            .filter(models.Category.id == payload.parent_id)
            .first())
        if not parent:
            raise HTTPException(status_code=404,detail="Parent category not found")

    # Create category
    new_category = models.Category(name=name,slug=slug,parent_id=payload.parent_id)

    # Stage, save, and reload the new category inside the database
    db.add(new_category)
    db.commit()
    db.refresh(new_category)

    return {
        "message": "Category created successfully",
        "category": {
            "id": new_category.id,
            "name": new_category.name,
            "slug": new_category.slug,
            "parent_id": new_category.parent_id
        }
    }















# auth.py:
import os
import jwt
import models
from database import get_db
from pydantic import EmailStr
from dotenv import load_dotenv
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List

load_dotenv()

router = APIRouter(prefix="/api", tags=["auth"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key_change_me")
ALGORITHM = "HS256"
security = HTTPBearer()

# --- Schemas ---
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

# --- ADMIN LOGIN (your existing one, now also checks verified) ---
@router.post("/login")
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

    payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "is_admin": user.is_admin}

# --- USER LOGIN (for normal users) ---
@router.post("/user/login")
def user_login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user or not pwd_context.verify(login_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User deactivated")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="User not verified by admin")

    payload = {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "exp": datetime.utcnow() + timedelta(hours=12)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "is_admin": user.is_admin, "email": user.email}

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

# --- ADMIN: See all users ---
@router.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), admin = Depends(get_current_admin)):
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    return users

# --- ADMIN: Update user (verify/unverify, activate, etc) ---
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