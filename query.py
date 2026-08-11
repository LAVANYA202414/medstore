from html import unescape
from fastapi import APIRouter
from helper_functions import *
from functools import lru_cache
from langchain_chroma import Chroma
import pandas as pd, re, os, random, difflib, json
from langchain_ollama import OllamaEmbeddings, ChatOllama

router = APIRouter()
BASE = os.path.dirname(__file__)


df = pd.read_csv(os.path.join(BASE, "products.csv")).fillna("")
df["Name_lower"] = df["Name"].astype(str).str.lower().str.strip()
df["Categories_lower"] = df["Categories"].astype(str).str.lower()
df["Description_lower"] = df["Description"].astype(str).str.lower() + " " + df["Short description"].astype(str).str.lower()
df = df[df["Name"].astype(str).str.strip().str.len() >= 3]
df = df[~df["Name_lower"].isin(["new", "test", "product", "null", ""])]
df = df[~df["Name_lower"].str.strip().eq("")]
df = df.drop_duplicates(subset=["Name_lower"], keep="first")

# drop rows where columns clearly got shifted by a broken CSV row
# ("In stock?" should be a short token like 1 / 0 / backorder)
df = df[df["In stock?"].astype(str).str.len() <= 15]

# numeric price columns, NaN when unparsable
df["_regular_price"] = pd.to_numeric(
    df["Regular price"].astype(str).str.replace(r'[^\d.]', '', regex=True), errors="coerce"
)
df["_sale_price"] = pd.to_numeric(
    df["Sale price"].astype(str).str.replace(r'[^\d.]', '', regex=True), errors="coerce"
)
df["_effective_price"] = df["_sale_price"].combine_first(df["_regular_price"])
df["_in_stock"] = df["In stock?"].astype(str).str.strip().eq("1")

df = df.reset_index(drop=True)

try:
    db = Chroma(persist_directory=os.path.join(BASE, "chroma_db"),
                embedding_function=OllamaEmbeddings(model="nomic-embed-text"))
except Exception:
    db = None

# llm_creative = ChatOllama(model="llama3.2:1b", temperature=0.2, num_predict=120)
llm_creative = ChatOllama(model="llama3.2:1b", temperature=0.2, num_predict=60, keep_alive="30m")
# llm_social = ChatOllama(model="llama3.2:1b", temperature=0.9, num_predict=60)
llm_social = ChatOllama(model="llama3.2:1b", temperature=0.9, num_predict=60, keep_alive="30m")

DROP_COLS = ["Name_lower", "Categories_lower", "_regular_price", "_sale_price", "_effective_price", "_in_stock"]

GENERIC_WORDS = {"show","me","some","products","product","list","all","give","please","want","need","any","few"}
# GREETING_WORDS = {"hi","hey","hello","hola","howdy"}
# GOODBYE_WORDS = {"bye","goodbye","see you","farewell","take care","see ya","adios","good night","bye bye","see you soon"}
# GREETING_PHRASES = {"good morning","good afternoon","good evening","greetings","hi there","hello there","hey there"}
EXCLUSION_KEYWORDS = ["other than","other then","except","excluding","exclude","without","apart from","besides","not including","not include"]
DETAIL_KEYWORDS = {"price","cost","rate","pricing","stock","availability","image","images","photo","description","detail","details","category","categories","model","tag","tags"}
DF_SORTED_BY_NAME_LEN = df.sort_values(by="Name_lower", key=lambda x: x.str.len(), ascending=False)
SYNONYM_MAP = {
    "bp": "blood pressure",
    "bp monitor": "blood pressure",
    "bp monitors": "blood pressure",
    "ecg": "ecg",
    "wheelchair": "wheelchair",
    "wheelchairs": "wheelchair",
}

POLICY_KEYWORDS = ["delivery charge","shipping cost","delivery cost","warranty","can i return","return policy",
                    "refund","how long does delivery","shipping time","exchange policy"]
ADVICE_KEYWORDS = ["how to use","best for home","suitable for","recommend","which is best","best one",
                    "is this safe","how do i use"]
COLOR_WORDS = ["black","white","red","blue","green","yellow","orange","grey","gray","pink","purple","brown","beige"]
SIZE_WORDS = ["small","medium","large","extra large","xl","xs","s","m","l"]

# ============================================================
# SESSION MEMORY (#5) - simple in-memory store keyed by session_id.
# Resets on server restart; fine for a lightweight follow-up window.
# ============================================================
SESSION_STATE = {}


@lru_cache(maxsize=1024)
def fuzzy_find_products_cached(query_text, limit=10):
    return fuzzy_find_products(query_text, limit)


@lru_cache(maxsize=512)
def classify_intent_llm_cached(user_query: str):
    return classify_intent_llm(user_query)


