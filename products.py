import os
import re
import math
import models
from auth import *
from pathlib import Path
from html import unescape
from database import get_db
from sqlalchemy import or_, func, desc
from typing import List, Optional
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from sqlalchemy.orm import Session, joinedload
from fastapi import status, Query, APIRouter, Depends
from fastapi import BackgroundTasks
from database import SessionLocal # sessionmaker
from datetime import datetime, timedelta
from collections import Counter


router = APIRouter()
CHROMA_DIR = Path(__file__).parent / "chroma_db"
EMBED_MODEL = "all-minilm"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

embedding_function = None
vector_db = None

def get_chroma():
    global embedding_function, vector_db
    if vector_db is not None:
        return embedding_function, vector_db
    embedding_function = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)
    vector_db = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embedding_function)
    return embedding_function, vector_db


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


# --- background counters ---
def inc_product_visits(product_ids: list[int]):
    db = SessionLocal()
    try:
        for pid in product_ids:
            db.add(models.ProductSearchCount(product_id=pid, search_count=1))
        db.commit()
    finally:
        db.close()


def inc_category_searches(category_ids: list[int]):
    db = SessionLocal()
    try:
        for cid in category_ids:
            db.add(models.CategorySearchCount(category_id=cid, search_count=1))
        db.commit()
    finally:
        db.close()


@router.get("/products")
def get_products(background_tasks: BackgroundTasks, category: Optional[str] = Query(None),product: Optional[str] = Query(None, description="Product name or slug"),page: int = Query(1, ge=1),limit: int = Query(10, ge=1, le=100),db: Session = Depends(get_db)):

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
        # === EMBEDDING SEARCH FOR SEMANTIC SEARCH ===
        clean_query = product.replace("-", " ").replace("_", " ").strip()
        try:
            _, v_db = get_chroma()
            results = v_db.similarity_search_with_score(clean_query, k=50)
            # Map chroma results to DB products
            all_products = db.query(models.Product).all()
            name_lookup = {p.name.lower(): p for p in all_products}
            
            embedded_products = []
            seen = set()
            for doc, score in results:
                name = doc.metadata.get("Name") or doc.page_content.split(" Categories:")[0].strip()
                p_obj = name_lookup.get(name.lower().strip())
                if p_obj and p_obj.id not in seen:
                    embedded_products.append(p_obj)
                    seen.add(p_obj.id)
            
            # If embedding found products, use them as base
            if embedded_products:
                db_products = embedded_products
            else:
                # Fallback to LIKE if embedding returns nothing
                prod_norm = product.strip().lower()
                prod_slug = to_slug(prod_norm)
                db_products = base_q.filter(
                    or_(
                        models.Product.name.ilike(f"%{prod_norm}%"),
                        models.Product.slug.ilike(f"%{prod_slug}%"),
                        models.Product.tags.ilike(f"%{prod_norm}%"))).all()

        except Exception as e:
            print(f"Chroma failed, fallback to LIKE: {e}")
            prod_norm = product.strip().lower()
            prod_slug = to_slug(prod_norm)
            db_products = base_q.filter(
                or_(
                    models.Product.name.ilike(f"%{prod_norm}%"),
                    models.Product.slug.ilike(f"%{prod_slug}%"),
                    models.Product.tags.ilike(f"%{prod_norm}%"))).all()

        # Keep your existing matching logic after embedding
        if not db_products:
            db_products = base_q.all()

        prod_norm = product.strip().lower()
        prod_slug = to_slug(prod_norm)
        prod_root = prod_norm[:-1] if prod_norm.endswith('s') and len(prod_norm) > 3 else prod_norm
        prod_tokens = [t for t in re.findall(r'\w+', prod_norm) if len(t) >= 3]

        matched = []
        # Check if we are in embedding mode
        is_embedding_mode = 'embedded_products' in locals() and embedded_products and len(embedded_products) > 0 and db_products == embedded_products

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

            # If embedding search already found semantically similar products, accept directly
            if is_embedding_mode:
                is_match = True
            else:
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
                    "visibility": p.visibility,
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
    matching_cat_ids = set()
    if category:
        cat_norm = normalize(category).lower().strip()
        matched_cat = None
        for c in all_cats:
            if cat_norm == c.name.lower().strip() or cat_norm == c.slug.lower().strip():
                matched_cat = c
                break

        if matched_cat:
            matching_cat_ids.add(matched_cat.id)
            background_tasks.add_task(inc_category_searches, [matched_cat.id])

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
            "visibility": p.visibility,
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
    # Map parent IDs to their child categories
    children_map = {}
    for c in all_cats:
        children_map.setdefault(c.parent_id, []).append(c)

    def build_tree(parent_id):
        nodes = children_map.get(parent_id, [])
        nodes = sorted(nodes, key=lambda x: x.name.lower())
        out = []
        for node in nodes:
            # Skip if name is only numbers
            if node.name.isdigit():
                continue
            # Skip if name contains no letters
            if not re.search(r'[a-zA-Z]', node.name):
                continue
            # get subcategories
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
def get_product_by_id(product_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}

    if not p.published:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found...")

    # hide if no visibility
    if not getattr(p, 'visibility', None):
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found - no visibility")

    background_tasks.add_task(inc_product_visits, [product_id])

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

    # --- RELATED PRODUCTS ---
    related_products = []
    clean_query = p.name.replace("-", " ").replace("_", " ").strip()
    try:
        _, v_db = get_chroma()
        results = v_db.similarity_search_with_score(clean_query, k=50)
        all_products = db.query(models.Product).filter(
            models.Product.published == True,
            models.Product.visibility == True,
            models.Product.id!= p.id
        ).all()
        name_lookup = {prod.name.lower(): prod for prod in all_products}

        seen = set()
        for doc, score in results:
            name = doc.metadata.get("Name") or doc.page_content.split(" Categories:")[0].strip()
            p_obj = name_lookup.get(name.lower().strip())
            if p_obj and p_obj.id not in seen:
                related_products.append(p_obj)
                seen.add(p_obj.id)
            if len(related_products) >= 3:
                break
    except Exception as e:
        print(f"Chroma related failed: {e}")

    # Fallback to LIKE if Chroma returns nothing - same as /products
    if not related_products:
        prod_norm = p.name.strip().lower()
        prod_slug = to_slug(prod_norm)
        related_products = db.query(models.Product).options(
            joinedload(models.Product.categories)
        ).filter(
            models.Product.published == True,
            models.Product.visibility == True,
            models.Product.id!= p.id,
            or_(
                models.Product.name.ilike(f"%{prod_norm}%"),
                models.Product.slug.ilike(f"%{prod_slug}%"),
                models.Product.tags.ilike(f"%{prod_norm}%")
            )
        ).limit(3).all()

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
        "visibility": p.visibility,
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
        "related_products": [
            {
                "id": r.id,
                "name": r.name,
                "slug": r.slug or to_slug(r.name),
                "price": float(r.regular_price or r.sale_price or 0) if (r.regular_price or r.sale_price) else 0,
                "image": r.images.split(',')[0].strip() if r.images else "/products/placeholder.png",
                "brand": r.brand or "Generic",
                "inStock": bool(r.in_stock),
            } for r in related_products[:3]
        ]
    }


