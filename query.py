from fastapi import APIRouter, HTTPException, Depends
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import re, difflib, os, traceback, logging
from pydantic import BaseModel
from pathlib import Path
from collections import Counter
from sqlalchemy.orm import Session
import pandas as pd
from database import get_db
import models

router = APIRouter()

class QueryRequest(BaseModel):
    user_query: str

EMBED_MODEL = "all-minilm"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("query")

embedding_function = None
vector_db = None
TOKEN_PRODUCT_COUNT = None

def get_resources():
    global embedding_function, vector_db
    if vector_db is not None:
        return embedding_function, vector_db

    if not CHROMA_DIR.exists():
        msg = f"chroma_db not found at {CHROMA_DIR}. Files in {CHROMA_DIR.parent}: {list(CHROMA_DIR.parent.iterdir())}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)

    try:
        embedding_function = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)
        embedding_function.embed_query("test")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(tb)
        raise HTTPException(status_code=500, detail=f"Ollama failed at {OLLAMA_BASE_URL}: {e}\n{tb}")

    try:
        vector_db = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embedding_function)
        vector_db.get(limit=1) # test

    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Failed to load DB: {e}\n{tb}")

    return embedding_function, vector_db


STOP_WORDS = {"price","of","cost","what","is","the","a","an","show","me","give","details","detail","for","in","on","please","tell","about","description","desc","info","information"}
def clean_tokens(s: str):
    toks = [t.lower() for t in re.findall(r'\w+', s.lower())]
    return [t for t in toks if t not in STOP_WORDS and len(t) >= 3]

def is_product_query(user_q: str, df_local, PRODUCTS_SORTED):
    q_lower = user_q.lower().strip()
    q_toks = clean_tokens(q_lower)
    if not q_toks:
        return None

    def contains_all(name_lower):
        for qt in q_toks:
            qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
            if qt not in name_lower and qt_root not in name_lower:
                if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(name_lower)):
                    return False
        return True

    match_count = df_local['Name_lower'].apply(contains_all).sum()
    if match_count > 1:
        return None

    if len(q_toks) == 1:
        qt = q_toks[0]
        count = 0
        exact_match_row = None
        for _, row in PRODUCTS_SORTED.iterrows():
            name_lower = str(row['Name_lower'])
            if name_lower == q_lower:
                return row
            name_toks = clean_tokens(name_lower)
            if any(qt in nt or nt in qt or difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in name_toks):
                count += 1
                if exact_match_row is None:
                    exact_match_row = row
            if count > 1:
                return None
        if count == 1:
            return exact_match_row
        return None

    for _, row in PRODUCTS_SORTED.iterrows():
        name_lower = str(row['Name_lower']).strip()
        if not name_lower:
            continue
        # Exact match only
        if name_lower == q_lower:
            return row
        if name_lower in q_lower and len(q_lower) < len(name_lower) + 10:
            return row

        name_toks = clean_tokens(name_lower)
        if not name_toks:
            continue
        if len(name_toks) > len(q_toks) + 2:
            continue
        matched = sum(1 for qt in q_toks if any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in name_toks))
        if matched == len(name_toks) and matched == len(q_toks):
            return row
    return None

