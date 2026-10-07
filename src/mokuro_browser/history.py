"""Local reading history; page aliases and tombstones prevent repeat counts."""
import hashlib
from contextlib import contextmanager
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
    counts = {"characters": 0, "kanji": 0, "kana": 0}
    for char in text:
        if not readable(char):
            continue
        counts["characters"] += 1
        number = ord(char)
        if (0x3400 <= number <= 0x4DBF or 0x4E00 <= number <= 0x9FFF
                or 0xF900 <= number <= 0xFAFF or 0x20000 <= number <= 0x323AF or char == "々"):
            counts["kanji"] += 1
        elif 0x3040 <= number <= 0x30FF or 0x31F0 <= number <= 0x31FF or 0x1B000 <= number <= 0x1B16F:
            counts["kana"] += 1
    return counts


class ReadingHistory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.tagger = None
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pages (id TEXT PRIMARY KEY, title TEXT NOT NULL, scanned_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, page_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lines (
                    id INTEGER PRIMARY KEY, page_id TEXT NOT NULL, position INTEGER NOT NULL,
                    text TEXT NOT NULL, characters INTEGER NOT NULL, kanji INTEGER NOT NULL,
                    kana INTEGER NOT NULL, words INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(page_id, position));
                CREATE INDEX IF NOT EXISTS active_lines ON lines(deleted, id);
            """)

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
        if self.tagger is None:
            # Both packages are already required by manga-ocr. Use its small
            # bundled dictionary even if another incomplete UniDic is installed.
            import fugashi
            import unidic_lite
            self.tagger = fugashi.GenericTagger(f'-r "{unidic_lite.DICDIR}/mecabrc" -d "{unidic_lite.DICDIR}"')
        result = character_counts(text)
        result["words"] = sum(any(readable(char) for char in word.surface)
                              for word in self.tagger(unicodedata.normalize("NFKC", text)))
        return result

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
                db.execute("INSERT INTO pages VALUES (?, ?, ?)", (saved_id, title[:300], time.time()))
                for position, line in enumerate(lines):
                    counts = self.counts(line)
                    db.execute("INSERT INTO lines(page_id,position,text,characters,kanji,kana,words) VALUES(?,?,?,?,?,?,?)",
                               (saved_id, position, line, counts["characters"], counts["kanji"], counts["kana"], counts["words"]))
            for alias in aliases:
                db.execute("INSERT OR IGNORE INTO aliases VALUES (?, ?)", (alias, saved_id))
        return {"saved": not bool(duplicate), "page_id": saved_id}

    def list(self, offset=0, limit=200):
        offset, limit = max(0, int(offset)), min(500, max(1, int(limit)))
        with self.lock, self.connect() as db:
            totals = dict(db.execute("""SELECT COALESCE(SUM(characters),0) AS characters,
                COALESCE(SUM(kanji),0) AS kanji, COALESCE(SUM(kana),0) AS kana,
                COALESCE(SUM(words),0) AS words, COUNT(*) AS lines,
                COUNT(DISTINCT page_id) AS pages FROM lines WHERE deleted=0""").fetchone())
            rows = db.execute("""SELECT lines.id,lines.text,lines.characters,lines.kanji,lines.kana,lines.words,
                pages.title,pages.scanned_at FROM lines JOIN pages ON pages.id=lines.page_id
                WHERE deleted=0 ORDER BY lines.id DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
        return {"totals": totals, "lines": [dict(row) for row in rows], "offset": offset, "limit": limit}

    def edit(self, line_id, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 10000:
            raise ValueError("Enter a nonempty line of at most 10,000 characters.")
        with self.lock, self.connect() as db:
            if not db.execute("SELECT id FROM lines WHERE id=? AND deleted=0", (line_id,)).fetchone():
                raise KeyError("Saved line not found.")
            text = text.strip()
            counts = self.counts(text)
            db.execute("UPDATE lines SET text=?,characters=?,kanji=?,kana=?,words=? WHERE id=?",
                       (text, counts["characters"], counts["kanji"], counts["kana"], counts["words"], line_id))
        return {"updated": True}

    def delete(self, line_id):
        with self.lock, self.connect() as db:
            changed = db.execute("UPDATE lines SET deleted=1,text='',characters=0,kanji=0,kana=0,words=0 WHERE id=? AND deleted=0", (line_id,)).rowcount
            if not changed:
                raise KeyError("Saved line not found.")
        return {"deleted": True}