@router.get("/admin/products")
def get_admin_products(page: int = Query(1, ge=1),limit: int = Query(10, ge=1, le=100),db: Session = Depends(get_db),admin=Depends(get_current_admin)):
    # Get all categories from database
    print(admin)
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

    # Setup database query to get products (newest first)
    base_q = db.query(models.Product).options(
        joinedload(models.Product.categories)
    ).order_by(models.Product.id.desc())

    # Calculate pagination totals
    total_items = db.query(func.count(models.Product.id)).scalar()
    total_pages = math.ceil(total_items / limit) if total_items else 1
    # Get just the items needed for the current page
    products = base_q.offset((page - 1) * limit).limit(limit).all()

    result = []
    for p in products:
        # Try to find a valid price, use 0 if broken
        try:
            price = float(p.sale_price or p.regular_price or 0)
        except:
            price = 0
        # Create a short summary text if one is missing
        short_desc = p.short_description or ""
        if not short_desc:
            short_desc = (p.description or "")[:150]
        # Get the full text path for each category
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
            "rating": 4.5,
            "tint": "#dceef7",
            "icon": cat_id.split('-')[0],
            "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
            "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
            "specifications": {"Model": p.model or ""},
            "published": bool(p.published),
            "visibility": bool(p.visibility),
            "is_featured": bool(p.is_featured),
            "_raw_categories": raw_cats
        })

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
def update_product(product_id: int,payload: ProductUpdate,db: Session = Depends(get_db),admin = Depends(get_current_admin)):

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
def activate_product(product_id: int,db: Session = Depends(get_db),admin=Depends(get_current_admin)):
    
    # Search product by id in database.
    product = (db.query(models.Product).filter(models.Product.id == product_id).first())
    print("prodict id {product.id} product name  {products.name} product visibility {product.visibility}")
    if not product:
        raise HTTPException(status_code=404,detail="Product not found")

    # Set the visibility status to True to show it to shoppers again
    product.visibility = True
    db.commit()
    db.refresh(product)

    return {
        "message": "Product activated successfully",
        "id": product.id,
        "name": product.name,
        "visibility": product.visibility
    }


