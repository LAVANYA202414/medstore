import csv, re
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import os, shutil

# Delete old broken DB
if os.path.exists("./chroma_db"):
    shutil.rmtree("./chroma_db")

def clean(t):
    return re.sub(r'<[^<]+?>', ' ', t or '').strip()

print("Loading model...")
embedding = HuggingFaceEmbeddings(
    model_name="all-MiniLM-L6-v2",
    cache_folder="./model_cache"
)

db = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embedding
)

docs = []
with open("./products.csv", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        name = row.get("Name","").strip()
        if not name:
            continue
        # Search text = Name + Description + Categories + Tags
        search_text = f"{name} {clean(row.get('Description',''))} {row.get('Categories','')} {row.get('Tags','')}"
        docs.append(Document(
            page_content=search_text,
            metadata=row  # Whole row saved
        ))

print(f"Total docs: {len(docs)} - Adding in batches of 1000...")

BATCH = 500
for i in range(0, len(docs), BATCH):
    batch = docs[i:i+BATCH]
    db.add_documents(batch)
    print(f"Added {i+len(batch)}/{len(docs)}")

print("Done - chroma_db ready with whole row metadata")