import os
import re
import uuid
import json
import sqlite3
import concurrent.futures
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory, abort
)
from werkzeug.utils import secure_filename

# Modular pipeline imports
from utils import (
    allowed_file, is_image, is_pdf, now_iso, clean_text,
    compute_content_hash, ALLOWED_EXT, MAX_CONTENT_MB
)
from db import get_db, init_db, row_to_dict, sync_item_fts, delete_item_fts
from ocr import extract_text_from_image, extract_text_from_pdf, OCR_AVAILABLE, PDF_AVAILABLE
from classifier import auto_categorize
from extractor import extract_entities
from tagger import generate_smart_tags

# ── AI Image Tagger (ai_tagger.py) ──────────────────────────────────────
try:
    from ai_tagger import generate_tags as _ai_generate_tags
except Exception as _ai_import_err:
    print(f"ai_tagger not loaded: {_ai_import_err}")
    _ai_generate_tags = None

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "recall-secret-key-2024"
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_MB * 1024 * 1024

# Initialize DB and ensure migrations are applied
@app.after_request
def add_cache_control_headers(response):
    # Prevent browser caching of dynamic HTML so dashboard, items, and counts are ALWAYS instant and fresh
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "-1"
    return response

init_db()

@app.route("/")
def index():
    conn = get_db()
    c = conn.cursor()

    # Core stats
    total = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    notes = c.execute("SELECT COUNT(*) FROM items WHERE type='note'").fetchone()[0]
    links = c.execute("SELECT COUNT(*) FROM items WHERE type='link'").fetchone()[0]
    images = c.execute("SELECT COUNT(*) FROM items WHERE type='image'").fetchone()[0]
    pdfs = c.execute("SELECT COUNT(*) FROM items WHERE type='pdf'").fetchone()[0]
    files = c.execute("SELECT COUNT(*) FROM items WHERE type IN ('image','pdf')").fetchone()[0]
    favourites = c.execute("SELECT COUNT(*) FROM items WHERE favourite=1").fetchone()[0]

    # Category distribution for cards & chart
    cats_raw = c.execute(
        "SELECT category, COUNT(*) as cnt FROM items GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    cats = [{"category": r["category"], "cnt": r["cnt"]} for r in cats_raw]

    # Recent items
    recent = [row_to_dict(r) for r in
              c.execute("SELECT * FROM items ORDER BY created_at DESC LIMIT 8").fetchall()]

    # Favourite items
    fav_items = [row_to_dict(r) for r in
                 c.execute("SELECT * FROM items WHERE favourite=1 ORDER BY created_at DESC LIMIT 6").fetchall()]

    # Upcoming Deadlines / Events extracted from entities
    deadline_items = []
    all_rows = c.execute("SELECT * FROM items WHERE entities LIKE '%is_future%'").fetchall()
    for row in all_rows:
        item_dict = row_to_dict(row)
        ents = item_dict.get("entities", {})
        future_dates = [d for d in ents.get("dates", []) if d.get("is_future")]
        if future_dates:
            deadline_items.append({
                "item": item_dict,
                "deadline": future_dates[0]
            })

    # Sort deadlines by upcoming date
    deadline_items.sort(key=lambda x: x["deadline"].get("iso", "9999-99-99"))
    deadline_items = deadline_items[:5]

    conn.close()
    stats = {
        "total": total,
        "notes": notes,
        "links": links,
        "images": images,
        "pdfs": pdfs,
        "files": files,
        "favourites": favourites,
        "ocr_available": OCR_AVAILABLE,
        "pdf_available": PDF_AVAILABLE
    }
    return render_template(
        "index.html",
        stats=stats,
        recent=recent,
        fav_items=fav_items,
        categories=cats,
        deadline_items=deadline_items
    )


@app.route("/items")
def items():
    conn = get_db()
    c = conn.cursor()

    q         = request.args.get("q", "").strip()
    clean_q   = q.lstrip('#').strip()
    cat       = request.args.get("category", "").strip()
    subcat    = request.args.get("subcategory", "").strip()
    item_type = request.args.get("type", "").strip()
    fav_only  = request.args.get("favourites", "") == "1"
    sort      = request.args.get("sort", "newest")

    # If search query present, search across all relevant fields
    sql = "SELECT * FROM items WHERE 1=1"
    params = []

    if q:
        sql += """ AND (
            title       LIKE ? OR
            description LIKE ? OR
            content     LIKE ? OR
            tags        LIKE ? OR
            category    LIKE ? OR
            subcategory LIKE ? OR
            entities    LIKE ?
        )"""
        like = f"%{clean_q}%"
        params.extend([like, like, like, like, like, like, like])

    if cat:
        sql += " AND category = ?"
        params.append(cat)

    if subcat:
        sql += " AND subcategory = ?"
        params.append(subcat)

    if item_type:
        sql += " AND type = ?"
        params.append(item_type)

    if fav_only:
        sql += " AND favourite = 1"

    order_map = {
        "newest":    "created_at DESC",
        "oldest":    "created_at ASC",
        "az":        "title ASC",
        "za":        "title DESC",
        "updated":   "updated_at DESC",
    }
    sql += f" ORDER BY {order_map.get(sort, 'created_at DESC')}"

    rows = [row_to_dict(r) for r in c.execute(sql, params).fetchall()]
    cats = [r[0] for r in c.execute("SELECT DISTINCT category FROM items ORDER BY category").fetchall()]
    conn.close()

    return render_template(
        "items.html",
        items=rows,
        query=q,
        selected_category=cat,
        selected_subcategory=subcat,
        selected_type=item_type,
        fav_only=fav_only,
        sort=sort,
        categories=cats
    )


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "GET":
        item_type = request.args.get("type", "image")
        return redirect(url_for("index", add=1, type=item_type))

    # ── Smart type detection ──────────────────────────────────────────────────
    # Use the hidden <input name="type"> as a hint, then verify against actual
    # submitted data. This makes upload work even if JavaScript didn't fire.
    _type_hint   = (request.form.get("type", "") or "").strip().lower()
    _uploaded    = request.files.get("file")
    _has_file    = _uploaded and _uploaded.filename not in ("", None)
    _has_url     = bool(request.form.get("url", "").strip())

    if _has_file and _type_hint not in ("image", "pdf"):
        # User uploaded a file but type hint is wrong — auto-detect from extension
        _ext = _uploaded.filename.rsplit(".", 1)[-1].lower() if "." in _uploaded.filename else ""
        from utils import ALLOWED_IMAGE_EXT, ALLOWED_PDF_EXT
        if _ext in ALLOWED_IMAGE_EXT:
            _type_hint = "image"
        elif _ext in ALLOWED_PDF_EXT:
            _type_hint = "pdf"
        else:
            _type_hint = "image"  # fallback

    if _type_hint in ("image", "pdf"):
        item_type = _type_hint
    elif _has_url or _type_hint == "link":
        item_type = "link"
    else:
        item_type = _type_hint if _type_hint in ("note", "link") else "note"

    title           = request.form.get("title", "").strip()
    description     = request.form.get("description", "").strip()
    user_category   = request.form.get("category", "").strip()
    tags_raw        = request.form.get("tags", "").strip()
    favourite       = 1 if request.form.get("favourite") else 0
    tm_label        = request.form.get("tm_label", "").strip()

    if not title:
        if _has_file and _uploaded and _uploaded.filename:
            base_name = os.path.splitext(_uploaded.filename)[0]
            title = re.sub(r'[-_]+', ' ', base_name).strip().title() or "Uploaded Image"
        elif item_type == "link":
            raw_url = request.form.get("url", "").strip()
            title = raw_url.split("//")[-1].split("/")[0] if raw_url else "Saved Link"
        elif item_type == "note":
            content_preview = request.form.get("content", "").strip()
            title = (content_preview[:30] + "...") if content_preview else f"Quick Note ({datetime.now().strftime('%d %b')})"
        else:
            title = f"{item_type.title()} ({datetime.now().strftime('%d %b')})"

    manual_tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
    item_id = str(uuid.uuid4())
    ts = now_iso()

    content  = ""
    url      = ""
    filename = ""
    ai_tags  = []  # populated below for image uploads

    if item_type == "note":
        content = request.form.get("content", "").strip()

    elif item_type == "link":
        url = request.form.get("url", "").strip()
        if not url:
            flash("URL is required for a link.", "error")
            return redirect(url_for("add"))
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        content = description or ""

    elif item_type in ("image", "pdf"):
        file = _uploaded
        if not file or file.filename == "":
            flash("Please select a file to upload.", "error")
            return redirect(url_for("add"))
        if not allowed_file(file.filename):
            flash(f"File type not allowed: .{file.filename.rsplit('.', 1)[-1] if '.' in file.filename else '?'}. Supported: PNG, JPG, JPEG, WEBP, BMP, GIF, JFIF, PDF", "error")
            return redirect(url_for("add"))

        ext      = file.filename.rsplit(".", 1)[1].lower()
        filename = f"{item_id}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        file.save(filepath)

        # OCR runs sync (fast ~1s). AI tagging runs async AFTER save so user is not blocked.
        if item_type == "image":
            content = extract_text_from_image(filepath)
            ai_tags = []   # filled by background thread after redirect
        else:
            content = extract_text_from_pdf(filepath)

    else:
        # This should never happen after auto-detection, but just in case
        flash("Could not determine item type. Please click Note / Link / Image / PDF button first.", "error")
        return redirect(url_for("add"))

    content = clean_text(content)

    # 1. Content Hash & Duplicate Check
    content_hash = compute_content_hash(f"{title} {content}" if content else f"{title} {url}")
    conn = get_db()
    c = conn.cursor()
    existing_dup = c.execute(
        "SELECT id, title FROM items WHERE content_hash = ? AND content_hash != '' LIMIT 1",
        (content_hash,)
    ).fetchone()

    # 2. Entity Extraction
    text_for_ai = f"{title}\n{description}\n{content}"
    entities = extract_entities(text_for_ai)

    # 3. Smart Tags Generation (combine manual + AI image tags + text smart tags)
    smart_tags = generate_smart_tags(text_for_ai)
    # Deduplicate across all three sources; compare without leading "#"
    _seen_tags = set()
    combined_tags = []
    for _tag in (manual_tags + ai_tags + smart_tags):
        _norm = _tag.strip().lstrip("#").lower()
        if _norm and _norm not in _seen_tags:
            _seen_tags.add(_norm)
            # Store without "#" prefix so templates render "#tag" correctly
            combined_tags.append(_tag.strip().lstrip("#").lower())

    # 4. Auto Categorization & Subcategorization
    cat_result = auto_categorize(title, f"{description}\n{content}", tags=combined_tags, tm_label=tm_label)
    category = user_category if (user_category and user_category != "General") else cat_result["category"]
    subcategory = cat_result["subcategory"]

    # Insert into Database
    c.execute("""
        INSERT INTO items (
            id, type, title, description, content, url, filename,
            tags, category, subcategory, entities, content_hash,
            favourite, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id, item_type, title, description, content, url, filename,
        json.dumps(combined_tags), category, subcategory, json.dumps(entities),
        content_hash, favourite, ts, ts
    ))
    conn.commit()

    # Sync to FTS5 virtual table
    sync_item_fts(item_id, conn)
    conn.close()

    success_msg = f'"{title}" saved successfully! Categorized as {category}'
    if subcategory:
        success_msg += f" › {subcategory}"
    if existing_dup:
        success_msg += f' (Note: Similar content already exists in "{existing_dup["title"]}")'

    flash(success_msg, "success")

    # Background AI Tagging - non-blocking so user is redirected immediately
    if item_type == "image" and _ai_generate_tags and filename:
        import threading, datetime as _dt
        _filepath_for_bg = os.path.join(UPLOAD_DIR, filename)
        _manual_tags_bg  = list(manual_tags)
        _user_cat_bg     = user_category
        _tm_label_bg     = tm_label
        _item_id_bg      = item_id

        def _bg_ai_tag():
            try:
                new_ai_tags = _ai_generate_tags(_filepath_for_bg) or []
                _seen = set()
                merged = []
                for t in (_manual_tags_bg + new_ai_tags):
                    n = t.strip().lstrip("#").lower()
                    if n and n not in _seen:
                        _seen.add(n)
                        merged.append(n)
                _conn2 = get_db()
                _row2  = _conn2.execute(
                    "SELECT title, description, content FROM items WHERE id=?",
                    (_item_id_bg,)
                ).fetchone()
                if _row2:
                    _text2 = _row2[0] + "\n" + (_row2[1] or '') + "\n" + (_row2[2] or '')
                    if not _user_cat_bg or _user_cat_bg == "General":
                        _cr2  = auto_categorize(_row2[0], _text2, tags=merged, tm_label=_tm_label_bg)
                        _cat2 = _cr2["category"]
                        _sub2 = _cr2["subcategory"]
                    else:
                        _cat2 = _user_cat_bg
                        _sub2 = ""
                    _now2 = _dt.datetime.utcnow().isoformat()
                    _conn2.execute(
                        "UPDATE items SET tags=?, category=?, subcategory=?, updated_at=? WHERE id=?",
                        (json.dumps(merged), _cat2, _sub2, _now2, _item_id_bg)
                    )
                    _conn2.commit()
                    sync_item_fts(_item_id_bg, _conn2)
                _conn2.close()
                print(f"[BG-AI] Tags updated for {_item_id_bg}: {merged[:5]}")
            except Exception as _bg_err:
                print(f"[BG-AI] Failed for {_item_id_bg}: {_bg_err}")

        threading.Thread(target=_bg_ai_tag, daemon=True).start()

    return redirect(url_for("view_item", item_id=item_id))


@app.route("/item/<item_id>")
def view_item(item_id):
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    item = row_to_dict(row)
    return render_template("view.html", item=item)


@app.route("/item/<item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id):
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    item = row_to_dict(row)

    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category    = request.form.get("category", "General").strip() or "General"
        subcategory = request.form.get("subcategory", "").strip()
        tags_raw    = request.form.get("tags", "").strip()
        favourite   = 1 if request.form.get("favourite") else 0
        content     = request.form.get("content", item["content"] or "").strip()
        url         = request.form.get("url", item["url"] or "").strip()

        if not title:
            flash("Title is required.", "error")
            conn.close()
            return redirect(url_for("edit_item", item_id=item_id))

        tags = [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
        ts   = now_iso()

        # Handle optional new file upload
        new_filename = item["filename"]
        file = request.files.get("file")
        if file and file.filename != "" and allowed_file(file.filename):
            if item["filename"]:
                old_path = os.path.join(UPLOAD_DIR, item["filename"])
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext          = file.filename.rsplit(".", 1)[1].lower()
            new_filename = f"{item_id}.{ext}"
            filepath     = os.path.join(UPLOAD_DIR, new_filename)
            file.save(filepath)
            if item["type"] == "image":
                content = extract_text_from_image(filepath)
            else:
                content = extract_text_from_pdf(filepath)

        content = clean_text(content)
        content_hash = compute_content_hash(f"{title} {content}" if content else f"{title} {url}")
        entities = extract_entities(f"{title}\n{description}\n{content}")

        conn.execute("""
            UPDATE items
            SET title=?, description=?, content=?, url=?, filename=?,
                tags=?, category=?, subcategory=?, entities=?,
                content_hash=?, favourite=?, updated_at=?
            WHERE id=?
        """, (
            title, description, content, url, new_filename,
            json.dumps(tags), category, subcategory, json.dumps(entities),
            content_hash, favourite, ts, item_id
        ))
        conn.commit()
        sync_item_fts(item_id, conn)
        conn.close()

        flash(f'"{title}" updated successfully!', "success")
        return redirect(url_for("view_item", item_id=item_id))

    conn.close()
    return render_template("edit.html", item=item)


@app.route("/item/<item_id>/delete", methods=["POST"])
def delete_item(item_id):
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        abort(404)

    item = row_to_dict(row)
    if item["filename"]:
        filepath = os.path.join(UPLOAD_DIR, item["filename"])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    conn.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    delete_item_fts(item_id, conn)
    conn.close()

    flash(f'"{item["title"]}" deleted.', "info")
    return redirect(url_for("items"))


@app.route("/item/<item_id>/favourite", methods=["POST"])
def toggle_favourite(item_id):
    conn = get_db()
    row  = conn.execute("SELECT favourite FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        abort(404)
    new_fav = 0 if row["favourite"] else 1
    conn.execute("UPDATE items SET favourite=?, updated_at=? WHERE id=?",
                 (new_fav, now_iso(), item_id))
    conn.commit()
    conn.close()
    return jsonify({"favourite": new_fav})


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    filename = secure_filename(filename)
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    clean_q = q.lstrip('#').strip()
    conn = get_db()
    like = f"%{clean_q}%"
    rows = conn.execute("""
        SELECT id, type, title, filename, category, subcategory, tags, content, description
        FROM items
        WHERE title LIKE ? OR description LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ? OR subcategory LIKE ?
        ORDER BY created_at DESC LIMIT 8
    """, (like, like, like, like, like, like)).fetchall()
    
    results = []
    for r in rows:
        d = dict(r)
        # Parse tags safely
        try:
            d["tags"] = json.loads(d.get("tags") or "[]") if isinstance(d.get("tags"), str) else (d.get("tags") or [])
        except Exception:
            d["tags"] = []
        raw_text = d.get("content") or d.get("description") or ""
        d["snippet"] = raw_text[:100] + ("…" if len(raw_text) > 100 else "")
        results.append(d)
        
    conn.close()
    return jsonify(results)


@app.route("/recognise")
@app.route("/recognize")
def recognise():
    return render_template("recognise.html")


if __name__ == "__main__":
    print("=" * 50)
    print("  Recall – Digital Life Organizer")
    print("  Running at http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
