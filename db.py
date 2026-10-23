import os
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'recall.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id           TEXT PRIMARY KEY,
            type         TEXT NOT NULL,
            title        TEXT NOT NULL,
            description  TEXT,
            content      TEXT,
            url          TEXT,
            filename     TEXT,
            tags         TEXT DEFAULT '[]',
            category     TEXT DEFAULT 'General',
            subcategory  TEXT DEFAULT '',
            entities     TEXT DEFAULT '{}',
            content_hash TEXT DEFAULT '',
            favourite    INTEGER DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
    """)

    existing_cols = [row[1] for row in c.execute('PRAGMA table_info(items)').fetchall()]
    if 'subcategory' not in existing_cols:
        c.execute("ALTER TABLE items ADD COLUMN subcategory TEXT DEFAULT ''")
    if 'entities' not in existing_cols:
        c.execute("ALTER TABLE items ADD COLUMN entities TEXT DEFAULT '{}'")
    if 'content_hash' not in existing_cols:
        c.execute("ALTER TABLE items ADD COLUMN content_hash TEXT DEFAULT ''")

    try:
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                id UNINDEXED,
                title,
                description,
                content,
                tags,
                category,
                subcategory,
                entities
            )
        """)
        fts_count = c.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0]
        items_count = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        if fts_count < items_count:
            c.execute("DELETE FROM items_fts")
            c.execute("""
                INSERT INTO items_fts (id, title, description, content, tags, category, subcategory, entities)
                SELECT id, title, description, content, tags, category, subcategory, entities FROM items
            """)
    except Exception as e:
        print(f"FTS init: {e}")

    conn.commit()
    conn.close()

def sync_item_fts(item_id, conn=None):
    close_at_end = False
    if conn is None:
        conn = get_db()
        close_at_end = True
    try:
        c = conn.cursor()
        item = c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        c.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        if item:
            c.execute("""
                INSERT INTO items_fts (id, title, description, content, tags, category, subcategory, entities)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item['id'],
                item['title'] or '',
                item['description'] or '',
                item['content'] or '',
                item['tags'] or '',
                item['category'] or '',
                item['subcategory'] or '',
                item['entities'] or ''
            ))
        conn.commit()
    except Exception as e:
        print(f"Error syncing FTS: {e}")
    finally:
        if close_at_end:
            conn.close()

def delete_item_fts(item_id, conn=None):
    close_at_end = False
    if conn is None:
        conn = get_db()
        close_at_end = True
    try:
        c = conn.cursor()
        c.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        if close_at_end:
            conn.close()

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    try:
        raw_tags = d.get('tags')
        if isinstance(raw_tags, str):
            d['tags'] = json.loads(raw_tags or '[]')
        elif not isinstance(raw_tags, list):
            d['tags'] = []
    except Exception:
        d['tags'] = []

    try:
        raw_entities = d.get('entities')
        if isinstance(raw_entities, str):
            d['entities'] = json.loads(raw_entities or '{}')
        elif not isinstance(raw_entities, dict):
            d['entities'] = {}
    except Exception:
        d['entities'] = {}

    return d
