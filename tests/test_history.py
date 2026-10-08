from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from mokuro_browser.history import ReadingHistory, character_counts


class ReadingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "history.sqlite3"
        self.history = ReadingHistory(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_punctuation_is_excluded_and_halfwidth_kana_normalized(self):
        self.assertEqual(character_counts("「日本語、かなカナ！」"),
                         {"characters": 7, "kanji": 3, "hiragana": 2, "katakana": 2})
        self.assertEqual(character_counts("ｶﾞ、１２ A! 𠮷"),
                         {"characters": 5, "kanji": 1, "hiragana": 0, "katakana": 1})
        self.assertEqual(character_counts("ひらがな カタカナー 々"),
                         {"characters": 10, "kanji": 1, "hiragana": 4, "katakana": 5})
        self.assertNotIn("words", self.history.counts("私は猫です。"))

    def test_all_page_text_is_saved_and_edited_together(self):
        self.history.add("a" * 64, "source", ["日本語", "かな", "カナ"], "Test manga")
        saved = self.history.list()
        self.assertEqual(len(saved["pages"]), 1)
        self.assertEqual(saved["pages"][0]["text"], "日本語\nかな\nカナ")
        self.assertEqual(saved["totals"], {"characters": 7, "kanji": 3, "hiragana": 2, "katakana": 2, "pages": 1})
        self.history.edit("a" * 64, "猫！\nにゃー ニャー")
        self.assertEqual(self.history.list()["pages"][0]["text"], "猫！\nにゃー ニャー")
        self.assertEqual(self.history.list()["totals"]["characters"], 7)

    def test_repeat_scans_keep_edits_and_do_not_restore_deleted_text(self):
        self.history.add("a" * 64, "source", ["日本語", "かな"], "Test manga")
        self.history.edit("a" * 64, "猫！")
        self.assertFalse(self.history.add("a" * 64, "source", ["日本語", "かな"])["saved"])
        # A resized image with identical text on the same page also deduplicates.
        self.assertFalse(self.history.add("b" * 64, "source", ["日本語", "かな"])["saved"])
        saved = ReadingHistory(self.path).list()
        self.assertEqual([page["text"] for page in saved["pages"]], ["猫！"])
        self.assertEqual(saved["totals"]["characters"], 1)
        self.assertEqual(saved["totals"]["kanji"], 1)
        self.assertEqual(saved["totals"]["hiragana"], 0)
        self.assertEqual(saved["totals"]["katakana"], 0)
        self.history.delete("a" * 64)
        self.assertFalse(self.history.add("a" * 64, "source", ["日本語", "かな"])["saved"])
        self.assertFalse(self.history.add("b" * 64, "source", ["日本語", "かな"])["saved"])
        self.assertEqual(ReadingHistory(self.path).list()["totals"]["pages"], 0)

    def test_same_dialogue_on_different_pages_is_counted_separately(self):
        self.history.add("a" * 64, "page-1", ["はい"])
        self.history.add("b" * 64, "page-2", ["はい"])
        self.assertEqual(self.history.list()["totals"]["characters"], 4)
        self.assertEqual(self.history.list()["totals"]["pages"], 2)
        self.assertEqual(len(self.history.list(offset=1, limit=1)["pages"]), 1)
        self.assertEqual(self.history.list(limit=1)["pages"][0]["id"], "b" * 64)

    def test_invalid_edits_leave_saved_text_intact(self):
        self.history.add("a" * 64, "source", ["猫"])
        with self.assertRaises(ValueError):
            self.history.edit("a" * 64, "  ")
        with self.assertRaises(KeyError):
            self.history.edit("b" * 64, "猫")
        self.assertEqual(self.history.list()["pages"][0]["text"], "猫")

    def test_multi_page_delete_is_atomic_and_deduplicates_selection(self):
        for page_id in ("a" * 64, "b" * 64):
            self.history.add(page_id, page_id, ["猫", "かな"])
        with self.assertRaises(KeyError):
            self.history.delete_pages(["a" * 64, "c" * 64])
        self.assertEqual(self.history.list()["totals"]["pages"], 2)
        with self.assertRaises(ValueError):
            self.history.delete_pages([])
        result = self.history.delete_pages(["a" * 64, "b" * 64, "a" * 64])
        self.assertEqual(result["pages"], 2)
        self.assertEqual(self.history.list()["totals"]["characters"], 0)
        self.assertFalse(self.history.add("a" * 64, "a" * 64, ["猫", "かな"])["saved"])

    def test_legacy_migration_preserves_order_edits_deletions_and_aliases(self):
        path = self.path.with_name("legacy.sqlite3")
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE pages(id TEXT PRIMARY KEY,title TEXT NOT NULL,scanned_at REAL NOT NULL);
                CREATE TABLE aliases(alias TEXT PRIMARY KEY,page_id TEXT NOT NULL);
                CREATE TABLE lines(id INTEGER PRIMARY KEY,page_id TEXT NOT NULL,position INTEGER NOT NULL,
                    text TEXT NOT NULL,characters INTEGER NOT NULL,kanji INTEGER NOT NULL,kana INTEGER NOT NULL,
                    words INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,UNIQUE(page_id,position));
            """)
            db.executemany("INSERT INTO pages VALUES(?,?,?)", [("a" * 64, "Old page", 1), ("b" * 64, "Deleted", 2)])
            # Deliberately wrong legacy counts: migration must count the edited text.
            db.executemany("INSERT INTO lines VALUES(?,?,?,?,?,?,?,?,?)", [
                (1, "a" * 64, 1, "カナ！", 99, 99, 99, 99, 0),
                (2, "a" * 64, 0, "猫\nかな", 99, 99, 99, 99, 0),
                (3, "a" * 64, 2, "", 0, 0, 0, 0, 1),
                (4, "b" * 64, 0, "", 0, 0, 0, 0, 1)])
            db.executemany("INSERT INTO aliases VALUES(?,?)", [("image:" + page_id, page_id)
                            for page_id in ("a" * 64, "b" * 64)])
        with mock.patch("mokuro_browser.history.character_counts", side_effect=RuntimeError("conversion stopped")):
            with self.assertRaisesRegex(RuntimeError, "conversion stopped"):
                ReadingHistory(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertNotIn("text", {row[1] for row in db.execute("PRAGMA table_info(pages)")})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lines").fetchone()[0], 4)
        migrated = ReadingHistory(path)
        saved = migrated.list()
        self.assertEqual(saved["totals"], {"characters": 5, "kanji": 1, "hiragana": 2, "katakana": 2, "pages": 1})
        self.assertEqual(saved["pages"][0]["text"], "猫\nかな\nカナ！")
        self.assertEqual(saved["pages"][0]["title"], "Old page")
        self.assertFalse(migrated.add("a" * 64, "source", ["Original OCR"])["saved"])
        self.assertFalse(migrated.add("b" * 64, "source", ["Deleted OCR"])["saved"])
        migrated.edit("a" * 64, "犬")
        self.assertEqual(ReadingHistory(path).list()["pages"][0]["text"], "犬")
        backup = path.with_suffix(".before-page-history.sqlite3")
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM lines").fetchone()[0], 4)

    def test_empty_scan_does_not_prevent_later_text_recovery(self):
        self.history.add("a" * 64, "source", [])
        self.assertTrue(self.history.add("a" * 64, "source", ["猫"])["saved"])
