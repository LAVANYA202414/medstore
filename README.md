# MedStore - Medical E-commerce Backend

Full-stack backend for medical supplies store with MySQL relational DB + Chroma Vector DB + Ollama embeddings for AI search.

---

## 1. Tech Stack

| Layer | Technology |
|-------|------------|
| **API** | FastAPI, Python 3.10+ |
| **Relational DB** | MySQL + SQLAlchemy + PyMySQL |
| **Vector DB** | ChromaDB (`langchain-chroma`) |
| **Embeddings** | Ollama `all-minilm` (`langchain-ollama`) |
| **Auth** | JWT (`pyjwt`) + `passlib` pbkdf2_sha256 |
| **Frontend Origins** | `localhost:5173/5174` + `medstore.codenomad.net` |

**Two databases:**
- **MySQL (`medstore_db`)**: Products, Categories, Users, product_categories join table
- **ChromaDB (`./chroma_db/`)**: Vector embeddings of products for semantic search (`/query`)

---

## 2. Project Structure

```
med_store/
├── main.py              # FastAPI app + CORS + routers
├── database.py          # SQLAlchemy engine, SessionLocal, get_db
├── models.py            # Product, Category, User, product_categories M2M
├── products.py          # /products, /admin/products, CRUD, category logic
├── query.py             # /query - RAG bot: MySQL exact + Chroma vector search
├── auth.py              # /api/signup, /user/login, /admin/login, /user/me
├── ingest.py            # POST /ingest -> builds chroma_db from products_cleaned.csv
├── mysql_ingest.py      # CLI: CSV -> MySQL (categories chain + products)
├── create_db.py         # Creates MySQL database medstore_db + writes .env
├── create_admin.py      # Creates admin user from .env ADMIN_EMAIL/PASSWORD
├── products.csv / products_cleaned.csv
├── chroma_db/           # Generated vector store (after ingest)
├── .env                 # DATABASE_URL, SECRET_KEY, ADMIN_EMAIL, etc.
```

---

## 3. Environment Setup (.env)

Create `.env` in root:

```env
DATABASE_URL=mysql+pymysql://root:your_mysql_password@localhost:3306/medstore_db
SECRET_KEY=your_super_secret_jwt_key_change_this
ADMIN_EMAIL=admin@medstore.ie
ADMIN_PASSWORD=AdminPass123
OLLAMA_BASE_URL=http://localhost:11434
```

`create_db.py` auto-writes `DATABASE_URL` to `.env` for you.

---

## 4. Full Setup Process (Step by Step)

### Step 0: Install dependencies

```bash
pip install -r requirements.txt
```

```bash
# For environment
python3 -m venv med_store_env
source med_store_env/bin/activate

# If requirements.txt doesn't work then: 
pip install fastapi uvicorn sqlalchemy pymysql python-dotenv
pip install passlib pyjwt langchain-chroma langchain-ollama
pip install pandas python-multipart email-validator
```

Install Ollama and pull model:
```bash
# Install Ollama from https://ollama.com
ollama pull all-minilm
ollama serve
```

### Step 1: Create MySQL Database

```bash
python3 create_db.py
# Tries 4 default MySQL root passwords, creates medstore_db
# Output: DATABASE_URL=mysql+pymysql://root:@localhost:3306/medstore_db
```

