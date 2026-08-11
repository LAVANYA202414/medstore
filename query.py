from fastapi import APIRouter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import pandas as pd
import re
import difflib

router = APIRouter()

df = pd.read_csv("products.csv").fillna("")
df.columns = df.columns.str.strip()
df['Name_lower'] = df['Name'].astype(str).str.lower().str.strip()

PRODUCTS_SORTED = df.sort_values(by='Name', key=lambda x: x.str.len(), ascending=False)

STOP_WORDS = {"price","of","cost","what","is","the","a","an","show","me","give","details","detail","for","in","on","please","tell","about","description","desc","info","information"}

def clean_tokens(s: str):
    toks = [t.lower() for t in re.findall(r'\w+', s.lower())]
    return [t for t in toks if t not in STOP_WORDS and len(t) >= 3]

def is_product_query(user_q: str):
    q_lower = user_q.lower()
    q_toks = clean_tokens(q_lower)
    if not q_toks:
        return None

    for _, row in PRODUCTS_SORTED.iterrows():
        name = str(row['Name']).strip()
        name_lower = str(row['Name_lower']).strip()
        if not name_lower or len(name_lower) < 3:
            continue

        # 1. Direct contains (handles exact)
        if name_lower in q_lower:
            return row

        # 2. Typo tolerant: all query tokens must fuzzy-match name tokens
        name_toks = clean_tokens(name_lower)
        if not name_toks:
            continue

        matched = 0
        for qt in q_toks:
            # close match for typo like transite -> transit / transportation
            # use difflib with cutoff 0.8 OR substring with len>=4
            found = False
            for nt in name_toks:
                if qt in nt or nt in qt: # transport in transportation
                    if len(qt) >= 4 and len(nt) >= 3:
                        found = True
                        break
                if difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.8:
                    found = True
                    break
            if found:
                matched += 1

        # need at least 80% of query tokens matched
        if matched >= len(q_toks) * 0.8 and matched >= 1:
            # prevent "chair" alone matching everything
            if len(q_toks) == 1 and q_toks[0] in ["chair","stool","table"]:
                continue
            return row

    return None

@router.get("/query")
def ask_rag_bot(user_query: str):
    # 1. PRODUCT?
    prod_row = is_product_query(user_query)
    if prod_row is not None:
        prod = prod_row.to_dict()
        prod.pop('Name_lower', None)
        return {"products": [prod], "query": user_query, "type": "product"}

    # 2. CATEGORY / SEARCH -> top 10
    embedding_function = OllamaEmbeddings(model="nomic-embed-text")
    vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_function)
    results = vector_db.similarity_search_with_score(user_query, k=20)

    final, seen = [], set()
    for doc, _ in results:
        row_num = doc.metadata.get("row")
        if row_num is None: continue
        r = df.iloc[int(row_num)].to_dict()
        name = str(r.get("Name","")).strip()
        if not name or name.lower() in seen: continue
        r.pop('Name_lower', None)
        final.append(r)
        seen.add(name.lower())
        if len(final) >= 10: break

    return {"products": final[:10], "query": user_query, "type": "category"}