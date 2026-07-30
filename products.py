import math
from typing import Optional
from fastapi import FastAPI, Query
import pandas as pd

app = FastAPI(title="Product Catalog API")

# Load and clean data once
df = pd.read_csv("products.csv").fillna("")
df.columns = df.columns.str.strip()
df = df.drop_duplicates(subset=["Name"], keep="first")


def normalize(text: str) -> str:
    # lowercase + trim + remove extra spaces around >
    return " > ".join([p.strip().lower() for p in text.split(">")]).strip()


@app.get("/products")
def get_products(
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
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
    paginated = filtered_df.iloc[(page - 1) * limit : page * limit]

    return {
        "metadata": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit,
        },
        "products": paginated.to_dict(orient="records"),
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
        return [
            {
                "name": name,
                "subcategories": [sub for sub in sorted(child.keys())] if child else [],
                "children": build(child),  # remove this line if you want only 1 level
            }
            for name, child in sorted(node.items())
        ]

    return build(tree)
