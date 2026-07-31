from fastapi import APIRouter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import pandas as pd

router = APIRouter()

# Load CSV once
df = pd.read_csv("products.csv").fillna("")

@router.get("/query")
def ask_rag_bot(user_query: str):
    embedding_function = OllamaEmbeddings(model="all-minilm")
    vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_function)
    
    results = vector_db.similarity_search_with_score(user_query, k=10)
    
    products = []
    for doc, score in results:
        row_num = doc.metadata.get("row")
        if row_num is None:
            continue
        try:
            # Get full product data from CSV by row number
            product_data = df.iloc[int(row_num)].to_dict()
            
            # skip empty Name
            if not str(product_data.get("Name")).strip():
                continue
                
            products.append(product_data)
            
            if len(products) >= 5:
                break
        except:
            continue

    return {
        "products": products
    }


