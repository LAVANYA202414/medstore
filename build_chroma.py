# build_chroma.py
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
import pandas as pd, re, os, shutil, time
from html import unescape

def clean(t):
    t = unescape(str(t).replace("\\n"," ").replace("\n"," "))
    t = re.sub(r"<[^>]+>"," ",t)
    return re.sub(r"\s+"," ",t).strip()

print("1. Reading CSV...")
df = pd.read_csv("products.csv").fillna("")
if os.path.exists("./chroma_db"):
    shutil.rmtree("./chroma_db")

# ### CHANGE MODEL HERE ###
embed = OllamaEmbeddings(model="nomic-embed-text") # was all-minilm

texts, metas = [], []
for i, row in df.iterrows():
    name = str(row.get("Name",""))
    # now we can use FULL description because 8192 tokens
    text = f"{name} {name} Categories: {row.get('Categories','')} Description: {clean(str(row.get('Description',''))[:1500])} Tags: {row.get('Tags','')}"
    texts.append(text[:2000]) # safe under 8192
    metas.append({"row": i})

print(f"2. Embedding {len(texts)} products...")

db = None
BATCH = 200 # faster batches because model is faster
for start in range(0, len(texts), BATCH):
    end = min(start+BATCH, len(texts))
    print(f" Batch {start//BATCH+1} : {start}-{end}")
    if db is None:
        db = Chroma.from_texts(texts=texts[start:end], metadatas=metas[start:end], embedding=embed, persist_directory="./chroma_db")
    else:
        db.add_texts(texts=texts[start:end], metadatas=metas[start:end])

print("DONE")

for q in ["forceps", "baby delivery dummy"]:
    print(f"\n{q}:")
    for doc, score in db.similarity_search_with_score(q, k=2):
        print(f" {score:.3f} row {doc.metadata['row']}")