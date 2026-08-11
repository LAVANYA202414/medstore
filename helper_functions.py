import re


def extract_price_filter(q_low: str):
    m = re.search(r'(?:under|less than|at most|below)\s*€?(\d+)', q_low)
    if m: return ("<", int(m.group(1)))
    m = re.search(r'(?:over|above|more than|at least)\s*€?(\d+)', q_low)
    if m: return (">", int(m.group(1)))
    m = re.search(r'cheaper than\s*€?(\d+)', q_low)
    if m: return ("<", int(m.group(1)))
    m = re.search(r'between\s*€?(\d+)\s*and\s*€?(\d+)', q_low)
    if m: return ("between", int(m.group(1)), int(m.group(2)))
    m = re.search(r'most expensive|highest price|expensive', q_low)
    if m: return ("sort_desc",)
    m = re.search(r'cheapest|lowest price|cheap', q_low)
    if m: return ("sort_asc",)

    return None


def extract_model_filter(q_low: str):
    # "model X" or "model-X" patterns
    m = re.search(r'model[\s\-]+([a-z0-9][a-z0-9\-]*)', q_low)
    if m: return m.group(1).upper()
    return None


def extract_image_count_filter(q_low: str):
    m = re.search(r'more than\s*(\d+)\s*images?', q_low)
    if m: return int(m.group(1))
    return None


def _price_key(x): return _get_price_val(x)


def _get_price_val(r):
    try:
        raw = r.get("Regular price", "") if isinstance(r, dict) else r["Regular price"]
        cleaned = re.sub(r'[^\d.]', '', str(raw).replace(',', ''))  # strip €, commas
        return float(cleaned) if cleaned else 0.0
    except:
        return 0.0


def apply_old_price_filter(rows, pf):
    if not pf: return rows
    if pf[0] == "<":
        return [r for r in rows if _get_price_val(r) <= pf[1]]
    if pf[0] == ">":
        return [r for r in rows if _get_price_val(r) >= pf[1]]
    if pf[0] == "between":
        return [r for r in rows if pf[1] <= _get_price_val(r) <= pf[2]]
    if pf[0] == "sort_asc":
        return sorted([r for r in rows if _get_price_val(r)>0], key=_price_key)[:20]
    if pf[0] == "sort_desc":
        return sorted([r for r in rows if _get_price_val(r)>0], key=_price_key, reverse=True)[:20]
    return rows