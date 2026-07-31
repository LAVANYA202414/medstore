import re
import math
import pandas as pd
from fastapi import FastAPI, Query
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
import ingest
import query

app = FastAPI(title="Product Catalog API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

df = pd.read_csv("products.csv").fillna("")
df.columns = df.columns.str.strip()
df = df.drop_duplicates(subset=["Name"], keep="first")

def normalize(text: str) -> str:
    return " > ".join([p.strip().lower() for p in text.split(">")]).strip()


def to_slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

df = pd.read_csv("products.csv").fillna("")
df = df.drop_duplicates(subset=["Name"], keep="first")

products = []
for i, row in df.iterrows():
    # Categories = "Diagnostics > Blood Pressure/Vital, Emergency > Bags"
    # Take first path as primary
    first_path = str(row['Categories']).split(',')[0].strip()
    parts = [p.strip() for p in first_path.split('>')]

    top = parts[0] if len(parts)>0 else "uncategorized"
    sub = parts[1] if len(parts)>1 else ""

    products.append({
        "id": f"p{i+1}",
        "name": row['Name'],
        "slug": to_slug(row['Name']),
        "description": row['Short description'] or row['Description'][:120],
        "longDescription": row['Description'],
        "categoryId": to_slug(top), # cat-diagnostics
        "subcategoryId": to_slug(sub), # sub-bp
        "categoryName": top,
        "subcategoryName": sub,
        "price": float(row['Regular price'] or row['Sale price'] or 0),
        "brand": row.get('Brand','') or 'Generic',
        "inStock": str(row['In stock?']) == '1',
        "rating": 4.5, # file doesn't have rating, set default or random
        "tint": "#dceef7",
        "icon": to_slug(sub).split('-')[0] if sub else to_slug(top).split('-')[0],
        "image": str(row['Images']).split(',')[0].strip() if row['Images'] else "/products/placeholder.png",
        "tags": [t.strip() for t in str(row['Tags']).split(',') if t.strip()][:5],
        "specifications": {
            "Model": row.get('Attribute 1 value(s)',''),
        }
    })

@app.get("/products")
def get_products(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    filtered_df = df
    if category:
        cat_norm = normalize(category)
        def match(cell: str) -> bool:
            paths = [normalize(p) for p in str(cell).split(",")]
            for p in paths:
                if p == cat_norm or p.startswith(cat_norm + " >"):
                    return True
            return False
        filtered_df = filtered_df[filtered_df["Categories"].apply(match)]

    total_items = len(filtered_df)
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1
    paginated = filtered_df.iloc[(page-1)*limit : page*limit]

    return {
        "metadata": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit
        },
        "products": paginated.to_dict(orient="records")
    }

@app.get("/categories")
def get_categories():
    tree = {}
    for cell in df["Categories"]:
        for path in [p.strip() for p in str(cell).split(",") if p.strip()]:
            parts = [p.strip() for p in path.split(">")]
            node = tree
            for part in parts:
                node = node.setdefault(part, {})

    def build(node):
        result = []
        for name, child in sorted(node.items()):
            slug = to_slug(name)
            result.append(
                {
                    "id": slug,
                    "name": name,
                    "shortName": name,
                    "slug": slug,
                    "description": f"{name} products and accessories.",
                    "icon": slug.split("-")[0] if slug else "",
                    "subcategories": [
                        {
                            "id": to_slug(sub),
                            "name": sub,
                            "slug": to_slug(sub)
                        }
                        for sub in sorted(child.keys())
                    ],
                    "children": build(child)
                }
            )
        return result

    return build(tree)

app.include_router(ingest.router)
app.include_router(query.router)