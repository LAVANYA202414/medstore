from sqlalchemy import create_engine, text

# Try these common setups - one will work
TRY_URLS = [
    "mysql+pymysql://root:@localhost:3306",  # XAMPP default
    "mysql+pymysql://root:root@localhost:3306", # WAMP/MAMP default
    "mysql+pymysql://root:password@localhost:3306",
    "mysql+pymysql://root:mysql@localhost:3306",
]

DB_NAME = "medstore_db"

for base_url in TRY_URLS:
    print(f"Trying {base_url} ...")
    try:
        engine = create_engine(base_url, connect_args={'connect_timeout': 3})
        with engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"))
            conn.commit()
            print(f"\n SUCCESS!")
            print(f"   Connected with: {base_url}")
            print(f"   Database '{DB_NAME}' created.")
            print(f"\n USE THIS URL IN YOUR CODE:")
            print(f"   {base_url}/{DB_NAME}")
            
            # Save it to .env for you
            with open(".env", "w") as f:
                f.write(f"DATABASE_URL={base_url}/{DB_NAME}\n")
            print(f"\n   Saved to .env file")
            break
    except Exception as e:
        print(f"   Failed: {str(e)[:150]}")
else:
    print("\n Could not connect to MySQL with any default password.")
    print("Follow Step 3 below.")