import math
import pandas as pd
from fastapi import FastAPI, Query
from typing import Dict, Any

app = FastAPI(title="Product Catalog API")

df = pd.read_csv("products.csv").fillna("")
df.columns = df.columns.str.strip()

@app.get("/products")
def get_products(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100)
):
    total_items = len(df)
    total_pages = math.ceil(total_items / limit)

    start = (page - 1) * limit
    end = start + limit

    paginated = df.iloc[start:end]

    return {
        "metadata": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "limit": limit
        },
        "products": paginated.to_dict(orient="records")
    }