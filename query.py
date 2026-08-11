from fastapi import APIRouter, HTTPException
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import pandas as pd
import re, difflib, os, traceback, logging
from pydantic import BaseModel
from pathlib import Path
from collections import Counter


router = APIRouter()

class QueryRequest(BaseModel):
    user_query: str

EMBED_MODEL = "all-minilm"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
CSV_PATH = Path(__file__).parent / "products.csv"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("query")

embedding_function = None
vector_db = None
df = None
TOKEN_PRODUCT_COUNT = None

def get_resources():
    global embedding_function, vector_db, df, TOKEN_PRODUCT_COUNT
    if vector_db is not None:
        return embedding_function, vector_db, df

    # DETAILED CHECKS
    if not CHROMA_DIR.exists():
        msg = f"chroma_db not found at {CHROMA_DIR}. Files in {CHROMA_DIR.parent}: {list(CHROMA_DIR.parent.iterdir())}"
        logger.error(msg)
        raise HTTPException(status_code=500, detail=msg)

    if not CSV_PATH.exists():
        raise HTTPException(status_code=500, detail=f"products.csv not found at {CSV_PATH}")

    try:
        embedding_function = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)
        embedding_function.embed_query("test")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(tb)
        raise HTTPException(status_code=500, detail=f"Ollama failed at {OLLAMA_BASE_URL}: {e}\n{tb}")

    try:
        vector_db = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embedding_function)
        _df = pd.read_csv(CSV_PATH).fillna("")
        _df.columns = _df.columns.str.strip()
        _df['Name_lower'] = _df['Name'].astype(str).str.lower().str.strip()
        df = _df

        TOKEN_PRODUCT_COUNT = Counter()
        for name in df['Name_lower']:
            unique_toks = set(clean_tokens(name))
            for tok in unique_toks:
                TOKEN_PRODUCT_COUNT[tok] += 1
            for tok in unique_toks:
                if tok.endswith('s'):
                    TOKEN_PRODUCT_COUNT[tok[:-1]] += 1

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(tb)
        raise HTTPException(status_code=500, detail=f"Failed to load DB/CSV: {e}\n{tb}")

    return embedding_function, vector_db, df


STOP_WORDS = {"price","of","cost","what","is","the","a","an","show","me","give","details","detail","for","in","on","please","tell","about","description","desc","info","information"}
def clean_tokens(s: str):
    toks = [t.lower() for t in re.findall(r'\w+', s.lower())]
    return [t for t in toks if t not in STOP_WORDS and len(t) >= 3]

def is_product_query(user_q: str, df_local, PRODUCTS_SORTED):
    q_lower = user_q.lower().strip()
    q_toks = clean_tokens(q_lower)
    if not q_toks:
        return None

    # --- NEW: If 2+ products contain ALL query tokens, treat as category ---
    def contains_all(name_lower):
        for qt in q_toks:
            qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
            if qt not in name_lower and qt_root not in name_lower:
                # fuzzy
                if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(name_lower)):
                    return False
        return True

    match_count = df_local['Name_lower'].apply(contains_all).sum()
    if match_count > 1:
        return None # -> will go to category search and return ALL

    # --- Single word check ---
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

    # --- Multi-word: exact product only ---
    for _, row in PRODUCTS_SORTED.iterrows():
        name_lower = str(row['Name_lower']).strip()
        if not name_lower:
            continue
        # exact match only
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
        if matched == len(name_toks) and matched == len(q_toks): # exact token match
            return row

    return None


@router.post("/query")
def ask_rag_bot(request: QueryRequest):
    try:
        _, v_db, df_local = get_resources()
        PRODUCTS_SORTED = df_local.sort_values(by='Name', key=lambda x: x.str.len(), ascending=False)

        prod_row = is_product_query(request.user_query, df_local, PRODUCTS_SORTED)
        if prod_row is not None:
            prod = prod_row.to_dict()
            prod.pop('Name_lower', None)
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

            # def matches(row):
            #     text = f"{row['Name_lower']} {str(row.get('Categories','')).lower()}"
            #     for qt in q_toks:
            #         qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
            #         if qt not in text and qt_root not in text:
            #             if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(text)):
            #                 return False
            #     return True

            # mask = df_local.apply(matches, axis=1)

            mask = df_local['Name_lower'].apply(matches)
            matched_df = df_local[mask]

            if len(matched_df) > 1: # if 2+ products match -> it's a category
                final, seen = [], set()
                for _, r in matched_df.iterrows():
                    name = str(r.get("Name","")).strip().lower()
                    if name in seen:
                        continue
                    d = r.to_dict()
                    d.pop('Name_lower', None)
                    final.append(d)
                    seen.add(name)
                return {"products": final, "query": request.user_query, "type": "category", "count": len(final)}

        # --- FALLBACK VECTOR SEARCH ---
        results = v_db.similarity_search_with_score(request.user_query, k=20)
        final, seen = [], set()
        for doc, _ in results:
            row_num = doc.metadata.get("row")
            if row_num is None:
                continue
            try:
                r = df_local.iloc[int(row_num)].to_dict()
            except Exception:
                continue
            name = str(r.get("Name","")).strip()
            if not name or name.lower() in seen:
                continue
            r.pop('Name_lower', None)
            final.append(r)
            seen.add(name.lower())
            if len(final) >= 10:
                break

        return {"products": final[:10], "query": request.user_query, "type": "category"}

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        # PRINT TO TERMINAL
        print("\n========== QUERY CRASH ==========")
        print(f"Query: {request.user_query}")
        print(tb)
        print("================================\n")
        logger.error(tb)
        # RETURN TO CLIENT (instead of generic 500)
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "traceback": tb,
            "query": request.user_query,
            "chroma_exists": CHROMA_DIR.exists(),
            "csv_exists": CSV_PATH.exists()
        })