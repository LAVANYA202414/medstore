import re
import math
import models
from typing import List
from html import unescape
from sqlalchemy import or_
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

    base_q = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.published == True)

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

                primary = cat_paths[0] if cat_paths else "uncategorized"
                parts = [s.strip() for s in primary.split(">")]
                top = parts[0] if len(parts) > 0 else "uncategorized"
                sub = parts[1] if len(parts) > 1 else ""

                matched.append({
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
        # strip _raw for response
        paginated = [{k: v for k, v in p.items() if not k.startswith("_")} for p in paginated]
        return {
            "metadata": {"total_items": total_items, "total_pages": total_pages, "current_page": page, "limit": limit},
            "products": paginated
        }

    # === Category filter (NOW FROM DB) ===
    if category:
        cat_norm = normalize(category).lower()
        matching_cat_ids = set()
        for c in all_cats:
            path = get_path(c).lower()
            parts = [s.strip() for s in path.split(">")]
            if cat_norm == path or cat_norm in parts or f" > {cat_norm}" in path or f"{cat_norm} >" in path or cat_norm == c.name.lower() or cat_norm == c.slug.lower():
                matching_cat_ids.add(c.id)

        # include descendants of matched categories
        if matching_cat_ids:
            # expand to descendants
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

    total_items = base_q.count()
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1
    db_products = base_q.offset((page-1)*limit).limit(limit).all()

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
    
    # get all category text paths
    cat_paths = [get_path(c) for c in p.categories]
    # pick the primary category chain
    primary = cat_paths[0] if cat_paths else "uncategorized"
    parts = [s.strip() for s in primary.split(">")]
    top = parts[0] if len(parts) > 0 else "uncategorized"
    sub = parts[1] if len(parts) > 1 else ""
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
        "categoryId": to_slug(top),
        "subcategoryId": to_slug(sub) if sub else "",
        "categoryName": top,
        "subcategoryName": sub,
        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
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
    brand: str = "Generic"
    model: Optional[str] = ""
    images: Optional[str] = ""
    tags: Optional[str] = ""
    category_ids: List[int] = []


# --- CREATE ---
@router.post("/products", status_code=status.HTTP_201_CREATED)
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


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    regular_price: Optional[float] = None
    sale_price: Optional[float] = None
    in_stock: Optional[bool] = None
    is_featured: Optional[bool] = None
    published: Optional[bool] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    images: Optional[str] = None
    tags: Optional[str] = None
    category_ids: Optional[List[int]] = None


# --- UPDATE ---
@router.put("/products/{product_id}")
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db), admin = Depends(get_current_admin)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = payload.dict(exclude_unset=True)

    if "category_ids" in update_data:
        cat_ids = update_data.pop("category_ids")
        if cat_ids is not None:
            categories = db.query(models.Category).filter(models.Category.id.in_(cat_ids)).all()
            product.categories = categories

    for key, value in update_data.items():
        if key == "name" and value and not payload.slug:
            # auto update slug if name changed and slug not provided
            setattr(product, "slug", to_slug(value))
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return {"message": "Product updated", "id": product.id}