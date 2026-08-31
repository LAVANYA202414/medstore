import auth
import models
import pandas as pd
from pathlib import Path
from typing import Optional
from database import get_db
from sqlalchemy import func
from datetime import datetime
from pydantic import BaseModel
from collections import Counter
from sqlalchemy.orm import Session
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
import re, difflib, os, traceback, logging, json
from fastapi import APIRouter, HTTPException, Depends, Query as QueryParam

datetime.utcnow()


router = APIRouter(tags=["chat"])


class QueryRequest(BaseModel):
    user_query: str
    topic_id: Optional[str] = None


EMBED_MODEL = "all-minilm"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("query")

embedding_function = None
vector_db = None


def generate_topic_title(query: str) -> str:
    cleaned = query.strip()
    for prefix in ["show me", "i need", "price of", "what is", "give me", "cost of"]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    words = cleaned.split()[:6]
    title = " ".join(words)
    return title.title()[:60] if title else query[:60].title()


def get_resources():
    global embedding_function, vector_db
    if vector_db is not None:
        return embedding_function, vector_db
    if not CHROMA_DIR.exists():
        raise HTTPException(status_code=500, detail=f"chroma_db not found at {CHROMA_DIR}")
    try:
        embedding_function = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_BASE_URL)
        embedding_function.embed_query("test")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama failed: {e}")
    try:
        vector_db = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embedding_function)
        vector_db.get(limit=1)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load DB: {e}")
    return embedding_function, vector_db


STOP_WORDS = {"price","of","cost","what","is","the","a","an","show","me","give","details","detail","for","in","on","please","tell","about","description","desc","info","information"}


def clean_tokens(s: str):
    toks = [t.lower() for t in re.findall(r'\w+', s.lower())]
    return [t for t in toks if t not in STOP_WORDS and len(t) >= 3]


def is_product_query(user_q: str, df_local, PRODUCTS_SORTED):
    q_lower = user_q.lower().strip()
    q_toks = clean_tokens(q_lower)
    if not q_toks:
        return None
    def contains_all(name_lower):
        for qt in q_toks:
            qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
            if qt not in name_lower and qt_root not in name_lower:
                if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(name_lower)):
                    return False
        return True
    match_count = df_local['Name_lower'].apply(contains_all).sum()
    if match_count > 1:
        return None
    if len(q_toks) == 1:
        qt = q_toks[0]
        count = 0
        exact_match_row = None
        for _, row in PRODUCTS_SORTED.iterrows():
            name_lower = str(row['Name_lower'])
            if name_lower == q_lower:
                return row
            name_toks = clean_tokens(name_lower)
            if any(qt in nt or nt in qt or difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in name_toks):
                count += 1
                if exact_match_row is None:
                    exact_match_row = row
            if count > 1:
                return None
        if count == 1:
            return exact_match_row
        return None
    for _, row in PRODUCTS_SORTED.iterrows():
        name_lower = str(row['Name_lower']).strip()
        if not name_lower:
            continue
        if name_lower == q_lower:
            return row
        if name_lower in q_lower and len(q_lower) < len(name_lower) + 10:
            return row
        name_toks = clean_tokens(name_lower)
        if not name_toks:
            continue
        if len(name_toks) > len(q_toks) + 2:
            continue
        matched = sum(1 for qt in q_toks if any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in name_toks))
        if matched == len(name_toks) and matched == len(q_toks):
            return row
    return None


def run_rag_logic(user_query: str, db: Session):
    _, v_db = get_resources()
    db_products = db.query(models.Product).filter(models.Product.published == True, models.Product.visibility == True).all()
    if not db_products:
        return {"products": [], "query": user_query, "type": "category"}
    rows = []
    for p in db_products:
        rows.append({"id": p.id, "Name": p.name, "slug": p.slug, "regular_price": p.regular_price, "sale_price": p.sale_price, "brand": p.brand, "images": p.images, "tags": p.tags, "description": p.description, "short_description": p.short_description, "_db_obj": p})
    df_local = pd.DataFrame(rows).fillna("")
    df_local['Name_lower'] = df_local['Name'].astype(str).str.lower().str.strip()
    PRODUCTS_SORTED = df_local.sort_values(by='Name', key=lambda x: x.str.len(), ascending=False)
    prod_row = is_product_query(user_query, df_local, PRODUCTS_SORTED)
    if prod_row is not None:
        prod = prod_row.to_dict()
        prod.pop('Name_lower', None); prod.pop('_db_obj', None)
        return {"products": [prod], "query": user_query, "type": "product"}
    q_lower = user_query.lower().strip()
    q_toks = clean_tokens(q_lower)
    if q_toks:
        def matches(name_lower):
            for qt in q_toks:
                qt_root = qt[:-1] if qt.endswith('s') and len(qt)>3 else qt
                if qt not in name_lower and qt_root not in name_lower:
                    if not any(difflib.SequenceMatcher(None, qt, nt).ratio() >= 0.85 for nt in clean_tokens(name_lower)):
                        return False
            return True
        mask = df_local['Name_lower'].apply(matches)
        matched_df = df_local[mask]
        if len(matched_df) > 1:
            final, seen = [], set()
            for _, r in matched_df.iterrows():
                name = str(r.get("Name","")).strip().lower()
                if name in seen: continue
                d = r.to_dict(); d.pop('Name_lower', None); d.pop('_db_obj', None)
                final.append(d); seen.add(name)
            return {"products": final, "query": user_query, "type": "category", "count": len(final)}

    # --- EMBEDDING SEARCH - FOR EVERY QUERY INCLUDING GREETING ---
    clean_q = user_query.replace("-", " ").replace("_", " ").strip()

    # REMOVED greeting check - now similarity search for every query

    results = v_db.similarity_search_with_score(clean_q, k=20)
    final, seen = [], set()
    name_lookup = {str(r['Name']).lower().strip(): r for _, r in df_local.iterrows()}
    for doc, score in results:
        meta_name = doc.metadata.get("Name") or doc.metadata.get("name")
        if not meta_name:
            meta_name = doc.page_content.split(" Categories:")[0].strip()

        lookup_key = str(meta_name).lower().strip()
        r = name_lookup.get(lookup_key)

        if r is None: # FIXED: was `if not r:`
            continue

        # r is a Series
        row = r.to_dict()
        name_key = str(row.get("Name","")).strip().lower()
        if not name_key or name_key in seen:
            continue
        row.pop('Name_lower', None)
        row.pop('_db_obj', None)
        final.append(row)
        seen.add(name_key)
        if len(final) >= 10:
            break

    return {"products": final[:10], "query": user_query, "type": "category", "count": len(final)}


