import os
import csv
import traceback
import warnings
from fastapi import FastAPI, HTTPException, Query
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
import ollama

# Suppress the Hugging Face Hub warning messages and deprecations
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

app = FastAPI()

PERSIST_DIR = "./chroma_db"
CSV_FILE_PATH = "/home/lavanya/Desktop/Lavanya/med_store/products.csv"

# Global embedding function and database variables
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vector_db = Chroma(persist_directory=PERSIST_DIR, embedding_function=embedding_function)


@app.post("/ingest")
def ingest_csv():
    try:
        if not os.path.exists(CSV_FILE_PATH):
            raise HTTPException(status_code=404, detail="CSV file not found at the specified path.")

        documents = []
        # Using utf-8-sig automatically strips BOM marks (\ufeff) if present in the CSV
        with open(CSV_FILE_PATH, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=",", quotechar='"')
            for row_idx, row in enumerate(reader):
                # Format page content dynamically, ignoring empty or null values
                row_text = "\n".join([f"{col}: {val}" for col, val in row.items() if val])
                doc = Document(page_content=row_text, metadata={"source": CSV_FILE_PATH, "row": row_idx})
                documents.append(doc)

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_documents(documents)
        print(f"Total chunks created: {len(chunks)}")

        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            print(f"Ingesting batch {i // batch_size + 1} ({len(batch)} chunks)")
            vector_db.add_documents(batch)

        return {"message": f"Successfully ingested {len(chunks)} chunks into the system"}

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.get("/query")
def ask_rag_bot(user_query: str = Query(..., description="The question for the RAG bot")):
    try:
        # Querying the local vector database for relevant context chunks
        results = vector_db.similarity_search(user_query, k=5)
        
        if not results:
            return {"response": "No matching context found in the database."}
            
        context = "\n\n".join([doc.page_content for doc in results])
        
        system_prompt = f"""You are a professional, helpful hospital inventory assistant. 
Answer the user's question using ONLY the provided context below.
Identify and list all relevant machines or products mentioned.
If you do not know the answer based on the context, say "Information not available".
Do not use external knowledge or invent facts.

CONTEXT:
{context}"""

        # Fixed parameter signature: 'role' keys inside 'messages' array
        response = ollama.chat(
            model="llama3.2",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query} 
            ]
        )
        
        return {"response": response['message']['content']}
        
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("Starting FastAPI app on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