# --- DEACTIVATE PRODUCT ---
@router.patch("/products/{product_id}/deactivate")
def deactivate_product(product_id: int,db: Session = Depends(get_db),admin=Depends(get_current_admin)):

    # Search product by id
    product = (db.query(models.Product).filter(models.Product.id == product_id).first())
    if not product:raise HTTPException(status_code=404,detail="Product not found")
    # Set the visibility status to False to hide it from shoppers
    product.visibility = False
    db.commit()
    db.refresh(product)

    return {
        "message": "Product deactivated successfully",
        "id": product.id,
        "name": product.name,
        "visibility": product.visibility
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


# --- UPDATE CATEGORY ---
class CategoryNameUpdate(BaseModel):
    name: str


@router.patch("/categories/{category_id}")
def update_category_name(category_id: int,payload: CategoryNameUpdate,db: Session = Depends(get_db),admin = Depends(get_current_admin)):

    # Find category
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Clean and validate name
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Category name is required")
    
    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Category name too short")

    # If name is same, no need to update
    if new_name.lower() == category.name.lower():
        return {
            "message": "No change - name is same",
            "category": {
                "id": category.id,
                "name": category.name,
                "slug": category.slug,
                "parent_id": category.parent_id
            }
        }

    # Check duplicate name (excluding self)
    existing = db.query(models.Category).filter(
        models.Category.name.ilike(new_name),
        models.Category.id != category_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category with this name already exists")

    # Update ONLY name (slug and parent_id stay same)
    category.name = new_name
    # Change slug too:
    # category.slug = to_slug(new_name)

    db.commit()
    db.refresh(category)

    return {
        "message": "Category name updated successfully",
        "category": {
            "id": category.id,
            "name": category.name,
            "slug": category.slug,
            "parent_id": category.parent_id
        }
    }


# @router.delete("/categories/{category_id}")
# def delete_category(
#     category_id: int,
#     db: Session = Depends(get_db),
#     admin = Depends(get_current_admin)
# ):
#     # 1. Find category
#     category = db.query(models.Category).filter(models.Category.id == category_id).first()
#     if not category:
#         raise HTTPException(status_code=404, detail="Category not found")

#     # 2. Check if it has child categories
#     has_children = db.query(models.Category).filter(models.Category.parent_id == category_id).first()
#     if has_children:
#         raise HTTPException(
#             status_code=400, 
#             detail="Cannot delete category with sub-categories. Delete sub-categories first."
#         )

#     # 3. Check if it has products linked (remove this if you don't have product relation)
#     # Assuming you have a product table with category_id
#     # If your relation is many-to-many, check accordingly
#     if hasattr(models, 'Product'):
#         has_products = db.query(models.Product).filter(
#             models.Product.categories.any(id=category_id)
#         ).first()
#         if has_products:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Cannot delete category linked with products. Remove/reassign products first."
#             )

#     # 4. Delete
#     db.delete(category)
#     db.commit()

#     return {
#         "message": "Category deleted successfully",
#         "deleted_category": {
#             "id": category.id,
#             "name": category.name,
#             "slug": category.slug
#         }
#     }


@router.get("/admin/products/{product_id}")
def get_admin_product_by_id(product_id: int,db: Session = Depends(get_db),admin = Depends(get_current_admin)):

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

    p = db.query(models.Product).options(
        joinedload(models.Product.categories)
    ).filter(models.Product.id == product_id).first()

    if not p:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    cat_paths = [get_path(c) for c in p.categories]

    if not cat_paths:
        leafIds, leafNames = [], []
        full_category_paths = []
    else:
        last_path = cat_paths[-1]
        last_part = last_path.split(">")[-1].strip()
        leafIds = [to_slug(last_part)]
        leafNames = [last_part]
        full_category_paths = cat_paths

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
        "short_description": p.short_description,
        "regular_price": p.regular_price,
        "sale_price": p.sale_price,
        "price": price,
        "categoryId": leafIds,
        "categoryName": leafNames,
        "categoryPaths": full_category_paths,
        "brand": p.brand or "Generic",
        "model": p.model,
        "inStock": bool(p.in_stock),
        "in_stock": p.in_stock,
        "published": p.published,
        "visibility": p.visibility,
        "is_featured": getattr(p, 'is_featured', False),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "images": p.images,
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()],
    }


