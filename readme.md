User query
   ↓
1. Encode query
   ↓
2. Load ALL embeddings from dataframe
   ↓
3. Calculate cosine similarity against ALL products
   ↓
4. Keyword search
   ↓
5. Load spell-correction pickle from disk
   ↓
6. Correct query
   ↓
7. Encode corrected query AGAIN
   ↓
8. Calculate cosine similarity against ALL products AGAIN
   ↓
9. Convert dataframe → JSON
   ↓
10. Send potentially large context to Ollama
   ↓
11. Wait for LLM generation