@router.get("/topics")
def get_all_topics(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    topics = db.query(
        models.ChatTopic.id.label('id'),
        models.ChatTopic.title.label('title'),
        func.count(models.ChatHistory.id).label('count'),
        func.max(models.ChatHistory.created_at).label('last_chat')
    ).join(
        models.ChatHistory, models.ChatTopic.id == models.ChatHistory.topic_id
    ).filter(
        models.ChatHistory.user_id == current_user.id
    ).group_by(
        models.ChatTopic.id, models.ChatTopic.title
    ).order_by(
        func.max(models.ChatHistory.created_at).desc()
    ).all()
    
    return [{"id": t.id, "title": t.title, "count": t.count} for t in topics]


@router.get("/admin/topics")
def get_admin_topics(
    user_id: int,  # Request the user_id as a query parameter
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
    # Check if the logged-in user is actually an admin
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to access admin endpoints")

    topics = db.query(
        models.ChatTopic.id.label('id'),
        models.ChatTopic.title.label('title'),  
        func.count(models.ChatHistory.id).label('count'),
        func.max(models.ChatHistory.created_at).label('last_chat')
    ).join(
        models.ChatHistory, models.ChatTopic.id == models.ChatHistory.topic_id
    ).filter(
        models.ChatHistory.user_id == user_id  # Filter by the requested user_id instead of current_user.id
    ).group_by(
        models.ChatTopic.id, models.ChatTopic.title
    ).order_by(
        func.max(models.ChatHistory.created_at).desc()
    ).all()
    
    return [{"id":t.id,"title": t.title, "count": t.count} for t in topics]


# @router.get("/topics/{topic_name}")
# def get_chats_by_topic(topic_name: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
#     chats = db.query(models.ChatHistory).filter(models.ChatHistory.user_id == current_user.id, models.ChatHistory.topic == topic_name).order_by(models.ChatHistory.created_at.asc()).all()
#     return {"topic": topic_name, "messages": [{"id": c.id, "query": c.user_query, "response": json.loads(c.response_json) if c.response_json else {}, "created_at": c.created_at} for c in chats]}


@router.post("/query")
def ask_rag_bot(request: QueryRequest, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    result = run_rag_logic(request.user_query, db)

    # Clean HTML tags from product descriptions if products exist in the result
    if "products" in result and isinstance(result["products"], list):
        for product in result["products"]:
            if isinstance(product, dict):
                # Clean description
                if "description" in product and product["description"]:
                    product["description"] = re.sub(r'<[^>]*>', '', str(product["description"])).strip()
                
                # Clean short_description
                if "short_description" in product and product["short_description"]:
                    product["short_description"] = re.sub(r'<[^>]*>', '', str(product["short_description"])).strip()

    try:
        chat_topic = None

        # If topic_id is sent -> continue existing chat
        if request.topic_id:
            chat_topic = db.query(models.ChatTopic).filter(
                models.ChatTopic.id == request.topic_id,
                models.ChatTopic.user_id == current_user.id
            ).first()

        # No topic_id, OR topic_id was invalid/not owned by user -> start a NEW chat
        if not chat_topic:
            title = request.user_query.strip()[:80]  # topic name = first message
            chat_topic = models.ChatTopic(
                user_id=current_user.id,
                title=title
            )
            db.add(chat_topic)
            db.flush()  # get chat_topic.id before using it below
            is_new_chat = True
        else:
            is_new_chat = False
            chat_topic.updated_at = datetime.utcnow()

        chat = models.ChatHistory(
            user_id=current_user.id,
            topic_id=chat_topic.id,
            user_query=request.user_query,
            response_type=result.get("type", "category"),
            response_json=json.dumps(result, default=str),
            products_count=len(result.get("products", []))
        )
        db.add(chat)
        db.commit()

        result["chat_id"] = chat.id
        result["topic_id"] = chat_topic.id
        result["topic_title"] = chat_topic.title
        result["is_new_chat"] = is_new_chat
        return result

    except Exception as e:
        db.rollback()
        logger.error(traceback.format_exc())
        raise HTTPException(500, str(e))



# --- GET CHAT HISTORY (only logged-in user can see their own) ---
@router.get("/query/history")
def get_chat_history(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
    page: int = QueryParam(1, ge=1),
    limit: int = QueryParam(20, ge=1, le=100)):
    total = db.query(models.ChatHistory).filter(models.ChatHistory.user_id == current_user.id).count()
    
    chats = db.query(models.ChatHistory)\
        .filter(models.ChatHistory.user_id == current_user.id)\
        .order_by(models.ChatHistory.created_at.desc())\
        .offset((page-1)*limit)\
        .limit(limit)\
        .all()
    
    history = []
    for c in chats:
        try:
            resp = json.loads(c.response_json) if c.response_json else {}
        except:
            resp = {}
        history.append({
            "id": c.id,
            "query": c.user_query,
            "response": resp,
            "type": c.response_type,
            "products_count": c.products_count,
            "created_at": c.created_at
        })
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "history": history
    }


@router.get("/query/history/{chat_id}")
def get_single_chat(
    chat_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)):

    # ADMIN can see any topic, USER can see only own
    topic_query = db.query(models.ChatTopic).filter(
        models.ChatTopic.id == chat_id
    )
    if not getattr(current_user, 'is_admin', False):
        topic_query = topic_query.filter(models.ChatTopic.user_id == current_user.id)
    
    topic = topic_query.first()
    if not topic:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_query = db.query(models.ChatHistory).filter(
        models.ChatHistory.topic_id == chat_id
    )
    if not getattr(current_user, 'is_admin', False):
        chat_query = chat_query.filter(models.ChatHistory.user_id == current_user.id)

    chats = chat_query.order_by(models.ChatHistory.created_at.asc()).all()

    messages = []
    for c in chats:
        try:
            resp = json.loads(c.response_json) if c.response_json else {}
        except:
            resp = {}
        messages.append({
            "id": c.id,
            "topic_id": c.topic_id,
            "query": c.user_query,
            "response": resp,
            "type": c.response_type,
            "created_at": c.created_at
        })

    return {
        "topic_id": topic.id,
        "title": topic.title,
        "total_messages": len(messages),
        "messages": messages
    }


# @router.delete("/query/history/{chat_id}")
# def delete_chat(
#     chat_id: int,
#     db: Session = Depends(get_db),
#     current_user: models.User = Depends(auth.get_current_user)
# ):
#     chat = db.query(models.ChatHistory).filter(
#         models.ChatHistory.id == chat_id,
#         models.ChatHistory.user_id == current_user.id
#     ).first()
#     if not chat:
#         raise HTTPException(status_code=404, detail="Chat not found")
    
#     db.delete(chat)
#     db.commit()
#     return {"message": "Chat deleted"}


# @router.delete("/query/history")
# def clear_all_history(
#     db: Session = Depends(get_db),
#     current_user: models.User = Depends(auth.get_current_user)
# ):
#     db.query(models.ChatHistory).filter(models.ChatHistory.user_id == current_user.id).delete()
#     db.commit()
#     return {"message": "All chat history cleared"}


class StartChatRequest(BaseModel):
    user_query: str


@router.post("/chat/start", tags=["chat"])
def start_new_chat(
    request: StartChatRequest, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    START NEW CHAT API
    Input: { "user_query": "show me transit chairs" }
    - Creates new topic with title = first message
    - Saves first message in chat_history
    - Returns topic_id to use for continuing
    """
    try:
        # RAG logic
        result = run_rag_logic(request.user_query, db)

        # Create NEW topic - title = first message (ChatGPT style)
        title = request.user_query.strip()[:80]
        chat_topic = models.ChatTopic(
            user_id=current_user.id,
            title=title
        )
        db.add(chat_topic)
        db.flush() # get id

        # Create first chat message
        chat = models.ChatHistory(
            user_id=current_user.id,
            topic_id=chat_topic.id,
            user_query=request.user_query,
            response_type=result.get("type", "category"),
            response_json=json.dumps(result, default=str),
            products_count=len(result.get("products", []))
        )
        db.add(chat)
        db.commit()
        db.refresh(chat_topic)
        db.refresh(chat)

        return {
            "message": "New chat started",
            "topic_id": chat_topic.id,
            "topic_title": chat_topic.title,
            "chat_id": chat.id,
            "query": chat.user_query,
            "response": result,
            "created_at": chat.created_at
        }

    except Exception as e:
        db.rollback()
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))