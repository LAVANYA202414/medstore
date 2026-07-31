from fastapi import APIRouter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import pandas as pd

router = APIRouter()

# Load CSV once
df = pd.read_csv("products.csv").fillna("")

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
from langchain_core.prompts import ChatPromptTemplate
import pandas as pd

router = APIRouter()

df = pd.read_csv("products.csv").fillna("")
embedding_function = OllamaEmbeddings(model="all-minilm")
llm = ChatOllama(model="llama3.2", temperature=0.3)

@router.get("/query")
def ask_rag_bot(user_query: str):
    vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_function)
    results = vector_db.similarity_search_with_score(user_query, k=10)

    # 1. General chat (not related to products)
    if not results or results[0][1] > 1.2:
        prompt = ChatPromptTemplate.from_template("You are a helpful medical store assistant. User: {q} Answer friendly.")
        res = (prompt | llm).invoke({"q": user_query})
        return {"answer": res.content, "products": []}

    # 2. Detect if it's category query or specific product query
    q_lower = user_query.lower()
    is_category_query = any(word in q_lower for word in ["models", "products", "show", "list", "all", "categories", "gloves", "anatomical"])

    if is_category_query:
        k_to_show = 5
    else:
        k_to_show = 1

    products = []
    for doc, score in results:
        row_num = doc.metadata.get("row")
        if row_num is None:
            continue
        try:
            product_data = df.iloc[int(row_num)].to_dict()
            if not str(product_data.get("Name")).strip():
                continue
            products.append(product_data)
            if len(products) >= k_to_show:
                break
        except:
            continue

    if not products:
        return {"answer": "Sorry, I couldn't find that.", "products": []}

    # 3. Generate answer
    if is_category_query:
        product_list_text = "\n".join([f"- {p['Name']} (${p['Regular price']})" for p in products])
        prompt = ChatPromptTemplate.from_template("""
        User asked: {q}
        We found these products:
        {plist}
        Answer like a chatbot: Say we have {count} products related to {q}, list them briefly.
        """)
        chain = prompt | llm
        response = chain.invoke({"q": user_query, "plist": product_list_text, "count": len(products)})
    else:
        main = products[0]
        prompt = ChatPromptTemplate.from_template("""
        User: {q}
        Product: {name}, Price: {price}, Desc: {desc}
        Answer friendly about this specific product.
        """)
        chain = prompt | llm
        response = chain.invoke({"q": user_query, "name": main.get("Name"), "price": main.get("Regular price"), "desc": main.get("Description")})

    return {
        "answer": response.content,
        "products": products
    }