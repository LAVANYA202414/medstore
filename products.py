import re
import math
import pandas as pd
from fastapi import FastAPI, Query
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware
import ingest
import query
from html import unescape


app = FastAPI(title="Product Catalog API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:8000", "https://medstore.codenomad.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def strip_html(text: str) -> str:
    if not text:
        return ""
    # decode &deg; &amp; etc
    text = unescape(text)
    # remove <p> <br> etc
    text = re.sub(r'<[^>]+>', ' ', text)
    # clean extra spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def to_slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')


def normalize(text: str):
    return " > ".join([p.strip().lower() for p in str(text).split(">")]).strip()


def get_primary_path(categories_str: str):
    paths = [p.strip() for p in str(categories_str).split(",") if p.strip()]
    if not paths:
        return "uncategorized"
    paths = sorted(paths, key=lambda x: x.count(">"), reverse=True)
    return paths[0]


df = pd.read_csv("products.csv").fillna("")
df.columns = df.columns.str.strip()
df = df[df['Name'].astype(str).str.strip()!= ""]
df = df.drop_duplicates(subset=["Name"], keep="first").reset_index(drop=True)

all_products = []
counter = 1

for _, row in df.iterrows():
    name = str(row['Name']).strip()
    if name == "":
        continue

    primary = get_primary_path(row['Categories'])
    parts = [p.strip() for p in primary.split(">")]

    top = parts[0] if len(parts) > 0 else "uncategorized"
    sub = parts[1] if len(parts) > 1 else ""

    try:
        price = float(row['Regular price'] or row['Sale price'] or 0)
    except:
        price = 0

    short_desc = str(row['Short description']).strip()
    if not short_desc:
        short_desc = str(row['Description'])[:150].strip()

    all_products.append({
        "id": f"p{counter}",
        "name": name,
        "slug": to_slug(name),
        "description": short_desc,
        "longDescription": str(row['Description']),
        "categoryId": to_slug(top),
        "subcategoryId": to_slug(sub) if sub else "",
        "categoryName": top,
        "subcategoryName": sub,
        "price": price,
        "brand": "Generic",
        "inStock": str(row['In stock?']) == '1',
        "rating": 4.5,
        "tint": "#dceef7",
        "icon": to_slug(sub).split('-')[0] if sub else to_slug(top).split('-')[0],
        "image": str(row['Images']).split(',')[0].strip() if row['Images'] else "/products/placeholder.png",
        "tags": [t.strip() for t in str(row['Tags']).split(',') if t.strip()][:5],
        "specifications": {"Model": str(row.get('Attribute 1 value(s)', ''))},
        "_raw_categories": str(row['Categories'])
    })
    counter += 1


@app.get("/products")
def get_products(
    category: Optional[str] = Query(None),
    product: Optional[str] = Query(None, description="Product name or slug"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    # If product name/slug is mentioned -> return that product detail
    if product:
        prod_norm = product.strip().lower()
        prod_slug = to_slug(prod_norm)

        for p in all_products:
            if p["name"].lower() == prod_norm or p["slug"] == prod_slug or p["slug"] == prod_norm:
                clean = {k: v for k, v in p.items() if not k.startswith("_")}
                clean["description"] = strip_html(clean["description"])
                clean["longDescription"] = strip_html(clean["longDescription"])
                return clean

        for p in all_products:
            if prod_norm in p["name"].lower() or prod_norm in p["slug"]:
                clean = {k: v for k, v in p.items() if not k.startswith("_")}
                clean["description"] = strip_html(clean["description"])
                clean["longDescription"] = strip_html(clean["longDescription"])
                return clean

        return {"error": f"Product '{product}' not found"}

    # If product not mentioned -> filter by category
    filtered = all_products

    if category:
        cat_norm = normalize(category).lower()
        new_list = []
        for p in filtered:
            paths = [normalize(x).lower() for x in p["_raw_categories"].split(",")]
            for path in paths:
                parts = [s.strip() for s in path.split(">")]
                if cat_norm == path or cat_norm in parts or f" > {cat_norm}" in path or f"{cat_norm} >" in path:
                    new_list.append(p)
                    break
        filtered = new_list

    total_items = len(filtered)
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1
    start = (page - 1) * limit
    paginated = filtered[start:start+limit]

    result = []
    for p in paginated:
        clean = {k: v for k, v in p.items() if not k.startswith("_")}
        # ONLY CLEAN WHILE SENDING RESPONSE
        clean["description"] = strip_html(clean["description"])
        clean["longDescription"] = strip_html(clean["longDescription"])
        result.append(clean)

    return {
        "metadata": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit
        },
        "products": result
    }


@app.get("/categories")
def get_categories():
    tree = {}
    for cell in df["Categories"]:
        if not cell or str(cell).strip() == "":
            continue
        for path in [p.strip() for p in str(cell).split(",") if p.strip()]:
            # FILTER: ignore pure numbers like 0, 1, 199, 350
            # and ignore paths that don't contain any letter
            if path.isdigit():
                continue
            if not re.search(r'[a-zA-Z]', path):
                continue
            # Also skip if path looks like a price (e.g., "350")
            if re.fullmatch(r'\d+(\.\d+)?', path.strip()):
                continue

            parts = [p.strip() for p in path.split(">") if p.strip()]
            # Clean parts - remove numeric parts
            parts = [p for p in parts if not p.isdigit() and re.search(r'[a-zA-Z]', p)]
            if not parts:
                continue

            node = tree
            for part in parts:
                node = node.setdefault(part, {})

    def build(node):
        out = []
        for name, child in sorted(node.items()):
            # Double filter at build time
            if name.isdigit():
                continue
            if not re.search(r'[a-zA-Z]', name):
                continue
            out.append({
                "id": to_slug(name),
                "name": name,
                "slug": to_slug(name),
                "subcategories": sorted(child.keys()),
                "children": build(child)
            })
        return out

    return build(tree)

app.include_router(ingest.router)
app.include_router(query.router)