@router.post("/query")
def ask_rag_bot(request: QueryRequest, db: Session = Depends(get_db)):
    try:
        _, v_db = get_resources()

        # --- LOAD FROM DATABASE INSTEAD OF CSV ---
        # Get all published products from DB
        db_products = db.query(models.Product).filter(
            models.Product.published == True,
            models.Product.visibility == True
        ).all()

        if not db_products:
            return {"products": [], "query": request.user_query, "type": "category"}

        # Convert DB to DataFrame to keep your same logic
        rows = []
        for p in db_products:
            rows.append({
                "id": p.id,
                "Name": p.name,
                "slug": p.slug,
                "regular_price": p.regular_price,
                "sale_price": p.sale_price,
                "brand": p.brand,
                "images": p.images,
                "tags": p.tags,
                "description": p.description,
                "short_description": p.short_description,
                "_db_obj": p # keep ref
            })
        df_local = pd.DataFrame(rows).fillna("")
        df_local['Name_lower'] = df_local['Name'].astype(str).str.lower().str.strip()

        # Build TOKEN_PRODUCT_COUNT like before but from DB
        TOKEN_PRODUCT_COUNT = Counter()
        for name in df_local['Name_lower']:
            unique_toks = set(clean_tokens(name))
            for tok in unique_toks:
                TOKEN_PRODUCT_COUNT[tok] += 1
                if tok.endswith('s'):
                    TOKEN_PRODUCT_COUNT[tok[:-1]] += 1

        PRODUCTS_SORTED = df_local.sort_values(by='Name', key=lambda x: x.str.len(), ascending=False)

        prod_row = is_product_query(request.user_query, df_local, PRODUCTS_SORTED)
        if prod_row is not None:
            prod = prod_row.to_dict()
            prod.pop('Name_lower', None)
            prod.pop('_db_obj', None)
            return {"products": [prod], "query": request.user_query, "type": "product"}

        # --- CATEGORY KEYWORD SEARCH FOR ANY LENGTH ---
        q_lower = request.user_query.lower().strip()
        q_toks = clean_tokens(q_lower)

        if q_toks:
            # find all products where ALL query tokens appear in name
            def matches(name_lower):
                for qt in q_toks:
                    qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
                    if qt not in name_lower and qt_root not in name_lower:
                        # fuzzy check
                        if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(name_lower)):
                            return False
                return True

            mask = df_local['Name_lower'].apply(matches)
            matched_df = df_local[mask]

            if len(matched_df) > 1:
                final, seen = [], set()
                for _, r in matched_df.iterrows():
                    name = str(r.get("Name","")).strip().lower()
                    if name in seen:
                        continue
                    d = r.to_dict()
                    d.pop('Name_lower', None)
                    d.pop('_db_obj', None)
                    final.append(d)
                    seen.add(name)
                return {"products": final, "query": request.user_query, "type": "category", "count": len(final)}

        # --- FALLBACK VECTOR SEARCH - NOW FETCH FROM DB ---
        results = v_db.similarity_search_with_score(request.user_query, k=20)
        final, seen = [], set()
        for doc, _ in results:
            # Try to get product by id from chroma metadata
            prod_id = doc.metadata.get("id") or doc.metadata.get("row")
            r = None
            if prod_id is not None:
                try:
                    # if row is index, get from df
                    r = df_local.iloc[int(prod_id)].to_dict() if str(prod_id).isdigit() and int(prod_id) < len(df_local) else None
                except:
                    r = None
                # if id is real DB id, query it
                if r is None:
                    try:
                        db_obj = db.query(models.Product).filter(models.Product.id == int(prod_id)).first()
                        if db_obj:
                            r = {"Name": db_obj.name, "id": db_obj.id, "slug": db_obj.slug, "regular_price": db_obj.regular_price}
                    except:
                        pass

            if r is None:
                # last fallback: use metadata directly
                r = {"Name": doc.metadata.get("Name") or doc.page_content}

            name = str(r.get("Name","")).strip()
            if not name or name.lower() in seen:
                continue
            r.pop('Name_lower', None)
            r.pop('_db_obj', None)
            final.append(r)
            seen.add(name.lower())
            if len(final) >= 10:
                break

        # if vector search gave 0 results, return top 10 from DB (fixes "hi" case)
        if not final:
            final = df_local.head(10).to_dict(orient="records")
            for f in final:
                f.pop('Name_lower', None)
                f.pop('_db_obj', None)

        return {"products": final[:10], "query": request.user_query, "type": "category"}

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n========== QUERY CRASH ==========\nQuery: {request.user_query}\n{tb}\n===============================\n")
        logger.error(tb)
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "traceback": tb,
            "query": request.user_query,
            "chroma_exists": CHROMA_DIR.exists(),
        })