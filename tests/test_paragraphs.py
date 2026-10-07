"""Synthetic regressions: no manga pages are distributed with this project."""
import unittest
import cv2
import numpy as np
from comic_text_detector.utils.textblock import TextBlock
from mokuro_browser.ocr.paragraphs import recover_paragraphs

def paragraph(full_rows=3, ending=2):
    image = np.full((650, 450, 3), 255, np.uint8)
    for index in range(full_rows + 1):
        y = 60 + index * 40
        count = 8 if index < full_rows else ending
        for x in range(60, 60 + count * 30, 30):
            cv2.rectangle(image, (x, y), (x+20, y+20), (0, 0, 0), 2)
            cv2.line(image, (x+10, y), (x+10, y+20), (0, 0, 0), 2)
    end = 60 + full_rows * 40
    polygon = [[55,55], [300,55], [300,end+25], [55,end+25]]
    original = TextBlock([55,55,300,end+25], [polygon], vertical=False, font_size=20)
    return image, original, polygon, end

class ParagraphTests(unittest.TestCase):
    def test_short_final_row_is_recovered(self):
        image, original, _, end = paragraph()
        recovered = recover_paragraphs(image, [original])
        self.assertTrue(any(getattr(block, "mokuro_paragraph", False) for block in recovered))
        self.assertTrue(any(np.asarray(line)[:,1].min() <= end and np.asarray(line)[:,1].max() >= end+21
                            for block in recovered for line in block.lines))

    def test_unrecovered_single_glyph_keeps_original_detection(self):
        for rows in (3, 4, 5, 8, 10):
            with self.subTest(rows=rows):
                image, original, polygon, _ = paragraph(rows, ending=1)
                recovered = recover_paragraphs(image, [original])
                self.assertTrue(any(np.array_equal(line, polygon) for b in recovered for line in b.lines))

    def test_small_fragments_cannot_start_a_paragraph(self):
        image, original, _, _ = paragraph(full_rows=0, ending=3)
        self.assertEqual(recover_paragraphs(image, [original]), [original])

    def test_detector_support_is_required(self):
        image, _, _, _ = paragraph()
        self.assertEqual(recover_paragraphs(image, []), [])

    def test_vertical_grid_stays_vertical(self):
        image = np.full((400, 400, 3), 255, np.uint8)
        lines = []
        for x in range(60, 301, 40):
            lines.append([[x,60],[x+20,60],[x+20,220],[x,220]])
            for y in range(60, 201, 40):
                cv2.rectangle(image, (x,y), (x+20,y+20), (0,0,0), 2)
                cv2.line(image, (x+10,y), (x+10,y+20), (0,0,0), 2)
        block = TextBlock([60,60,321,221], lines, vertical=True, font_size=20)
        self.assertEqual(recover_paragraphs(image, [block]), [block])
