from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
import pandas as pd, re, shutil
from html import unescape
from pathlib import Path

BASE = Path(__file__).resolve().parent
CHROMA_DIR = BASE / "chroma_db"
CSV_PATH = BASE / "products.csv"

def clean(t):
    t = unescape(str(t).replace("\\n"," ").replace("\n"," "))
    t = re.sub(r"<[^>]+>"," ",t)
    return re.sub(r"\s+"," ",t).strip()[:800] # pre-trim

print(f"1. Reading CSV from {CSV_PATH}...")
df = pd.read_csv(CSV_PATH).fillna("")

if CHROMA_DIR.exists():
    shutil.rmtree(CHROMA_DIR)

embed = OllamaEmbeddings(model="all-minilm")

texts, metas = [], []
for i, row in df.iterrows():
    name = str(row.get("Name",""))[:150] # don't double name, keep short
    cat = clean(str(row.get("Categories",""))[:200])
    desc = clean(str(row.get("Description",""))[:400])
    tags = str(row.get("Tags",""))[:100]

    text = f"{name} Categories: {cat} Description: {desc} Tags: {tags}"
    # FINAL HARD CUT - must be < 512 tokens ~ 1000 chars for all-minilm
    text = text[:600].strip()

    if len(text) < 10:
        continue

    texts.append(text)
    metas.append({"row": i})

print(f"2. Embedding {len(texts)} products to {CHROMA_DIR}...")

db = None
BATCH = 50 # smaller batch for small model
for start in range(0, len(texts), BATCH):
    end = min(start+BATCH, len(texts))
    print(f" Batch {start//BATCH+1} : {start}-{end}")
    try:
        if db is None:
            db = Chroma.from_texts(texts=texts[start:end], metadatas=metas[start:end], embedding=embed, persist_directory=str(CHROMA_DIR))
        else:
            db.add_texts(texts=texts[start:end], metadatas=metas[start:end])
    except Exception as e:
        print(f" FAILED batch {start}-{end}: {e}")
        # skip bad batch, continue
        for j in range(start, end):
            try:
                if db is None:
                    db = Chroma.from_texts(texts=[texts[j]], metadatas=[metas[j]], embedding=embed, persist_directory=str(CHROMA_DIR))
                else:
                    db.add_texts(texts=[texts[j]], metadatas=[metas[j]])
            except:
                print(f" Skipping row {metas[j]['row']} - too long")
                continue

print("DONE")