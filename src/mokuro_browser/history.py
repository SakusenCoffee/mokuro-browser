"""Local reading history; page aliases and tombstones prevent repeat counts."""
import hashlib
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import unicodedata


def readable(char):
    return unicodedata.category(char)[0] in "LN"


def character_counts(text):
    text = unicodedata.normalize("NFKC", text)
    counts = {"characters": 0, "kanji": 0, "hiragana": 0, "katakana": 0}
    for char in text:
        if not readable(char):
            continue
        counts["characters"] += 1
        number = ord(char)
        if (0x3400 <= number <= 0x4DBF or 0x4E00 <= number <= 0x9FFF
                or 0xF900 <= number <= 0xFAFF or 0x20000 <= number <= 0x323AF or char == "々"):
            counts["kanji"] += 1
        else:
            name = unicodedata.name(char, "")
            if name.startswith(("HIRAGANA ", "HENTAIGANA ")):
                counts["hiragana"] += 1
            elif name.startswith("KATAKANA"):
                counts["katakana"] += 1
    return counts


class ReadingHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pages (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, scanned_at REAL NOT NULL,
                    text TEXT NOT NULL, characters INTEGER NOT NULL, kanji INTEGER NOT NULL,
                    hiragana INTEGER NOT NULL, katakana INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, page_id TEXT NOT NULL);
            """)
            if "text" not in {row["name"] for row in db.execute("PRAGMA table_info(pages)")}:
                self.migrate_lines(db)
            db.execute("CREATE INDEX IF NOT EXISTS active_pages ON pages(deleted, scanned_at)")

    def migrate_lines(self, db):
        """Atomically regroup legacy lines, preserving edits, deletions and aliases."""
        # Keep a one-time SQLite backup before replacing the old layout. SQLite's
        # backup API also includes committed data that is still in a WAL file.
        backup = self.path.with_suffix(".before-page-history.sqlite3")
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as previous:
                db.backup(previous)
        db.execute("BEGIN IMMEDIATE")
        db.execute("ALTER TABLE pages ADD COLUMN text TEXT NOT NULL DEFAULT ''")
        for name in ("characters", "kanji", "hiragana", "katakana", "deleted"):
            db.execute(f"ALTER TABLE pages ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
        texts = {}
        for row in db.execute("SELECT page_id,text FROM lines WHERE deleted=0 ORDER BY position,id"):
            texts.setdefault(row["page_id"], []).append(row["text"])
        for row in db.execute("SELECT id FROM pages").fetchall():
            text = "\n".join(texts.get(row["id"], []))
            counts = character_counts(text)
            db.execute("UPDATE pages SET text=?,characters=?,kanji=?,hiragana=?,katakana=?,deleted=? WHERE id=?",
                       (text, counts["characters"], counts["kanji"], counts["hiragana"], counts["katakana"],
                        int(not bool(text)), row["id"]))
        db.execute("DROP TABLE lines")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def counts(self, text):
        return character_counts(text)

    def add(self, page_id, source_key, lines, title=""):
        if (not isinstance(page_id, str) or len(page_id) != 64
                or any(c not in "0123456789abcdef" for c in page_id)
                or not isinstance(source_key, str) or len(source_key) > 128
                or not isinstance(lines, list) or len(lines) > 2000
                or any(not isinstance(line, str) or len(line) > 10000 for line in lines)
                or not isinstance(title, str)):
            raise ValueError("Invalid reading history page.")
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            return {"saved": False, "page_id": page_id}
        signature = hashlib.sha256(json.dumps([source_key, lines], ensure_ascii=False).encode()).hexdigest()
        aliases = ("image:" + page_id, "text:" + signature)
        with self.lock, self.connect() as db:
            duplicate = db.execute("SELECT page_id FROM aliases WHERE alias IN (?, ?)", aliases).fetchone()
            saved_id = duplicate["page_id"] if duplicate else page_id
            if not duplicate:
                text = "\n".join(lines)
                counts = self.counts(text)
                db.execute("""INSERT INTO pages(id,title,scanned_at,text,characters,kanji,hiragana,katakana)
                    VALUES(?,?,?,?,?,?,?,?)""",
                           (saved_id, title[:300], time.time(), text, counts["characters"], counts["kanji"],
                            counts["hiragana"], counts["katakana"]))
            for alias in aliases:
                db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (alias, saved_id))
        return {"saved": not bool(duplicate), "page_id": saved_id}

    def list(self, offset=0, limit=200):
        offset, limit = max(0, int(offset)), min(500, max(1, int(limit)))
        with self.lock, self.connect() as db:
            totals = dict(db.execute("""SELECT COALESCE(SUM(characters),0) AS characters,
                COALESCE(SUM(kanji),0) AS kanji, COALESCE(SUM(hiragana),0) AS hiragana,
                COALESCE(SUM(katakana),0) AS katakana, COUNT(*) AS pages FROM pages WHERE deleted=0""").fetchone())
            rows = db.execute("""SELECT id,text,characters,kanji,hiragana,katakana,title,scanned_at FROM pages
                WHERE deleted=0 ORDER BY scanned_at DESC,id DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        return {"totals": totals, "pages": [dict(row) for row in rows], "offset": offset, "limit": limit}

    def edit(self, page_id, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 100000:
            raise ValueError("Enter nonempty page text of at most 100,000 characters.")
        with self.lock, self.connect() as db:
            if not db.execute("SELECT id FROM pages WHERE id=? AND deleted=0", (page_id,)).fetchone():
                raise KeyError("Saved page not found.")
            text = text.strip()
            counts = self.counts(text)
            db.execute("UPDATE pages SET text=?,characters=?,kanji=?,hiragana=?,katakana=? WHERE id=?",
                       (text, counts["characters"], counts["kanji"], counts["hiragana"], counts["katakana"], page_id))
        return {"updated": True}

    def delete(self, page_id):
        return self.delete_pages([page_id])

    def delete_pages(self, page_ids):
        if (not isinstance(page_ids, list) or not 1 <= len(page_ids) <= 500
                or any(not isinstance(page_id, str) or len(page_id) != 64
                       or any(c not in "0123456789abcdef" for c in page_id) for page_id in page_ids)):
            raise ValueError("Select between 1 and 500 saved pages to delete.")
        page_ids = list(dict.fromkeys(page_ids))
        placeholders = ",".join("?" for _ in page_ids)
        with self.lock, self.connect() as db:
            count = db.execute(f"SELECT COUNT(*) FROM pages WHERE id IN ({placeholders}) AND deleted=0", page_ids).fetchone()[0]
            if count != len(page_ids):
                raise KeyError("Saved page not found. Refresh history and try again.")
            db.execute(f"""UPDATE pages SET deleted=1,text='',characters=0,kanji=0,hiragana=0,katakana=0
                WHERE id IN ({placeholders})""", page_ids)
        return {"deleted": True, "pages": len(page_ids)}
