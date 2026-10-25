import os
import re
import uuid
import json
import sqlite3
import concurrent.futures
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory, abort, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
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
app.secret_key = os.getenv("SECRET_KEY", "recall-secret-key-2024-secure-v2")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
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

# ── Authentication & User Session Helpers ────────────────────
def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    row = conn.execute("SELECT id, email, username, created_at FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}

EXEMPT_ENDPOINTS = {"login", "register", "static", "ping"}

@app.before_request
def require_login():
    endpoint = request.endpoint
    if not endpoint:
        return None
    if endpoint in EXEMPT_ENDPOINTS or endpoint.startswith("static"):
        return None
    user = get_current_user()
    if not user:
        session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))


@app.route("/ping")
def ping():
    return jsonify({"status": "alive", "service": "recall"}), 200
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip().lower()
        password = request.form.get("password", "")
        if not login_id or not password:
            flash("Please enter your email/username and password.", "error")
            return render_template("login.html")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE LOWER(email)=? OR LOWER(username)=?",
            (login_id, login_id)
        ).fetchone()

        # If user not found (e.g. Render container restart), auto-register owner or first user
        if not user:
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if user_count == 0 or login_id in ("n7159852@gmail.com", "akku"):
                user_id = str(uuid.uuid4())
                pw_hash = generate_password_hash(password)
                uname = "akku" if login_id in ("n7159852@gmail.com", "akku") else login_id.split("@")[0]
                uemail = "n7159852@gmail.com" if login_id in ("n7159852@gmail.com", "akku") else (login_id if "@" in login_id else f"{login_id}@recall.local")
                conn.execute(
                    "INSERT INTO users (id, email, username, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, uemail, uname, pw_hash, now_iso())
                )
                conn.execute("UPDATE items SET user_id=? WHERE user_id='' OR user_id IS NULL", (user_id,))
                conn.commit()
                user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

        if not user:
            conn.close()
            flash("Invalid email/username or password.", "error")
            return render_template("login.html")

        # Check password or auto-update for owner so they are never locked out
        if not check_password_hash(user["password_hash"], password):
            if login_id in ("n7159852@gmail.com", "akku") or user["email"] == "n7159852@gmail.com":
                new_hash = generate_password_hash(password)
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user["id"]))
                conn.commit()
            else:
                conn.close()
                flash("Invalid email/username or password.", "error")
                return render_template("login.html")

        session.permanent = True
        session["user_id"] = user["id"]
        session["username"] = user["username"]

        # Ensure any orphan items in DB are assigned to logged-in user
        conn.execute("UPDATE items SET user_id=? WHERE user_id='' OR user_id IS NULL", (user["id"],))
        conn.commit()
        conn.close()

        flash(f"Welcome back, {user['username']}!", "success")
        next_url = request.form.get("next") or request.args.get("next")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM users WHERE LOWER(email)=? OR LOWER(username)=?",
            (email, username.lower())
        ).fetchone()
        if existing:
            conn.close()
            flash("An account with this email or username already exists. Please sign in.", "error")
            return render_template("register.html")

        user_id = str(uuid.uuid4())
        pw_hash = generate_password_hash(password)
        created_at = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT INTO users (id, email, username, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, username, pw_hash, created_at)
        )

        # Migration: Assign orphan items to the first registered user
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 1:
            conn.execute("UPDATE items SET user_id=? WHERE user_id='' OR user_id IS NULL", (user_id,))
            try:
                conn.execute("UPDATE items_fts SET user_id=? WHERE user_id='' OR user_id IS NULL", (user_id,))
            except Exception:
                pass

        conn.commit()
        conn.close()

        session.permanent = True
        session["user_id"] = user_id
        session["username"] = username
        flash(f"Account created successfully! Welcome to Recall, {username}!", "success")
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/")
def index():
    user_id = session.get("user_id")
    conn = get_db()
    c = conn.cursor()

    # Core stats for logged-in user
    total = c.execute("SELECT COUNT(*) FROM items WHERE user_id=?", (user_id,)).fetchone()[0]
    notes = c.execute("SELECT COUNT(*) FROM items WHERE type='note' AND user_id=?", (user_id,)).fetchone()[0]
    links = c.execute("SELECT COUNT(*) FROM items WHERE type='link' AND user_id=?", (user_id,)).fetchone()[0]
    images = c.execute("SELECT COUNT(*) FROM items WHERE type='image' AND user_id=?", (user_id,)).fetchone()[0]
    pdfs = c.execute("SELECT COUNT(*) FROM items WHERE type='pdf' AND user_id=?", (user_id,)).fetchone()[0]
    files = c.execute("SELECT COUNT(*) FROM items WHERE type IN ('image','pdf') AND user_id=?", (user_id,)).fetchone()[0]
    favourites = c.execute("SELECT COUNT(*) FROM items WHERE favourite=1 AND user_id=?", (user_id,)).fetchone()[0]

    # Category distribution for cards & chart
    cats_raw = c.execute(
        "SELECT category, COUNT(*) as cnt FROM items WHERE user_id=? GROUP BY category ORDER BY cnt DESC",
        (user_id,)
    ).fetchall()
    cats = [{"category": r["category"], "cnt": r["cnt"]} for r in cats_raw]

    # Recent items
    recent = [row_to_dict(r) for r in
              c.execute("SELECT * FROM items WHERE user_id=? ORDER BY created_at DESC LIMIT 8", (user_id,)).fetchall()]

    # Favourite items
    fav_items = [row_to_dict(r) for r in
                 c.execute("SELECT * FROM items WHERE favourite=1 AND user_id=? ORDER BY created_at DESC LIMIT 6", (user_id,)).fetchall()]

    # Upcoming Deadlines / Events extracted from entities
    deadline_items = []
    all_rows = c.execute("SELECT * FROM items WHERE user_id=? AND entities LIKE '%is_future%'", (user_id,)).fetchall()
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
    user_id = session.get("user_id")
    conn = get_db()
    c = conn.cursor()

    q         = request.args.get("q", "").strip()
    clean_q   = q.lstrip('#').strip()
    cat       = request.args.get("category", "").strip()
    subcat    = request.args.get("subcategory", "").strip()
    item_type = request.args.get("type", "").strip()
    fav_only  = request.args.get("favourites", "") == "1"
    sort      = request.args.get("sort", "newest")

    # If search query present, search across user's items
    sql = "SELECT * FROM items WHERE user_id = ?"
    params = [user_id]

    if q:
        tokens = [t.strip() for t in clean_q.split() if t.strip()]
        if len(tokens) > 1:
            clause_parts = []
            for token in tokens:
                t_like = f"%{token}%"
                clause_parts.append("""(
                    title       LIKE ? OR
                    description LIKE ? OR
                    content     LIKE ? OR
                    tags        LIKE ? OR
                    category    LIKE ? OR
                    subcategory LIKE ? OR
                    entities    LIKE ?
                )""")
                params.extend([t_like] * 7)
            full_like = f"%{clean_q}%"
            full_clause = """(
                title       LIKE ? OR
                description LIKE ? OR
                content     LIKE ? OR
                tags        LIKE ? OR
                category    LIKE ? OR
                subcategory LIKE ? OR
                entities    LIKE ?
            )"""
            params.extend([full_like] * 7)
            sql += f" AND (({' AND '.join(clause_parts)}) OR {full_clause})"
        else:
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
            params.extend([like] * 7)

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
    cats = [r[0] for r in c.execute("SELECT DISTINCT category FROM items WHERE user_id=? ORDER BY category", (user_id,)).fetchall()]
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
    user_id = session.get("user_id")
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
    favourite = 1 if request.form.get("favourite") == "1" else 0
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
        "SELECT id, title FROM items WHERE content_hash = ? AND content_hash != '' AND user_id = ? LIMIT 1",
        (content_hash, user_id)
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

    # Insert into Database with user_id
    c.execute("""
        INSERT INTO items (
            id, user_id, type, title, description, content, url, filename,
            tags, category, subcategory, entities, content_hash,
            favourite, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id, user_id, item_type, title, description, content, url, filename,
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

    # Background AI Tagging & OCR - non-blocking so user is redirected immediately
    if item_type == "image" and filename:
        import threading, datetime as _dt
        _filepath_for_bg = os.path.join(UPLOAD_DIR, filename)
        _manual_tags_bg  = list(manual_tags)
        _user_cat_bg     = user_category
        _tm_label_bg     = tm_label
        _item_id_bg      = item_id

        def _bg_ai_tag():
            try:
                from ai_tagger import analyze_image
                ai_data = analyze_image(_filepath_for_bg)
                new_ai_tags = ai_data.get("tags") or []
                ai_text = ai_data.get("extracted_text") or ""
                ai_summary = ai_data.get("summary") or ""
                ai_cat = ai_data.get("category") or ""

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
                    curr_title = _row2[0] or ""
                    curr_desc  = _row2[1] or ""
                    curr_cont  = _row2[2] or ""

                    # Populate OCR text and summary if empty (e.g. on Render)
                    final_cont = curr_cont if curr_cont.strip() else ai_text
                    final_desc = curr_desc if curr_desc.strip() else ai_summary

                    _text2 = curr_title + "\n" + final_desc + "\n" + final_cont
                    if not _user_cat_bg or _user_cat_bg == "General":
                        _cr2  = auto_categorize(curr_title, _text2, tags=merged, tm_label=_tm_label_bg)
                        _cat2 = _cr2["category"] if _cr2["category"] != "General" else (ai_cat or "General")
                        _sub2 = _cr2["subcategory"]
                    else:
                        _cat2 = _user_cat_bg
                        _sub2 = ""
                    _now2 = _dt.datetime.utcnow().isoformat()
                    _conn2.execute(
                        "UPDATE items SET tags=?, category=?, subcategory=?, content=?, description=?, updated_at=? WHERE id=?",
                        (json.dumps(merged), _cat2, _sub2, final_cont, final_desc, _now2, _item_id_bg)
                    )
                    _conn2.commit()
                    sync_item_fts(_item_id_bg, _conn2)
                _conn2.close()
                print(f"[BG-AI] AI tagging completed for {_item_id_bg}: {len(merged)} tags, {len(final_cont)} chars text")
            except Exception as _bg_err:
                print(f"[BG-AI] Failed for {_item_id_bg}: {_bg_err}")

        threading.Thread(target=_bg_ai_tag, daemon=True).start()

    return redirect(url_for("view_item", item_id=item_id))


@app.route("/item/<item_id>")
def view_item(item_id):
    user_id = session.get("user_id")
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=? AND user_id=?", (item_id, user_id)).fetchone()
    conn.close()
    if not row:
        abort(404)
    item = row_to_dict(row)
    return render_template("view.html", item=item)


@app.route("/item/<item_id>/edit", methods=["GET", "POST"])
def edit_item(item_id):
    user_id = session.get("user_id")
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=? AND user_id=?", (item_id, user_id)).fetchone()
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
        favourite = 1 if request.form.get("favourite") == "1" else 0
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
            WHERE id=? AND user_id=?
        """, (
            title, description, content, url, new_filename,
            json.dumps(tags), category, subcategory, json.dumps(entities),
            content_hash, favourite, ts, item_id, user_id
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
    user_id = session.get("user_id")
    conn = get_db()
    row  = conn.execute("SELECT * FROM items WHERE id=? AND user_id=?", (item_id, user_id)).fetchone()
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

    conn.execute("DELETE FROM items WHERE id=? AND user_id=?", (item_id, user_id))
    conn.commit()
    delete_item_fts(item_id, conn)
    conn.close()

    flash(f'"{item["title"]}" deleted.', "info")
    return redirect(url_for("items"))


@app.route("/item/<item_id>/favourite", methods=["POST"])
def toggle_favourite(item_id):
    user_id = session.get("user_id")
    conn = get_db()
    row  = conn.execute("SELECT favourite FROM items WHERE id=? AND user_id=?", (item_id, user_id)).fetchone()
    if not row:
        conn.close()
        abort(404)
    new_fav = 0 if row["favourite"] else 1
    conn.execute("UPDATE items SET favourite=?, updated_at=? WHERE id=? AND user_id=?",
                 (new_fav, now_iso(), item_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"favourite": new_fav})


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    user_id = session.get("user_id")
    filename = secure_filename(filename)
    conn = get_db()
    item = conn.execute("SELECT id FROM items WHERE filename=? AND user_id=?", (filename, user_id)).fetchone()
    conn.close()
    if not item:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/search")
def api_search():
    user_id = session.get("user_id")
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    clean_q = q.lstrip('#').strip()
    conn = get_db()
    tokens = [t.strip() for t in clean_q.split() if t.strip()]
    params = []
    if len(tokens) > 1:
        clause_parts = []
        for token in tokens:
            t_like = f"%{token}%"
            clause_parts.append("(title LIKE ? OR description LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ? OR subcategory LIKE ?)")
            params.extend([t_like] * 6)
        full_like = f"%{clean_q}%"
        params.extend([full_like] * 6)
        where_sql = f"(({' AND '.join(clause_parts)}) OR (title LIKE ? OR description LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ? OR subcategory LIKE ?))"
    else:
        like = f"%{clean_q}%"
        where_sql = "(title LIKE ? OR description LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ? OR subcategory LIKE ?)"
        params = [like] * 6

    final_params = [user_id] + params
    rows = conn.execute(f"""
        SELECT id, type, title, filename, category, subcategory, tags, content, description
        FROM items
        WHERE user_id = ? AND ({where_sql})
        ORDER BY created_at DESC LIMIT 8
    """, final_params).fetchall()
    
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


@app.route("/item/<item_id>/ai-retag", methods=["POST"])
def retag_item(item_id):
    user_id = session.get("user_id")
    conn = get_db()
    row = conn.execute("SELECT * FROM items WHERE id=? AND user_id=?", (item_id, user_id)).fetchone()
    if not row:
        conn.close()
        abort(404)
    item = row_to_dict(row)
    if item["type"] != "image" or not item["filename"]:
        conn.close()
        flash("AI analysis is only available for images.", "warning")
        return redirect(url_for("view_item", item_id=item_id))

    filepath = os.path.join(UPLOAD_DIR, item["filename"])
    from ai_tagger import analyze_image
    ai_data = analyze_image(filepath)

    new_tags = ai_data.get("tags") or []
    ai_text = ai_data.get("extracted_text") or ""
    ai_summary = ai_data.get("summary") or ""
    ai_cat = ai_data.get("category") or "General"

    existing_tags = item.get("tags") or []
    _seen = set()
    merged = []
    for t in (existing_tags + new_tags):
        n = t.strip().lstrip("#").lower()
        if n and n not in _seen:
            _seen.add(n)
            merged.append(n)

    final_cont = item["content"] if (item["content"] and item["content"].strip()) else ai_text
    final_desc = item["description"] if (item["description"] and item["description"].strip()) else ai_summary
    final_cat = item["category"] if (item["category"] and item["category"] != "General") else ai_cat

    now_ts = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE items SET tags=?, content=?, description=?, category=?, updated_at=? WHERE id=? AND user_id=?",
        (json.dumps(merged), final_cont, final_desc, final_cat, now_ts, item_id, user_id)
    )
    conn.commit()
    sync_item_fts(item_id, conn)
    conn.close()
    flash(f"Gemini AI analyzed image! Added #{', #'.join(new_tags[:4])}", "success")
    return redirect(url_for("view_item", item_id=item_id))


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
