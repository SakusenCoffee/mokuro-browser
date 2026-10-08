import unittest
from unittest import mock

import numpy as np

from mokuro_browser.ocr.covers import CoverOcr, covered_area, merge_cover_text


def block(box, text, *, score=None, font=20, vertical=False):
    x0, y0, x1, y1 = box
    value = {"box": box, "font_size": font, "vertical": vertical, "lines": [text],
             "lines_coords": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]}
    if score is not None:
        value.update(confidence=score, ocr_source="ppocrv6")
    return value


class CoverOcrTests(unittest.TestCase):
    def setUp(self):
        self.white = np.full((400, 500, 3), 255, dtype=np.uint8)
        self.color = np.full((400, 500, 3), (220, 180, 130), dtype=np.uint8)

    def test_cover_replacement_and_independent_missing_title(self):
        manga = [block([20, 20, 200, 50], "性別超趣性")]
        scene = [block([15, 15, 210, 55], "性別超越", score=.95),
                 block([300, 20, 380, 55], "演劇", score=.99)]
        result = merge_cover_text(self.color, manga, scene)
        self.assertEqual({b["lines"][0] for b in result}, {"性別超越", "演劇"})

    def test_plain_dialogue_keeps_manga_recognition_without_duplicates(self):
        manga = [block([20, 20, 100, 40], "ありがとう")]
        scene = [block([15, 15, 105, 45], "ありがとラ", score=.96)]
        self.assertEqual(merge_cover_text(self.white, manga, scene), manga)

    def test_widely_spaced_black_cover_letters_are_replaced(self):
        manga = [block([20, 25, 40, 90], "特別", vertical=True),
                 block([20, 125, 40, 150], "読", vertical=True)]
        scene = [block([15, 20, 45, 200], "特別読切", score=.95, vertical=True)]
        self.assertEqual(merge_cover_text(self.white, manga, scene), scene)

    def test_partial_character_does_not_erase_complete_credit(self):
        manga = [block([20, 20, 45, 150], "原作", vertical=True)]
        scene = [block([15, 20, 50, 60], "原", score=.99)]
        self.assertEqual(merge_cover_text(self.color, manga, scene), manga)

    def test_multiple_cover_lines_can_replace_one_bad_merged_line(self):
        manga = [block([20, 20, 200, 120], "本当に、")]
        scene = [block([20, 20, 200, 60], "演劇", score=.99),
                 block([20, 75, 200, 120], "青春ラブストーリー!!", score=.96)]
        self.assertEqual(merge_cover_text(self.color, manga, scene), scene)

    def test_replacing_one_line_preserves_rest_of_multiline_block(self):
        manga = block([20, 20, 200, 100], "誤読")
        manga["lines"] = ["誤読", "残す行"]
        manga["lines_coords"] = [block([20, 20, 200, 50], "")["lines_coords"][0],
                                  block([20, 70, 200, 100], "")["lines_coords"][0]]
        scene = block([15, 15, 210, 55], "正しい文字", score=.95)
        result = merge_cover_text(self.color, [manga], [scene])
        self.assertEqual([b["lines"] for b in result], [["正しい文字"], ["残す行"]])
        self.assertEqual(result[1]["box"], [20, 70, 200, 100])

    def test_union_coverage_does_not_double_count_overlapping_boxes(self):
        self.assertEqual(covered_area([0, 0, 100, 100],
                                     [[-10, 0, 40, 100], [20, 0, 40, 100]]), 4000)

    def test_low_confidence_unmatched_artifact_is_not_added(self):
        scene = [block([20, 20, 120, 50], "模様", score=.81)]
        self.assertEqual(merge_cover_text(self.color, [], scene), [])

    def test_full_scan_resets_detection_after_recognition_only_retry(self):
        ocr = CoverOcr.__new__(CoverOcr)
        ocr.model = mock.Mock(return_value=mock.Mock(boxes=None, txts=None))
        self.assertEqual(ocr.recognize(self.white), [])
        ocr.model.assert_called_once_with(self.white, use_det=True, use_cls=False, use_rec=True)

    def test_banner_retry_excludes_adjacent_decoration_without_cropping_long_caption(self):
        ocr = CoverOcr.__new__(CoverOcr)
        ocr.model = mock.Mock(return_value=mock.Mock(txts=("演劇",), scores=(.99,)))
        image = self.white.copy()
        image[22:60, 22:110] = (255, 220, 0)
        points = [[20, 20], [140, 20], [140, 64], [20, 64]]
        _, text, score = ocr.refine_banner(image, points, "演劇×", .81)
        self.assertEqual((text, score), ("演劇", .99))
        self.assertFalse(ocr.model.call_args.kwargs["use_det"])
        ocr.model.reset_mock()
        wide = [[20, 20], [400, 20], [400, 64], [20, 64]]
        self.assertEqual(ocr.refine_banner(image, wide, "青春ラブストーリー", .85)[1], "青春ラブストーリー")
        ocr.model.assert_not_called()
