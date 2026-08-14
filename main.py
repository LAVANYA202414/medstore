import auth
from fastapi import FastAPI
import ingest, query, products
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Medstore")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:8000", "https://medstore.codenomad.net", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(products.router)
app.include_router(auth.router) # for /api/login