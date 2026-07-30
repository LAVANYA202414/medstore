from fastapi import FastAPI, HTTPException, Query
from langchain_community.document_loaders.csv_loader import CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
# from langchain_ollama import OllamaEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
import ollama
import os
import traceback

app = FastAPI()

# embedding_function = OllamaEmbeddings(model="nomic-embed-text")
embedding_function = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-en-v1.5"
)

PERSIST_DIR = "./chroma_db"

# If the folder exists, it loads existing data. If not, it creates a clean instance.
vector_db = Chroma(
    persist_directory=PERSIST_DIR,
    embedding_function=embedding_function
)

@app.post("/ingest")
def ingest_csv():
    try:
        file_path = "/home/lavanya/Desktop/Lavanya/med_store/products.csv"
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="CSV file not found at the specified path.")

        loader = CSVLoader(
            file_path=file_path,
            csv_args={"delimiter": ",", "quotechar": '"'}
        )

        documents = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50
        )

        chunks = text_splitter.split_documents(documents)
        print(f"Total chunks: {len(chunks)}")

        batch_size = 1000
        chunks = chunks[:500]
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
        results = vector_db.similarity_search(user_query, k=3)
        
        if not results:
            return {"response": "No matching context found in the database."}
            
        context = "\n\n".join([doc.page_content for doc in results])
        
        system_prompt = f"""
        You are a professional, helpful hospital assistant. Answer the user's question using ONLY the provided context below.
        If you do not know the answer based on the context, state clearly that the information is not available.
        Do not use external knowledge or invent facts.
        
        CONTEXT:
        {context}
        """

        response = ollama.chat(
            model="llama3",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query} 
            ]
        )
        
        return {"response": response['message']['content']}
        
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
