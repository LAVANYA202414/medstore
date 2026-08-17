@router.get("/products/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        while curr:
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}
    
    # get all category text paths
    cat_paths = [get_path(c) for c in p.categories]
    # pick the primary category chain
    primary = cat_paths[0] if cat_paths else "uncategorized"
    parts = [s.strip() for s in primary.split(">")]
    top = parts[0] if len(parts) > 0 else "uncategorized"
    sub = parts[1] if len(parts) > 1 else ""
    try:
        price = float(p.regular_price or p.sale_price or 0)
    except:
        price = 0

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug or to_slug(p.name),
        "description": strip_html(p.short_description or (p.description or "")[:150]),
        "longDescription": strip_html(p.description or ""),
        "categoryId": to_slug(top),
        "subcategoryId": to_slug(sub) if sub else "",
        "categoryName": top,
        "subcategoryName": sub,
        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
    }













@router.get("/products/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        while curr:
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}

    cat_paths = [get_path(c) for c in p.categories]

    # FIX 1: Pick longest chain as primary, not first
    cat_paths_sorted = sorted(cat_paths, key=lambda x: x.count(">"), reverse=True)
    primary = cat_paths_sorted[0] if cat_paths_sorted else "uncategorized"

    parts = [s.strip() for s in primary.split(">")]
    top = parts[0] if len(parts) > 0 else "uncategorized"
    sub = parts[1] if len(parts) > 1 else ""
    # For deep categories like A > B > C, you want full sub chain
    sub_chain = " > ".join(parts[1:]) if len(parts) > 1 else ""
    leaf = parts[-1] if len(parts) > 1 else "" # deepest subcategory

    print("SUBCATEGORY:",to_slug(sub) if sub else "")
    print("categoryId", to_slug(top))
    try:
        price = float(p.regular_price or p.sale_price or 0)
    except:
        price = 0

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug or to_slug(p.name),
        "description": strip_html(p.short_description or (p.description or "")[:150]),
        "longDescription": strip_html(p.description or ""),
        "categoryId": to_slug(top),
        "subcategoryId": to_slug(sub) if sub else "",
        "categoryName": top,
        "subcategoryName": sub,
        # "categoryPath": primary,
        # "subcategoryPath": sub_chain,
        # "allCategories": cat_paths,
        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
    }
























@router.get("/products/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        while curr:
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}

    cat_paths = [get_path(c) for c in p.categories]

    # --- ARRAY LOGIC ---
    categoryIds = []
    categoryNames = []
    subcategoryIds = []
    subcategoryNames = []
    allCategoryPaths = []

    for path in cat_paths:
        parts = [s.strip() for s in path.split(">")]
        if not parts[0]:
            continue
        top = parts[0]
        sub = parts[1] if len(parts) > 1 else ""

        allCategoryPaths.append(path)

        top_slug = to_slug(top)
        if top_slug not in categoryIds:
            categoryIds.append(top_slug)
            categoryNames.append(top)

        if sub:
            sub_slug = to_slug(sub)
            if sub_slug not in subcategoryIds:
                subcategoryIds.append(sub_slug)
                subcategoryNames.append(sub)

    # primary for old compatibility
    primary = sorted(cat_paths, key=lambda x: x.count(">"), reverse=True)[0] if cat_paths else "uncategorized"

    try:
        price = float(p.regular_price or p.sale_price or 0)
    except:
        price = 0

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug or to_slug(p.name),
        "description": strip_html(p.short_description or (p.description or "")[:150]),
        "longDescription": strip_html(p.description or ""),

        # NEW ARRAY FORMAT
        "categoryId": categoryIds, # ["emergency", "diagnostics"]
        "categoryName": categoryNames, # ["Emergency", "Diagnostics"]
        "subcategoryId": subcategoryIds, # ["bags", "rescue"]
        "subcategoryName": subcategoryNames,
        "allCategories": allCategoryPaths,

        # Old single fields for backward compatibility if needed
        "primaryCategoryId": to_slug(primary.split(">")[0].strip()) if primary else "",
        "primaryCategoryName": primary.split(">")[0].strip() if primary else "",

        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
    }













@router.get("/products/{product_id}")
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    all_cats = db.query(models.Category).all()
    all_cats_map = {c.id: c for c in all_cats}

    def get_path(cat):
        parts = []
        curr = cat
        while curr:
            parts.append(curr.name)
            curr = all_cats_map.get(curr.parent_id) if curr.parent_id else None
        return " > ".join(reversed(parts))

    p = db.query(models.Product).options(joinedload(models.Product.categories)).filter(models.Product.id == product_id).first()
    if not p:
        return {"error": f"Product {product_id} not found"}

    cat_paths = [get_path(c) for c in p.categories]

    # NEW: last category logic
    leafIds = []
    leafNames = []
    allCategoryPaths = []

    for path in cat_paths:
        parts = [s.strip() for s in path.split(">") if s.strip()]
        if not parts:
            continue

        allCategoryPaths.append(path)
        leaf = parts[-1] # LAST - works for both "Emergency" and "Emergency > Rescue"
        leaf_slug = to_slug(leaf)

        if leaf_slug not in leafIds:
            leafIds.append(leaf_slug)
            leafNames.append(leaf)

    try:
        price = float(p.regular_price or p.sale_price or 0)
    except:
        price = 0

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug or to_slug(p.name),
        "description": strip_html(p.short_description or (p.description or "")[:150]),
        "longDescription": strip_html(p.description or ""),
        "categoryId": leafIds, # ["emergency"] or ["rescue"]
        "categoryName": leafNames, # ["Emergency"] or ["Rescue"]
        "allCategories": allCategoryPaths, # for debug ["Emergency", "Emergency > Rescue"]
        "price": price,
        "brand": p.brand or "Generic",
        "inStock": bool(p.in_stock),
        "image": p.images.split(',')[0].strip() if p.images else "/products/placeholder.png",
        "tags": [t.strip() for t in str(p.tags or "").split(',') if t.strip()][:5],
    }