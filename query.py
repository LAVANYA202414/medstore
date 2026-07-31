# from fastapi import APIRouter
# from langchain_chroma import Chroma
# from langchain_ollama import OllamaEmbeddings
# import pandas as pd

# router = APIRouter()

# # Load CSV once
# df = pd.read_csv("products.csv").fillna("")

# @router.get("/query")
# def ask_rag_bot(user_query: str):
#     embedding_function = OllamaEmbeddings(model="all-minilm")
#     vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_function)
    
#     results = vector_db.similarity_search_with_score(user_query, k=10)
    
#     products = []
#     for doc, score in results:
#         row_num = doc.metadata.get("row")
#         if row_num is None:
#             continue
#         try:
#             # Get full product data from CSV by row number
#             product_data = df.iloc[int(row_num)].to_dict()
            
#             # skip empty Name
#             if not str(product_data.get("Name")).strip():
#                 continue
                
#             products.append(product_data)
            
#             if len(products) >= 5:
#                 break
#         except:
#             continue

#     return {
#         "products": products
#     }





from fastapi import APIRouter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
import pandas as pd
import re
from html import unescape

router = APIRouter()

df = pd.read_csv("products.csv").fillna("")
embed = OllamaEmbeddings(model="all-minilm")
llm = ChatOllama(model="llama3.2", temperature=0.3) # llama3.2 ONLY for answer

def strip_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(str(text))
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def get_display_price(row):
    try:
        sale = float(row.get("Sale price") or 0)
        regular = float(row.get("Regular price") or 0)
        if sale > 0 and sale < regular:
            return f"${sale} (was ${regular})"
        if regular > 0:
            return f"${regular}"
        return "Price on Request"
    except:
        return "Price on Request"

@router.get("/query")
def ask_rag_bot(user_query: str):

    # --- 1. PRODUCTS ONLY FROM CHROMA_DB (NO LLAMA) ---
    query_clean = user_query.lower().strip()
    final_products = []

    # Exact name match from CSV (no llama)
    exact = df[df['Name'].str.lower().str.strip() == query_clean]
    if len(exact) == 1:
        final_products = [exact.iloc[0].to_dict()]
    else:
        # Vector search from chroma_db
        db = Chroma(persist_directory="./chroma_db", embedding_function=embed)
        results = db.similarity_search_with_score(user_query, k=20)

        if len(results) == 0 or results[0][1] > 1.2:
            # No products found -> llama handles general chat
            ans = llm.invoke("You are a helpful medical store assistant. User says: " + user_query)
            return {"answer": ans.content, "products": []}

        user_query_small = user_query.lower()
        list_keywords = ["models", "products", "show me", "list", "all products", "all"]
        is_list = any(k in user_query_small for k in list_keywords)
        need = 5 if is_list else 1

        for item in results:
            doc = item[0]
            row = doc.metadata.get("row")
            if row is None:
                continue
            data = df.iloc[int(row)].to_dict()
            if not str(data["Name"]).strip():
                continue

            # Category filter for BP
            if "blood pressure" in user_query_small or " bp " in f" {user_query_small} ":
                cats = str(data.get("Categories", "")).lower()
                name_low = str(data["Name"]).lower()
                if "blood pressure" not in cats and "blood pressure" not in name_low and "b.p." not in name_low and "bpm" not in name_low:
                    continue

            final_products.append(data)
            if len(final_products) == need:
                break

    if len(final_products) == 0:
        ans = llm.invoke("You are a helpful medical store assistant. User says: " + user_query)
        return {"answer": ans.content, "products": []}

    # --- 2. ANSWER ONLY FROM LLAMA3.2 (uses chroma products as context) ---
    if len(final_products) > 1:
        text = ""
        for p in final_products:
            text += f"- {p['Name']} - {get_display_price(p)}\n"
        prompt = f"User asked: {user_query}\nWe have these products from database:\n{text}\nAnswer friendly, list products with prices. Don't invent products."
        ans = llm.invoke(prompt)
    else:
        one = final_products[0]
        clean_desc = strip_html(one.get("Description", ""))[:800]
        prompt = f"User: {user_query}\nProduct Name: {one['Name']}\nPrice: {get_display_price(one)}\nCategories: {one.get('Categories')}\nDescription: {clean_desc}\nExplain in friendly way 2-3 lines."
        ans = llm.invoke(prompt)

    return {
        "answer": ans.content, # from llama3.2
        "products": final_products # from chroma_db only
    }