@router.get("/admin/search_counts")
def get_all_counts(
    db: Session = Depends(get_db),
    admin = Depends(get_current_admin)
):

    since_24h = datetime.utcnow() - timedelta(hours=24)

    # ---------- 24H ----------
    product_rows_24h = db.query(models.ProductSearchCount).filter(
        models.ProductSearchCount.created_at >= since_24h
    ).all()
    category_rows_24h = db.query(models.CategorySearchCount).filter(
        models.CategorySearchCount.created_at >= since_24h
    ).all()

    p_counter_24h = Counter([r.product_id for r in product_rows_24h])
    c_counter_24h = Counter([r.category_id for r in category_rows_24h])

    top_p_24h_ids = [pid for pid, _ in p_counter_24h.most_common(3)]
    top_c_24h_ids = [cid for cid, _ in c_counter_24h.most_common(3)]

    # bulk fetch names to avoid N+1
    prod_map_24h = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_(top_p_24h_ids)).all()} if top_p_24h_ids else {}
    cat_map_24h = {c.id: c for c in db.query(models.Category).filter(models.Category.id.in_(top_c_24h_ids)).all()} if top_c_24h_ids else {}

    top_products_24h = [
        {
            "product_id": pid,
            "product_name": prod_map_24h.get(pid).name if prod_map_24h.get(pid) else f"Product #{pid}",
            "slug": prod_map_24h.get(pid).slug if prod_map_24h.get(pid) else None,
            "visit_count": count
        }
        for pid, count in p_counter_24h.most_common(3)
    ]

    top_categories_24h = [
        {
            "category_id": cid,
            "category_name": cat_map_24h.get(cid).name if cat_map_24h.get(cid) else f"Category #{cid}",
            "slug": cat_map_24h.get(cid).slug if cat_map_24h.get(cid) else None,
            "search_count": count
        }
        for cid, count in c_counter_24h.most_common(3)
    ]

    # ---------- ALL TIME ----------
    p_counter_all = Counter()
    c_counter_all = Counter()

    # if you have large data, use SQL count for all-time (faster)
    all_products = db.query(
        models.ProductSearchCount.product_id,
        func.count(models.ProductSearchCount.id).label("cnt")
    ).group_by(models.ProductSearchCount.product_id).order_by(desc("cnt")).limit(3).all()

    all_categories = db.query(
        models.CategorySearchCount.category_id,
        func.count(models.CategorySearchCount.id).label("cnt")
    ).group_by(models.CategorySearchCount.category_id).order_by(desc("cnt")).limit(3).all()

    all_p_ids = [r.product_id for r in all_products]
    all_c_ids = [r.category_id for r in all_categories]

    prod_map_all = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_(all_p_ids)).all()} if all_p_ids else {}
    cat_map_all = {c.id: c for c in db.query(models.Category).filter(models.Category.id.in_(all_c_ids)).all()} if all_c_ids else {}

    top_products_all = [
        {
            "product_id": r.product_id,
            "product_name": prod_map_all.get(r.product_id).name if prod_map_all.get(r.product_id) else f"Product #{r.product_id}",
            "slug": prod_map_all.get(r.product_id).slug if prod_map_all.get(r.product_id) else None,
            "visit_count": r.cnt
        }
        for r in all_products
    ]

    top_categories_all = [
        {
            "category_id": r.category_id,
            "category_name": cat_map_all.get(r.category_id).name if cat_map_all.get(r.category_id) else f"Category #{r.category_id}",
            "slug": cat_map_all.get(r.category_id).slug if cat_map_all.get(r.category_id) else None,
            "search_count": r.cnt
        }
        for r in all_categories
    ]

    return {
        "last_24_hours": {
            # "since": since_24h.isoformat(),
            "total_product_visits": len(product_rows_24h),
            "total_category_searches": len(category_rows_24h),
            "top_products": top_products_24h,
            "top_categories": top_categories_24h
        },
        "all_time": {
            "total_product_visits": db.query(func.count(models.ProductSearchCount.id)).scalar(),
            "total_category_searches": db.query(func.count(models.CategorySearchCount.id)).scalar(),
            "top_products": top_products_all,
            "top_categories": top_categories_all
        }
    }