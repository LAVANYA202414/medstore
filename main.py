import auth
from fastapi import FastAPI
import ingest, query, products
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Medstore")

# CORS ORIGIN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:8000", "https://medstore.codenomad.net", "http://localhost:5174", "https://medstoreadmin.codenomad.net"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routing
# app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(products.router)
app.include_router(auth.router) # for /api/login