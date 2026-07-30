from fastapi import APIRouter
from langchain_community.document_loaders.csv_loader import CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

router = APIRouter()

@router.post("/ingest")
def ingest_csv():
    loader = CSVLoader(
        file_path="/home/lavanya/Desktop/Lavanya/med_store/products.csv",
        csv_args={'delimiter': ',', 'quotechar': '"'}
    )
    documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_documents(documents)

    embedding_function = OllamaEmbeddings(model="all-minilm")

    vector_db = Chroma.from_documents(chunks, embedding_function, persist_directory="./chroma_db")

    return {"message": f"Success! Ingested {len(chunks)} chunks into './chroma_db'"}