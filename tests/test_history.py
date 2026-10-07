from pathlib import Path
import tempfile
import unittest

from mokuro_browser.history import ReadingHistory, character_counts


class ReadingHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "history.sqlite3"
        self.history = ReadingHistory(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_punctuation_is_excluded_and_halfwidth_kana_normalized(self):
        self.assertEqual(character_counts("「日本語、かなカナ！」"), {"characters": 7, "kanji": 3, "kana": 4})
        self.assertEqual(character_counts("ｶﾞ、１２ A! 𠮷"), {"characters": 5, "kanji": 1, "kana": 1})
        self.assertEqual(self.history.counts("私は猫です。")['words'], 4)

    def test_repeat_scans_keep_edits_and_do_not_restore_deleted_text(self):
        self.history.add("a" * 64, "source", ["日本語", "かな"], "Test manga")
        rows = self.history.list()["lines"]
        kana_id, kanji_id = rows[0]["id"], rows[1]["id"]
        self.history.edit(kanji_id, "猫！")
        self.history.delete(kana_id)
        self.assertFalse(self.history.add("a" * 64, "source", ["日本語", "かな"])["saved"])
        # A resized image with identical text on the same page also deduplicates.
        self.assertFalse(self.history.add("b" * 64, "source", ["日本語", "かな"])["saved"])
        saved = ReadingHistory(self.path).list()
        self.assertEqual([line["text"] for line in saved["lines"]], ["猫！"])
        self.assertEqual(saved["totals"]["characters"], 1)
        self.assertEqual(saved["totals"]["kanji"], 1)
        self.assertEqual(saved["totals"]["kana"], 0)

    def test_same_dialogue_on_different_pages_is_counted_separately(self):
        self.history.add("a" * 64, "page-1", ["はい"])
        self.history.add("b" * 64, "page-2", ["はい"])
        self.assertEqual(self.history.list()["totals"]["characters"], 4)
        self.assertEqual(self.history.list()["totals"]["pages"], 2)
        self.assertEqual(len(self.history.list(offset=1, limit=1)["lines"]), 1)

    def test_invalid_edits_leave_saved_text_intact(self):
        self.history.add("a" * 64, "source", ["猫"])
        line_id = self.history.list()["lines"][0]["id"]
        with self.assertRaises(ValueError):
            self.history.edit(line_id, "  ")
        self.assertEqual(self.history.list()["lines"][0]["text"], "猫")

    def test_empty_scan_does_not_prevent_later_text_recovery(self):
        self.history.add("a" * 64, "source", [])
        self.assertTrue(self.history.add("a" * 64, "source", ["猫"])["saved"])
