from fastapi import FastAPI
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

app = FastAPI()

embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory="./chroma_db", embedding_function=embedding_function)

@app.get("/query")
def query_data(q: str):
    results = vector_db.similarity_search_with_score(q, k=10)
    
    available_items = []
    for doc, score in results:
        if score > 1.2:  # too far = nonsense query
            continue
        row = doc.metadata
        if row.get("Published") != "1": continue
        if row.get("Visibility in catalogue") != "visible": continue
        available_items.append(row)

    return {"available_items": available_items, "count": len(available_items), "query": q}