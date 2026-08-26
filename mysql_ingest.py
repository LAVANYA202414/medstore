import re
import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import Product, Category

load_dotenv()
db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
print(f"Connecting to database at: {db_url}")

def to_slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')

print("Creating tables...")
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
print("Tables created: ", list(Base.metadata.tables.keys()))

csv_path = "products_cleaned.csv" if os.path.exists("products_cleaned.csv") else "products.csv"
print(f"Reading {csv_path}...")
df = pd.read_csv(csv_path).fillna("")
df.columns = df.columns.str.strip()
df = df[df['Name'].astype(str).str.strip()!= ""]
df = df.drop_duplicates(subset=["Name"], keep="first").reset_index(drop=True)

db = SessionLocal()
category_cache = {}

def get_or_create_category_chain(path_str):
    parts = [p.strip() for p in str(path_str).split(">") if p.strip()]
    result = []
    parent = None
    for part in parts:
        if not part or part.isdigit() or not re.search(r'[a-zA-Z]', part):
            continue
        cache_key = f"{parent.id if parent else 'root'}::{part}"
        if cache_key in category_cache:
            cat = category_cache[cache_key]
            parent = cat
            result.append(cat)
            continue

        query = db.query(Category).filter(Category.name == part)
        query = query.filter(Category.parent_id == (parent.id if parent else None))
        existing = query.first()

        if existing:
            category_cache[cache_key] = existing
            parent = existing
            result.append(existing)
            continue

        new_cat = Category(name=part, slug=to_slug(part), parent_id=parent.id if parent else None)
        db.add(new_cat)
        db.flush()
        category_cache[cache_key] = new_cat
        parent = new_cat
        result.append(new_cat)
    return result

try:
    print(f"Ingesting {len(df)} products...")

    for idx, row in df.iterrows():
        try:
            rp = float(str(row['Regular price'] or 0).replace(',', '').replace('€','').strip() or 0)
        except:
            rp = 0
        try:
            sp = float(str(row['Sale price'] or 0).replace(',', '').replace('€','').strip() or 0)
        except:
            sp = 0

        pub_raw = str(row.get('Published','1')).strip().lower()
        is_published = pub_raw in ['1','true','yes']

        vis_raw = str(row.get('Visibility in catalogue','visible')).strip().lower()
        is_visible = False if 'hidden' in vis_raw else True

        p = Product(
            name=str(row['Name']).strip()[:500],
            slug=to_slug(row['Name']),
            short_description=str(row['Short description'])[:1000],
            description=str(row['Description'])[:5000],
            regular_price=rp,
            sale_price=sp,
            in_stock=str(row['In stock?']) == '1',
            model=str(row.get('Attribute 1 value(s)', ''))[:255],
            images=str(row['Images']).split(',')[0].strip()[:500],
            tags=str(row['Tags'])[:1000],
            published=is_published,
            visibility=is_visible
        )

        seen_cat_ids = set()
        unique_cats = []
        for cat_path in [c.strip() for c in str(row['Categories']).split(",") if c.strip()]:
            chain = get_or_create_category_chain(cat_path)
            for cat_obj in chain:
                if cat_obj.id not in seen_cat_ids:
                    seen_cat_ids.add(cat_obj.id)
                    unique_cats.append(cat_obj)

        p.categories = unique_cats
        db.add(p)

        if idx % 500 == 0:
            db.commit()
            print(f" {idx}/{len(df)} done")

    db.commit()
    print(f"\n SUCCESS! {db.query(Product).count()} products, {db.query(Category).count()} categories")

except Exception as e:
    db.rollback()
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