def summarize_text(text, max_chars=220):
    text = clean(text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    # cut at the last full sentence if possible, else last full word
    last_period = truncated.rfind('. ')
    if last_period > max_chars * 0.4:
        return truncated[:last_period + 1].strip()
    last_space = truncated.rfind(' ')
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip('.,;: ') + '...'


def generate_greeting_llm(is_goodbye=False, user_query=""):
    if is_goodbye:
        prompt = f"""You are Medstore assistant.
        User just said goodbye: "{user_query}"
        Write ONE short warm goodbye sentence for a medical store. Vary wording. No quotes, no explanation."""
    else:
        prompt = f"""You are Medstore assistant.
        User just said hello: "{user_query}"
        Write ONE short warm greeting sentence asking how you can help find medical products. Vary wording. No quotes, no explanation."""

    try:
        resp = llm_social.invoke(prompt).content.strip()
        # clean if LLM still echoes instructions
        resp = resp.replace('"','').replace("'", "").strip()
        if "is_goodbye" in resp.lower() or "if" == resp.lower()[:2]:
            # fallback if LLM fails
            return "Goodbye! Have a great day!" if is_goodbye else "Hello! I'm your Medstore assistant. How can I help you today?"
        # take first sentence only
        resp = resp.split("\n")[0]
        if len(resp) > 200:
            resp = resp[:200]
        return resp
    except Exception:
        return "Goodbye! Have a great day!" if is_goodbye else "Hello! I'm your Medstore assistant. How can I help you find medical products today?"

def is_greeting_or_goodbye_llm(q):
    cls = classify_intent_llm(q)
    if cls and cls.get("intent") in ("greeting","goodbye"):
        return cls.get("intent")
    return None


def clean(t):
    t = unescape(str(t).replace("\\n"," ").replace("\n"," "))
    t = re.sub(r'<[^>]+>',' ',t)
    return re.sub(r'\s+',' ',t).strip()

all_cats=set()
for cats in df["Categories"].dropna():
    for part in re.split(r'[,>]',str(cats)):
        p=part.strip().lower()
        if len(p)>2: all_cats.add(p)
all_cats=sorted(all_cats,key=len,reverse=True)


def _to_str(q):
    if isinstance(q,dict):
        for k in ["name","product","title","value","category"]:
            if k in q and isinstance(q[k],str): return q[k]
        for v in q.values():
            if isinstance(v,str): return v
        return str(q)
    return str(q) if q is not None else ""


def row_key(row_or_name):
    if isinstance(row_or_name,str): name_low=row_or_name.lower()
    else:
        try: name_low=row_or_name["Name_lower"]
        except Exception: name_low=str(row_or_name.get("Name","")).lower()
    return re.sub(r'[^a-z0-9]','',name_low)


def row_to_dict(row):
    d=row.to_dict() if hasattr(row,"to_dict") else dict(row)
    return {k:v for k,v in d.items() if not k.startswith("Unnamed") and k not in DROP_COLS}


def rows_to_dicts(rows,excluded_keys=None):
    excluded_keys=excluded_keys or set()
    out=[]; seen=set()
    for r in rows:
        key=row_key(r)
        if key in excluded_keys or key in seen: continue
        seen.add(key); out.append(row_to_dict(r))
    return out


def apply_synonyms(q_low):
    for k,v in SYNONYM_MAP.items():
        q_low = re.sub(rf'\b{re.escape(k)}\b', v, q_low)
    return q_low


def extract_exclusion(q_low):
    q_low=q_low.lower()
    for kw in sorted(EXCLUSION_KEYWORDS,key=len,reverse=True):
        if kw in q_low:
            idx=q_low.find(kw); main_part=q_low[:idx].strip(); after=q_low[idx+len(kw):].strip()
            parts=re.split(r'\s+and\s+|\s*,\s*|\s+or\s+',after)
            excluded=[]
            for p in parts:
                p=re.sub(r'[^\w\s\-]','',p).strip()
                if len(p)>=3: excluded.append(p)
            return main_part,excluded
    return q_low,[]


def get_excluded_keys(excluded_phrases):
    excluded_keys=set()
    for phrase in excluded_phrases:
        for r in fuzzy_find_products(phrase,limit=5): excluded_keys.add(row_key(r))
    return excluded_keys


def strip_detail_words(q_low):
    q=re.sub(r'\b(what|is|are|the|of|for|me|please|tell|show|give)\b',' ',q_low)
    q=re.sub(r'\b(price|cost|rate|pricing|stock|availability|image|images|photo|description|detail|details)\b',' ',q)
    q=re.sub(r'\s+',' ',q).strip()
    return q


def detect_detail_intent(q_low):
    q = q_low.lower().strip()
    q_clean = re.sub(r'[^\w\s]', '', q).strip()
    if q_clean in all_cats:
        return None
    if re.search(r'\bprice\b|\bcost\b|\brate\b|\bpricing\b|\bhow much\b', q):
        return "price"
    if re.search(r'\bin stock\b|\bout of stock\b|\bavailability\b|\bstock\b', q):
        return "stock"
    if re.search(r'\bimages?\b|\bphotos?\b|\bpicture\b', q):
        return "images"
    if re.search(r'\bdescription\b', q):
        return "description"
    if re.search(r'\bcategories\b|\bcategory\b', q):
        return "categories"
    if re.search(r'\bmodel\b', q):
        return "model"
    if re.search(r'\btags?\b', q):
        return "tags"
    return None


# ============================================================
# #1 PRICE FILTER
# ============================================================
def extract_price_constraint(q_low):
    """Returns dict: {mode: 'max'|'min'|'range'|'cheapest'|'expensive', value/low/high}"""
    q = q_low.replace("euros","euro").replace("€","euro ")
    if re.search(r'\bcheapest\b|\blowest price\b|\bleast expensive\b', q):
        return {"mode":"cheapest"}
    if re.search(r'\bmost expensive\b|\bhighest price\b|\bexpensive\b|\bpricest\b', q):
        return {"mode":"expensive"}
    m = re.search(r'between\s+(\d+(?:\.\d+)?)\s*(?:euro|eur)?\s*and\s+(\d+(?:\.\d+)?)', q)
    if m:
        return {"mode":"range","low":float(m.group(1)),"high":float(m.group(2))}
    m = re.search(r'(?:under|below|less than|cheaper than|up to)\s*(?:euro\s*)?(\d+(?:\.\d+)?)', q)
    if m:
        return {"mode":"max","value":float(m.group(1))}
    m = re.search(r'(?:above|over|more than|greater than)\s*(?:euro\s*)?(\d+(?:\.\d+)?)', q)
    if m:
        return {"mode":"min","value":float(m.group(1))}
    return None


def apply_price_filter(rows, constraint):
    if not constraint or not rows:
        return rows
    def price_of(r):
        v = r.get("_effective_price") if isinstance(r, dict) else r["_effective_price"]
        return v
    mode = constraint["mode"]
    if mode == "max":
        return [r for r in rows if pd.notna(price_of(r)) and price_of(r) <= constraint["value"]]
    if mode == "min":
        return [r for r in rows if pd.notna(price_of(r)) and price_of(r) >= constraint["value"]]
    if mode == "range":
        return [r for r in rows if pd.notna(price_of(r)) and constraint["low"] <= price_of(r) <= constraint["high"]]
    if mode == "expensive":
        valid = [r for r in rows if pd.notna(price_of(r))]
        return sorted(valid, key=price_of, reverse=True)[:10]
    if mode == "cheapest":
        valid = [r for r in rows if pd.notna(price_of(r))]
        return sorted(valid, key=price_of)[:10]
    return rows


# ============================================================
# #2 STOCK FILTER
# ============================================================
def extract_stock_constraint(q_low):
    if re.search(r'\bout of stock\b|\bnot in stock\b|\bunavailable\b|\bbackorder\b', q_low):
        return False
    if re.search(r'\bin stock\b|\bavailable\b', q_low):
        return True
    return None


def apply_stock_filter(rows, wants_in_stock):
    if wants_in_stock is None or not rows:
        return rows
    def in_stock_of(r):
        return r.get("_in_stock") if isinstance(r, dict) else r["_in_stock"]
    return [r for r in rows if bool(in_stock_of(r)) == wants_in_stock]


# ============================================================
# #3 ATTRIBUTE / MODEL / COLOR / SIZE FILTER
# ============================================================
def extract_attribute_terms(q_low):
    terms = []
    for m in re.finditer(r'\b[a-z]{1,4}-?\d{2,4}[a-z0-9-]*\b', q_low):
        # looks like a model code, e.g. zkm-128-k, w4701
        if any(ch.isdigit() for ch in m.group(0)):
            terms.append(m.group(0))
    for c in COLOR_WORDS:
        if re.search(rf'\b{c}\b', q_low):
            terms.append(c)
    for s in SIZE_WORDS:
        if re.search(rf'\b{re.escape(s)}\b', q_low) and len(s) > 1:
            terms.append(s)
    m = re.search(r'(\d+)\s*inch', q_low)
    if m:
        terms.append(m.group(0))
    return list(dict.fromkeys(terms))  # dedupe, keep order


def apply_attribute_filter(rows, terms):
    if not terms or not rows:
        return rows
    out = []
    for r in rows:
        d = r if isinstance(r, dict) else r.to_dict()
        haystack = " ".join(str(d.get(k,"")) for k in
                             ["Name","Description","Short description","Attribute 1 value(s)","Tags"]).lower()
        if any(t in haystack for t in terms):
            out.append(r)
    return out


# ============================================================
# #7 COUNTING
# ============================================================
def is_count_query(q_low):
    return bool(re.search(r'\bhow many\b|\bhow much\b\s+of|\bcount of\b|\bnumber of\b|\bdo you have any\b', q_low))


# ============================================================
# #4 POLICY / ADVICE
# ============================================================
def detect_policy_query(q_low):
    for kw in POLICY_KEYWORDS:
        if kw in q_low:
            return True
    return False

def detect_advice_query(q_low):
    for kw in ADVICE_KEYWORDS:
        if kw in q_low:
            return True
    return False


def classify_intent_llm(user_query: str):
    prompt = f"""
    You classify user messages for a medical store.
    User: "hi" -> {{"intent":"greeting","products":[],"category":null,"detail":null}}
    User: "hello" -> {{"intent":"greeting","products":[],"category":null,"detail":null}}
    User: "bye" -> {{"intent":"goodbye","products":[],"category":null,"detail":null}}
    User: "thank you" -> {{"intent":"goodbye","products":[],"category":null,"detail":null}}
    User: "thanks" -> {{"intent":"goodbye","products":[],"category":null,"detail":null}}
    User: "thank you so much" -> {{"intent":"goodbye","products":[],"category":null,"detail":null}}
    User: "Transit Chair" -> {{"intent":"single_product","products":["Transit Chair"],"category":null,"detail":null}}
    User: "price of transit chair" -> {{"intent":"specific_detail","products":["Transit Chair"],"category":null,"detail":"price"}}
    User: "difference between the transit chair and trauma head" -> {{"intent":"comparison","products":["Transit Chair","Trauma Head"],"category":null,"detail":null}}
    User: "emergency" -> {{"intent":"category_search","products":[],"category":"emergency","detail":null}}
    User: "suggest emergency chairs" -> {{"intent":"suggestion","products":[],"category":"emergency","detail":null}}
    User: "compare Transit Chair and Tri Wheel Transit Chair" -> {{"intent":"comparison","products":["Transit Chair","Tri Wheel Transit Chair"],"category":null,"detail":null}}
    Now classify:
    User: "{user_query}" ->
    Return ONLY JSON, no explanation.
    """
    try:
        resp=llm_creative.invoke(prompt).content.strip()
        m=re.search(r'\{.*\}',resp,re.DOTALL)
        if not m: return None
        return json.loads(m.group(0))
    except Exception: return None


def fuzzy_find_products(query_text, limit=10):
    query_text = _to_str(query_text)
    q_low = query_text.lower().strip()
    if len(q_low) < 2:
        return []
    if all(w in GENERIC_WORDS for w in q_low.split() if len(w)>=2):
        return []

    # 1. exact match
    exact = df[df["Name_lower"] == q_low]
    if not exact.empty:
        return [exact.iloc[0]]

    # 2. product names inside query - FIXED: collect ALL, not return after first
    # "price of Minor Delivery Set and transit chair" -> should return both
    found_in_query = []
    seen_keys = set()
    # sort by length desc so longer names matched first (Minor Delivery Set before Delivery)

    # df_sorted = df.sort_values(by="Name_lower", key=lambda x: x.str.len(), ascending=False)
    for _, r in DF_SORTED_BY_NAME_LEN.iterrows():
        nl = r["Name_lower"]
        if len(nl) >= 3 and nl in q_low:
            key = row_key(r)
            if key not in seen_keys:
                seen_keys.add(key)
                found_in_query.append(r)
    if found_in_query:
        # if query contains 2 product names separated by "and", return both
        return found_in_query[:limit]

    q_words = [w for w in re.split(r'[^a-z0-9]+', q_low) if len(w) >= 2]
    if not q_words:
        return []

    results = []
    coverage_results = [] 
    seen = set()

    for _, r in df.iterrows():
        name = r["Name_lower"]
        cats = r["Categories_lower"]
        desc = r["Description_lower"]
        combined = f"{name} {cats} {desc}"

        # substring match
        if q_low in name or q_low in cats or q_low in desc:
            key = row_key(r)
            if key not in seen:
                seen.add(key)
                if q_low in name:
                    name_words = name.split()
                    if q_low == name_words[0]:
                        score = 1.0
                    elif re.search(rf'\b{re.escape(q_low)}\b', name):
                        score = 0.90
                    else:
                        score = 0.80
                elif q_low in desc:
                    score = 0.75
                else:
                    score = 0.70
                results.append((r, score))
            continue

        # word coverage with typo tolerance
        combined_words = [w for w in re.split(r'[^a-z0-9]+', combined) if len(w) >= 2]
        matched = 0
        for qw in q_words:
            for cw in combined_words:
                if qw == cw or (len(qw) >= 3 and qw in cw) or difflib.SequenceMatcher(None, qw, cw).ratio() >= 0.9:
                    matched += 1
                    break
        q_cov = matched / len(q_words) if q_words else 0
        if q_cov >= 0.5:
            key = row_key(r)
            if key not in seen:
                seen.add(key)
                coverage_results.append((r, q_cov))

    final = results if results else coverage_results
    if final:
        final = sorted(final, key=lambda x: x[1], reverse=True)
        return [r for r,_ in final[:limit]]

    # 4. semantic fallback for abbreviations like bp -> blood pressure
    if db is not None:
        try:
            docs = db.similarity_search_with_score(query_text, k=limit)
            for doc, score in docs:
                # print(f"SCORE: {score:.4f} | {doc.page_content[:80]} | row={doc.metadata.get('row')}")
                if score > 0.65:
                    continue
                try:
                    row = df.iloc[int(doc.metadata.get("row"))]
                except Exception:
                    continue
                key = row_key(row)
                if key not in seen:
                    seen.add(key)
                    results.append((row, 1-score))
        except Exception:
            pass

    results = sorted(results, key=lambda x: x[1], reverse=True)
    return [r for r,_ in results[:limit]]


def fuzzy_find_categories(query_text,limit=5):
    query_text=_to_str(query_text)
    if len(query_text.strip())<3: return []
    q_low=query_text.lower().strip()

    # if query is clearly a product term like "forceps", don't fuzzy-match categories
    # only allow exact substring: query in cat or cat in query
    if len(q_low) <= 8:
        matched = []
        for cat in all_cats:
            if q_low == cat or q_low in cat.split() or cat in q_low:
                matched.append(cat)
        return matched[:limit]

    q_words=[w for w in q_low.split() if len(w)>=3 and w not in GENERIC_WORDS and w not in DETAIL_KEYWORDS]
    if not q_words: return []
    scored=[]; seen=set()
    for cat in all_cats:
        if cat in q_low or q_low in cat:
            if cat not in seen:
                seen.add(cat); scored.append((cat,1.0,True))
            continue
        cat_words=[w for w in re.split(r'[^a-z0-9]+', cat) if len(w)>=3]
        if not cat_words: continue
        match_count=0; exact_hit=False
        for cw in cat_words:
            for qw in q_words:
                if cw==qw: match_count+=1; exact_hit=True; break
                if len(cw)>=4 and len(qw)>=4 and (cw in qw or qw in cw): match_count+=1; break
        ratio=match_count/len(cat_words) if cat_words else 0
        if ratio>=0.8 and exact_hit: # was 0.6 - too loose
            if cat not in seen: seen.add(cat); scored.append((cat,ratio,exact_hit))

    # increase cutoff from 0.6 to 0.85 to avoid forceps->forensics
    close=difflib.get_close_matches(q_low,all_cats,n=5,cutoff=0.85)
    for c in close:
        if c not in seen: seen.add(c); scored.append((c,0.5,False))
    scored.sort(key=lambda x:(x[2],x[1]),reverse=True)
    return [c for c,_,_ in scored][:limit]


def get_products_by_categories(cats,limit=1000):
    rows=[]; seen=set()
    for cat in cats:
        matches=df[df["Categories_lower"].str.contains(re.escape(cat),na=False,regex=True)]
        for _,r in matches.iterrows():
            key=row_key(r)
            if key not in seen: seen.add(key); rows.append(r)
        if len(rows)>=limit: break
    return rows[:limit]


def get_random_products(limit=10):
    try:
        sample_df=df.sample(n=min(limit,len(df))); return [r for _,r in sample_df.iterrows()]
    except Exception: return [r for _,r in df.head(limit).iterrows()]


def random_products_response(excluded_keys,excluded_phrases,tries=5,pool=15,show=10):
    filtered_rows=[]
    for _ in range(tries):
        candidate_rows=get_random_products(limit=pool)
        filtered_rows=[r for r in candidate_rows if row_key(r) not in excluded_keys]
        if len(filtered_rows)>=5: break
    prod_dicts=rows_to_dicts(filtered_rows[:show],excluded_keys)
    suffix=f" excluding {', '.join(excluded_phrases)}" if excluded_phrases else ""
    names=', '.join(p['Name'] for p in prod_dicts[:5])
    return {"answer":f"Here are some products from Medstore{suffix}: {names}","products":prod_dicts}


def build_detail_answer(product,detail):
    detail=_to_str(detail)
    if not detail or detail.lower() in ["null","none",""]:
        return clean(product.get('Description','')+' '+product.get('Short description',''))[:700]
    d=detail.lower()
    if d=="price": return f"{product['Name']} - Regular price: €{product.get('Regular price','N/A')} | Sale price: {product.get('Sale price','') or 'N/A'}"
    if d=="stock": return f"{product['Name']} - In stock: {product.get('In stock?','N/A')}"
    if d=="images": return f"{product['Name']} - Images: {product.get('Images','N/A')}"
    if d=="description": return f"{product['Name']} - {clean(product.get('Description','')+' '+product.get('Short description',''))[:700]}"
    if d=="categories": return f"{product['Name']} - Categories: {product.get('Categories','N/A')}"
    if d=="model": return f"{product['Name']} - {product.get('Attribute 1 name','Model')}: {product.get('Attribute 1 value(s)','N/A')}"
    if d=="tags": return f"{product['Name']} - Tags: {product.get('Tags','N/A')}"
    return summarize_text(product.get('Description',''))[:200]


def generate_difference_llm(products, user_query):
    # products = list of rows
    ctx = ""
    for p in products[:2]:
        ctx += f"""
    Product: {p.get('Name')}
    Price: €{p.get('Regular price')} Sale: €{p.get('Sale price')}
    Categories: {p.get('Categories')}
    Description: {clean(p.get('Short description','')+' '+p.get('Description',''))[:600]}
    ---
    """
    prompt = f"""You are Medstore assistant.
    User asks: "{user_query}"
    Here are products:
    {ctx}
    Explain the difference between them in simple layman terms - what each is used for, price difference, category difference.
    Keep it 3-4 sentences, friendly.
    If you don't know, say "I don't have detailed difference".

    Return ONLY the answer, no JSON."""
    try:
        resp = llm_creative.invoke(prompt).content.strip()
        if not resp or len(resp) < 20 or "don't have" in resp.lower():
            return None
        return resp
    except Exception:
        return None


def full_product_answer(p):
    return (f"{clean(p.get('Description','')+' '+p.get('Short description',''))[:700]} | Price: €{p.get('Regular price','') or 'N/A'} | Sale price: {p.get('Sale price','') or 'N/A'} | Stock: {p.get('In stock?','N/A')} | Category: {p.get('Categories','N/A')} | {p.get('Attribute 1 name','Model')}: {p.get('Attribute 1 value(s)','N/A')}")


def is_generic_query(text):
    words=[w for w in text.strip().lower().split() if len(w)>=2]
    return bool(words) and all(w in GENERIC_WORDS for w in words)


def validate_llm_entities(names,q_low):
    valid=[]
    for n in names:
        n_low=_to_str(n).lower()
        words=[w for w in n_low.split() if len(w)>=3]
        if words and any(w in q_low for w in words): valid.append(n)
    return valid


# ============================================================
# #5 FOLLOW-UP DETECTION
# ============================================================
FOLLOWUP_PATTERNS = [
    r'\bcheaper\b', r'\bmore expensive\b', r'\bpricier\b',
    r'\bwhat about\b', r'\band its\b', r'\bwhat is its\b', r'\bthat one\b',
    r'\bin (red|blue|black|white|green|yellow|grey|gray|pink|orange|brown)\b',
    r'^\s*and\b',
]

def is_followup_query(q_low, has_own_product_mention):
    if has_own_product_mention:
        return False
    return any(re.search(p, q_low) for p in FOLLOWUP_PATTERNS)


@router.get("/query")
def ask_rag_bot(user_query: str, session_id: str = "default"):
    q = user_query.strip(); q_low = q.lower().strip()
    if not q_low:
        return {"answer": generate_greeting_llm(False, q), "products": []}

    quick_product_hit = fuzzy_find_products_cached(q_low, limit=1)

    # fast-path heuristic FIRST — only fall back to the LLM when heuristics are unsure
    q_clean_cat = re.sub(r'[^\w\s>]', '', q_low).strip()
    heuristic_detail = detect_detail_intent(q_low)
    is_exact_product_fast = q_low in df["Name_lower"].values

    if is_exact_product_fast and not heuristic_detail:
        cls_early = {"intent": "single_product", "products": [q], "category": None, "detail": None}
    elif q_clean_cat in all_cats:
        cls_early = {"intent": "category_search", "products": [], "category": q_clean_cat, "detail": None}
    else:
        cls_early = classify_intent_llm_cached(q)

    if cls_early and cls_early.get("intent") == "greeting":
        if not quick_product_hit:
            return {"answer": generate_greeting_llm(False, q), "products": []}
    if cls_early and cls_early.get("intent") == "goodbye":
        if q_low in ["thank you","thanks","thank you so much","thanks a lot","thx","ty"] or not quick_product_hit:
            return {"answer": generate_greeting_llm(True, q), "products": []}

    state = SESSION_STATE.setdefault(session_id, {"last_products": [], "last_cats": []})

    # --- #4 policy questions: answer honestly, we don't have this data ---
    if detect_policy_query(q_low):
        return {"answer":"I don't have delivery, warranty, or returns policy details here - please contact Medstore support directly for that.","products":[]}

    advice_prefix = ""
    if detect_advice_query(q_low):
        advice_prefix = "I can't give medical advice or personal recommendations, but here's what I have in our catalogue: "

    # --- synonym expansion (#9: bp -> blood pressure) ---
    q_low = apply_synonyms(q_low)

    main_q,excluded_phrases=extract_exclusion(q_low)
    excluded_keys=get_excluded_keys(excluded_phrases) if excluded_phrases else set()
    query_for_intent=main_q if excluded_phrases else q
    search_q=main_q if excluded_phrases else q_low

    # --- 5. Filters extracted (but not applied yet) ---
    price_constraint = extract_price_constraint(search_q)
    stock_constraint = extract_stock_constraint(search_q)
    attribute_terms = extract_attribute_terms(search_q)
    count_query = is_count_query(search_q)

    core_q = search_q
    core_q = re.sub(r'(under|below|less than|cheaper than|up to|above|over|more than|greater than)\s*(?:euro\s*)?\d+(\.\d+)?', ' ', core_q)
    core_q = re.sub(r'between\s+\d+(\.\d+)?\s*(?:euro|eur)?\s*and\s+\d+(\.\d+)?', ' ', core_q)
    core_q = re.sub(r'\bcheapest\b|\bmost expensive\b|\blowest price\b|\bhighest price\b', ' ', core_q)
    core_q = re.sub(r'\bin stock\b|\bout of stock\b|\bavailable\b|\bunavailable\b|\bbackorder\b', ' ', core_q)
    core_q = re.sub(r'\s+', ' ', core_q).strip()
    if not core_q:
        core_q = search_q

    # --- #5 follow-up handling ---
    resolved_products_pre = fuzzy_find_products(core_q, limit=100)

    price_filter_old = extract_price_filter(search_q) # ("<",200)

    # --- PRICE-ONLY: "show products under 200" ---
    # core_q will be "show products" after stripping numbers
    if price_filter_old:
        cleaned_for_generic = re.sub(r'\bexpensive\b|\bcheap\b|\bcheapest\b|\bmost expensive\b', '', core_q).strip()
        is_generic = is_generic_query(core_q) or is_generic_query(cleaned_for_generic) or cleaned_for_generic.lower() in ["show products", "products", "show me products", "", "show", "show expensive", "show cheap"]
        has_no_product = not resolved_products_pre and not fuzzy_find_categories(core_q)
        if is_generic and has_no_product:
            pool = [r for _, r in df.iterrows()]
            pool = apply_old_price_filter(pool, price_filter_old)
            prod_dicts = rows_to_dicts(pool[:10], excluded_keys)
            if prod_dicts:
                state["last_products"] = pool
                if price_filter_old[0] == "<":
                    label = f"under €{price_filter_old[1]}"
                elif price_filter_old[0] == ">":
                    label = f"over €{price_filter_old[1]}"
                elif price_filter_old[0] == "between":
                    label = f"between €{price_filter_old[1]} and €{price_filter_old[2]}"
                else:
                    label = "matching price filter"
                return {"answer": f"Found {len(pool)} products {label}: {', '.join(p['Name'] for p in prod_dicts[:5])}", "products": prod_dicts}
    

    if is_generic_query(core_q) and not price_constraint and not stock_constraint:
        return random_products_response(excluded_keys,excluded_phrases)

    has_own_mention = bool(resolved_products_pre) or bool(fuzzy_find_categories(core_q))
    if is_followup_query(q_low, has_own_mention) and (state["last_products"] or state["last_cats"]):
        pool = state["last_products"] or get_products_by_categories(state["last_cats"], limit=100)
        pool = apply_price_filter(pool, price_constraint) if price_constraint else pool
        pool = apply_stock_filter(pool, stock_constraint) if stock_constraint is not None else pool
        pool = apply_attribute_filter(pool, attribute_terms) if attribute_terms else pool
        if re.search(r'\bcheaper\b', q_low) and not price_constraint:
            valid = [r for r in pool if pd.notna(r["_effective_price"])]
            pool = sorted(valid, key=lambda r: r["_effective_price"])[:5]
        if re.search(r'\bmore expensive\b|\bpricier\b', q_low) and not price_constraint:
            valid = [r for r in pool if pd.notna(r["_effective_price"])]
            pool = sorted(valid, key=lambda r: -r["_effective_price"])[:5]
        prod_dicts = rows_to_dicts(pool[:10], excluded_keys)
        if prod_dicts:
            state["last_products"] = pool
            answer = advice_prefix + ("Here you go: " + ", ".join(p["Name"] for p in prod_dicts[:5]))
            return {"answer": answer, "products": prod_dicts}
        return {"answer":"I couldn't find a matching alternative for that follow-up - could you name the product or category?","products":[]}

    if q_clean_cat in all_cats:
        cls = {"intent":"category_search","products":[],"category":q_clean_cat,"detail":None}
    else:
        heuristic_detail = detect_detail_intent(core_q)
        if excluded_phrases:
            # query_for_intent (main_q) differs from q, so cls_early doesn't apply — need a fresh call
            cls = classify_intent_llm(query_for_intent)
        else:
            # query_for_intent == q, so we already classified this exact string above — reuse it
            cls = cls_early
        if cls is None:
            cls={"intent":"specific_detail" if heuristic_detail else "single_product",
                 "products":[strip_detail_words(query_for_intent)],
                 "category":None,
                 "detail":heuristic_detail}

    intent=cls.get("intent","single_product")

    if intent == "category_search":
        detail = None
    else:
        detail = cls.get("detail") or detect_detail_intent(core_q)

    mentioned_products=validate_llm_entities(cls.get("products",[]) or [], q_low)
    if not mentioned_products:
        mentioned_products=[strip_detail_words(core_q)]

    mentioned_category_raw=cls.get("category")
    mentioned_category=(mentioned_category_raw if mentioned_category_raw and validate_llm_entities([mentioned_category_raw],q_low) else None)

    # --- resolve products ---
    resolved_products=[]
    seen=set()
    for pname in mentioned_products:
        for r in fuzzy_find_products(pname, limit=100):
            key = row_key(r)
            if key not in seen and key not in excluded_keys:
                seen.add(key); resolved_products.append(r)
    if not resolved_products:
        cleaned_search = strip_detail_words(core_q)
        tmp = fuzzy_find_products(cleaned_search or core_q, limit=100)
        resolved_products = [r for r in tmp if row_key(r) not in excluded_keys]

    # --- #9 FIX: always resolve categories in parallel, never gated
    # solely behind LLM's intent label ---
    resolved_cats = fuzzy_find_categories(mentioned_category) if mentioned_category else []
    if not resolved_cats:
        resolved_cats = fuzzy_find_categories(core_q)

    # a category is "strong" if the query is basically the category itself,
    # or matches were found and we don't have a single dominant product hit
    strong_category = bool(resolved_cats) and (
        (q_clean_cat in all_cats and len(resolved_products) < 3) or
        (intent == "category_search" and len(resolved_products) < 5)
    )

    is_exact_product = q_low in df["Name_lower"].values or strip_detail_words(q_low) in df["Name_lower"].values

    if is_exact_product and intent!="comparison" and not (intent=="specific_detail" and detail):
        exact_q = q_low if q_low in df["Name_lower"].values else strip_detail_words(q_low)
        exact_row = df[df["Name_lower"]==exact_q].iloc[0]
        if row_key(exact_row) not in excluded_keys:
            state["last_products"] = [exact_row]
            return {"answer":full_product_answer(exact_row),"products":rows_to_dicts([exact_row],excluded_keys)}

    # --- #1/#2/#3/#6: apply combinable filters to whichever pool wins ---
    def finalize(pool, label):
        pool = apply_price_filter(pool, price_constraint) if price_constraint else pool
        pool = apply_stock_filter(pool, stock_constraint) if stock_constraint is not None else pool
        pool = apply_attribute_filter(pool, attribute_terms) if attribute_terms else pool
        pool = pool[:10]
        prod_dicts = rows_to_dicts(pool, excluded_keys)
        state["last_products"] = pool
        state["last_cats"] = resolved_cats
        if count_query:
            return {"answer": f"There are {len(prod_dicts)} {label} matching your query.", "products": prod_dicts[:10]}
        if not prod_dicts:
            return None
        if len(prod_dicts) == 1:
            p = pool[0]
            return {"answer": advice_prefix + full_product_answer(p), "products": [prod_dicts[0]]}
        names = ", ".join(p["Name"] for p in prod_dicts[:5])
        suffix = f" (+{len(prod_dicts)-5} more)" if len(prod_dicts) > 5 else ""
        return {"answer": advice_prefix + f"Found {len(prod_dicts)} {label}: {names}{suffix}", "products": prod_dicts[:10]}

    # SPECIFIC DETAIL wins first (never for category_search)
    if intent != "category_search" and (intent=="specific_detail" or detail) and resolved_products and not (price_constraint or stock_constraint or attribute_terms or count_query):
        if len(resolved_products) > 1:
            answers = [build_detail_answer(p, detail) for p in resolved_products[:5]]
            prod_dicts = rows_to_dicts(resolved_products[:5], excluded_keys)
            state["last_products"] = resolved_products[:5]
            return {"answer": " | ".join(answers), "products": prod_dicts}
        else:
            prod = resolved_products[0]
            answer = build_detail_answer(prod, detail)
            prod_dicts = rows_to_dicts([prod], excluded_keys)
            state["last_products"] = [prod]
            return {"answer":answer,"products":prod_dicts}

    if intent=="comparison" and len(resolved_products)>=2:
        prod_dicts = rows_to_dicts(resolved_products[:3], excluded_keys)
        # try LLM first
        llm_answer = generate_difference_llm(resolved_products[:2], q)
        if llm_answer:
            state["last_products"] = resolved_products[:3]
            return {"answer": llm_answer, "products": prod_dicts}
        else:
            # fallback - short description + price as you asked
            fallback = []
            for p in resolved_products[:2]:
                fallback.append(f"{p['Name']} - {clean(p.get('Short description','') or p.get('Description',''))[:250]} | Price: €{p.get('Regular price','N/A')}")
            state["last_products"] = resolved_products[:3]
            return {"answer": " | ".join(fallback), "products": prod_dicts}

    if strong_category:
        cat_prods = get_products_by_categories(resolved_cats[:2], limit=200)
        result = finalize(cat_prods, f"products in category '{resolved_cats[0]}'")
        if result: return result

    if intent=="suggestion":
        if resolved_cats:
            cat_prods = get_products_by_categories(resolved_cats[:2], limit=10)
            prod_dicts = rows_to_dicts(cat_prods[:10], excluded_keys)
            if prod_dicts:
                state["last_products"] = cat_prods
                return {"answer":f"Here are suggestions in '{resolved_cats[0]}': {', '.join(p['Name'] for p in prod_dicts[:5])}","products":prod_dicts}
        if resolved_products:
            base_cat = resolved_products[0]["Categories"].split(",")[0].split(">")[0].strip().lower()
            similar = get_products_by_categories([base_cat], limit=10)
            prod_dicts = rows_to_dicts(similar[:10], excluded_keys)
            if prod_dicts:
                state["last_products"] = similar
                return {"answer":f"Based on '{resolved_products[0]['Name']}', you might like: {', '.join(p['Name'] for p in prod_dicts[:5])}","products":prod_dicts}
        return random_products_response(excluded_keys, excluded_phrases)

    if resolved_products:
        result = finalize(resolved_products, "products")
        if result: return result

    if resolved_cats:
        cat_prods = get_products_by_categories(resolved_cats[:2], limit=10)
        result = finalize(cat_prods, f"products in category '{resolved_cats[0]}'")
        if result: return result

    if any(phrase in q_low for phrase in ["show me","show some","list","some products","all products","products"]):
        return random_products_response(excluded_keys, excluded_phrases)

    # --- #8: not in our catalogue at all, vs generic catch-all ---
    return {"answer":"We don't currently have that item in our catalogue. Try searching by category, e.g. 'wheelchairs' or 'blood pressure monitors'.","products":[]}