If fails, create manually:
```sql
CREATE DATABASE medstore_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### Step 2: Ingest Products to MySQL (If not exists)

This builds categories tree (`Emergency > Rescue`) and links products.

```bash
python3 mysql_ingest.py
# Reads products_cleaned.csv (or products.csv)
# Output: SUCCESS! 5111 products, 195 categories, 15853 links
```

Check DB:
```bash
python3 check_db.py
# Products: 5111
# Categories: 195
# Links: 15853
```

### Step 3: Build Chroma Vector DB (for AI search)

```bash
uvicorn main:app --reload
# POST http://localhost:8000/ingest
curl -X POST http://localhost:8000/ingest
# Creates ./chroma_db/ with embeddings, batches of 50
```

Or build offline without API:
```python
# from ingest.py logic
```

### Step 4: Create Admin User

```bash
# Set ADMIN_EMAIL and ADMIN_PASSWORD in .env first
python3 create_admin.py
# Admin created: admin@medstore.ie
```

### Step 5: Run API

```bash
uvicorn main:app --reload --port 8000
# Docs: http://localhost:8000/docs
```

---

## 5. API Reference

### Public Product APIs (MySQL only)

**GET /products**
```http
GET /products?category=Defibrillators&page=1&limit=10
GET /products?product=Transit Chair
```
Response:
```json
{
  "metadata": {"total_items": 120, "total_pages": 12, "current_page": 1},
  "products": [{
    "id": 1,
    "name": "Transit Chair",
    "slug": "transit-chair",
    "description": "Short desc",
    "longDescription": "Full HTML stripped",
    "categoryId": ["rescue"],
    "categoryName": ["Rescue"],
    "price": 299.0,
    "brand": "Generic",
    "inStock": true,
    "rating": 4.5,
    "image": "https://...",
    "tags": ["..."],
    "specifications": {"Model": "..."},
    "_raw_categories": "Emergency > Rescue"
  }]
}
```
- Filters: `published=true AND visibility=true`
- Category search supports full path `Emergency > Rescue` and child propagation

### Admin Product APIs (Auth required)

```
POST /create-category
GET /admin/products/{product_id}
PATCH /categories/{category_id}
PATCH /products/{product_id}
PATCH /products/{product_id}/activate
PATCH /products/{product_id}/deactivate
GET /admin/products
POST /create-products
GET /api/users
PATCH /api/users/{user_id}
```

### RAG Search API (MySQL + Chroma)

```
POST /query
Body: {"user_query": "show me chair for emergency"}

Flow:
1. MySQL exact match (is_product_query) -> 1 product
2. MySQL token match (all tokens in name) -> >1 products
3. Chroma similarity_search_with_score(k=20) -> vector results
4. Fallback: top 10 from MySQL

Response: {"products": [...], "query": "...", "type": "product|category"}
```

Requires:
- `chroma_db/` exists
- Ollama running at `OLLAMA_BASE_URL` with `all-minilm`

### Auth APIs (Users vs Admin)

**User Signup (is_admin=False)**
```
POST /api/signup
POST /api/user/signup
Body: {
  "email": "user@test.com",
  "password": "Test1234",          # min 8, 1 uppercase, 1 number
  "confirm_password": "Test1234"
}
-> 201 + access_token
```

**User Login**
```
POST /api/user/login
Body: {"email": "user@test.com", "password": "Test1234"}
-> access_token, user {id, email, is_admin:false}
-> Rejects admin accounts
```

**Admin Login**
```
POST /api/admin/login
POST /api/login (backward compat)
Body: {"email": "admin@medstore.ie", "password": "AdminPass123"}
-> access_token, is_admin:true
-> Rejects normal users
```

Token: JWT HS256, 12h expiry, payload `{user_id, is_admin, exp}`

---

## 6. Common Issues & Fixes

**1. Chroma DB not found**
```bash
ls chroma_db/
# If not exists -> POST /ingest
# Check OLLAMA_BASE_URL in .env, ollama serve running
```

**2. `is_admin` check in /login blocks users**
- Use separate endpoints: `/api/user/login` (users) vs `/api/admin/login` (admin)
- `get_current_admin` should check admin, not `login`

---

## 7. Data Model (models.py)

```python
Product: id, name, slug, short_description, description, regular_price, sale_price,
         in_stock, is_featured, published, visibility, brand, model, images, tags, categories M2M

Category: id, name, slug, parent_id (self FK), products M2M

product_categories: product_id, category_id (composite PK)

User: id, email unique, password_hash, is_admin, is_active, created_at
```

---

## 8. Scripts

| Script | Purpose |
|--------|---------|
| `create_db.py` | Create MySQL DB + .env |
| `mysql_ingest.py` | CSV -> MySQL |
| `ingest.py` | CSV -> Chroma DB (vector) |
| `create_admin.py` | Create admin user |
| `check_db.py` | Debug: count products/categories/links |

---

## 9. Production Checklist

- Change `SECRET_KEY` in .env
- Set strong `ADMIN_PASSWORD`
- Restrict CORS origins in `main.py`
- Use `mysql+pymysql` with real credentials, not root:@localhost
- Backup `chroma_db/` after ingest (rebuild is expensive)
---