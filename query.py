from fastapi import APIRouter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
import pandas as pd

router = APIRouter()

df = pd.read_csv("products.csv").fillna("")
embed = OllamaEmbeddings(model="all-minilm")
llm = ChatOllama(model="llama3.2", temperature=0.3)

@router.get("/query")
def ask_rag_bot(user_query: str):

    # search in database
    db = Chroma(persist_directory="./chroma_db", embedding_function=embed)
    results = db.similarity_search_with_score(user_query, k=10)

    # Fallback to general chat if no matching products are found in the database
    if len(results) == 0:
        ans = llm.invoke("You are a helpful medical store assistant. User says: " + user_query)
        return {"answer": ans.content, "products": []}

    # Fallback to general chat if the closest match is too irrelevant (high distance score)
    first_score = results[0][1]
    if first_score > 1.2:
        ans = llm.invoke("You are a helpful medical store assistant. User says: " + user_query)
        return {"answer": ans.content, "products": []}

    # check if user wants list or single product
    user_query_small = user_query.lower()

    if "models" in user_query_small or "products" in user_query_small or "show" in user_query_small or "list" in user_query_small or "all" in user_query_small:
        is_list = True
    else:
        is_list = False

    if is_list == True:
        need = 5
    else:
        need = 1

    # get products from csv
    final_products = []

    for item in results:
        doc = item[0]
        row = doc.metadata.get("row")

        if row == None:
            continue

        data = df.iloc[int(row)].to_dict()
        name = str(data["Name"])

        if name == "" or name == " ":
            continue

        final_products.append(data)

        if len(final_products) == need:
            break

    if len(final_products) == 0:
        return {"answer": "Sorry, I couldn't find that.", "products": []}

    # make answer
    if is_list == True:
        text = ""
        for p in final_products:
            text = text + p["Name"] + " - $" + str(p["Regular price"]) + "\n"

        prompt = "User asked: " + user_query + "\nWe have these products:\n" + text + "\nTell user we have " + str(len(final_products)) + " products and list them."
        ans = llm.invoke(prompt)

    else:
        one = final_products[0]
        prompt = "User: " + user_query + "\nProduct Name: " + str(one["Name"]) + "\nPrice: " + str(one["Regular price"]) + "\nDescription: " + str(one["Description"]) + "\nExplain this product in friendly way."
        ans = llm.invoke(prompt)

    return {
        "answer": ans.content,
        "products": final_products
    }