"""Recover regular horizontal paragraphs when neural line polygons overlap.

Only repeated, aligned rows of similar-sized glyphs on a light background
qualify. Existing detections must support the candidate paragraph. This keeps
the usual vertical speech-bubble path intact.
"""
import cv2
import numpy as np

from comic_text_detector.utils.textblock import TextBlock


def _glyphs(gray):
    """Keep individual glyph candidates even when they cannot form a row."""
    _, ink = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    min_height = max(8, gray.shape[0] * 0.004)
    max_height = max(32, gray.shape[0] * 0.04)
    glyphs = []
    for x, y, w, h, area in stats[1:]:
        if (min_height <= h <= max_height and 0.15 * h <= w <= 1.8 * h
                and 0.08 * w * h <= area <= 0.9 * w * h):
            glyphs.append((int(x), int(y), int(w), int(h)))
    return ink, glyphs


def _rows(gray, components=None):
    ink, glyphs = _glyphs(gray) if components is None else components
    max_height = max(32, gray.shape[0] * 0.04)
    groups = []
    for glyph in sorted(glyphs, key=lambda g: g[1] + g[3] / 2):
        x, y, w, h = glyph
        cy = y + h / 2
        matched = False
        for group in reversed(groups):
            gh = np.median([g[3] for g in group])
            gy = np.median([g[1] + g[3] / 2 for g in group])
            if cy - gy > max_height:
                break
            if abs(cy - gy) < 0.35 * max(h, gh) and 0.5 <= h / gh <= 2:
                group.append(glyph)
                matched = True
                break
        if not matched:
            groups.append([glyph])
    rows = []
    for group in groups:
        height = float(np.median([g[3] for g in group]))
        runs = [[]]
        for glyph in sorted(group):
            if runs[-1] and glyph[0] - (runs[-1][-1][0] + runs[-1][-1][2]) > height * 2:
                runs.append([])
            runs[-1].append(glyph)
        for run in runs:
            # Short final rows such as 「有する。」 can contain only two
            # connected components. Keep those candidates here; a paragraph
            # still needs three full rows below, so isolated fragments cannot
            # become paragraphs by themselves.
            if len(run) < 2:
                continue
            x1 = min(g[0] for g in run)
            x2 = max(g[0] + g[2] for g in run)
            y1 = min(g[1] for g in run)
            y2 = max(g[1] + g[3] for g in run)
            if x2 - x1 < height * 1.5 or y2 - y1 > height * 1.55:
                continue
            # Paragraph gutters and spaces must be mostly white.
            patch = gray[max(0, y1-2):y2+2, max(0, x1-2):x2+2]
            if np.mean(patch > 210) < 0.4:
                continue
            # Kana and punctuation can break into smaller components. Recover
            # them at row ends from ink, stopping at a full glyph-width gap.
            margin = int(height * 2)
            left, right = max(0, x1-margin), min(gray.shape[1], x2+margin)
            border = np.flatnonzero(np.mean(ink[y1:y2, x2:right] > 0, axis=0) > 0.9)
            if border.size:
                right = x2 + int(border[0])
            columns = np.flatnonzero(np.sum(ink[y1:y2, left:right] > 0, axis=0) >= 2) + left
            if len(columns):
                pieces = np.split(columns, np.flatnonzero(np.diff(columns) > height) + 1)
                for piece in pieces:
                    if piece[0] <= x1 + height and piece[-1] >= x2 - height:
                        x1, x2 = int(piece[0]), int(piece[-1]+1)
                        break
            rows.append([x1, y1, x2, y2, height, len(run)])
    return sorted(rows, key=lambda r: (r[1], r[0]))


def _intersection(a, b):
    return max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))


def _interval_coverage(intervals):
    """Return the length covered by overlapping one-dimensional intervals."""
    if not intervals:
        return 0
    covered = 0
    left, right = sorted(intervals)[0]
    for next_left, next_right in sorted(intervals)[1:]:
        if next_left > right:
            covered += right - left
            left, right = next_left, next_right
        else:
            right = max(right, next_right)
    return covered + right - left


def _line_is_replaced(line, paragraphs, glyphs):
    """Only remove a detector polygon after recovered rows cover its text.

    A bad detector polygon may cover an entire paragraph. Its area is mostly
    white space, so area overlap alone is insufficient. Recovered rows must
    span its vertical extent before it can be removed.
    """
    poly = np.asarray(line)
    box = [poly[:, 0].min(), poly[:, 1].min(), poly[:, 0].max(), poly[:, 1].max()]
    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    replacement_rows = [
        [np.min(np.asarray(row)[:, 0]), np.min(np.asarray(row)[:, 1]),
         np.max(np.asarray(row)[:, 0]), np.max(np.asarray(row)[:, 1])]
        for paragraph in paragraphs for row in paragraph.lines
    ]

    for paragraph in paragraphs:
        rows = []
        for row in paragraph.lines:
            row_poly = np.asarray(row)
            row_box = [row_poly[:, 0].min(), row_poly[:, 1].min(),
                       row_poly[:, 0].max(), row_poly[:, 1].max()]
            if _intersection(box, row_box):
                rows.append(row_box)
        if not rows:
            continue

        covered_area = sum(_intersection(box, row) for row in rows)
        area_coverage = covered_area / (width * height)
        vertical_coverage = _interval_coverage([
            (max(box[1], row[1]), min(box[3], row[3])) for row in rows
        ]) / height
        horizontal_coverage = max(
            max(0, min(box[2], row[2]) - max(box[0], row[0])) / width for row in rows
        )

        # Normal detector rows are replaced only when their ink region is
        # substantially covered. A large detector polygon needs coverage over
        # its full height; otherwise it may contain an omitted short ending.
        normal = height < paragraph.font_size * 2.5 and area_coverage >= 0.65
        large = (vertical_coverage >= 0.85 and horizontal_coverage >= 0.55
                 and height >= paragraph.font_size * 2.5)
        # Crossed detector polygons sometimes span an illustration and several
        # recovered lines. They are neither horizontal nor vertical text rows.
        slanted = (abs(poly[1, 1] - poly[0, 1]) > paragraph.font_size * 2
                   and abs(poly[3, 0] - poly[0, 0]) > paragraph.font_size * 2)
        crossed = (slanted and height >= paragraph.font_size * 8
                   and width >= paragraph.font_size * 8
                   and vertical_coverage >= 0.5 and horizontal_coverage >= 0.55)
        if not (normal or large or crossed):
            continue

        # Coverage percentages can hide an omitted one-glyph ending or a gap
        # inside a long paragraph. Check the components BEFORE row filtering.
        # A slanted bad polygon also includes artwork outside the text column;
        # constrain that special case to the recovered column, not its huge
        # axis-aligned bounding box.
        uncovered = False
        for x, y, w, h in glyphs:
            if not 0.65 * paragraph.font_size <= h <= 1.5 * paragraph.font_size:
                continue
            cx, cy = x + w / 2, y + h / 2
            if slanted and not paragraph.xyxy[0] <= cx <= paragraph.xyxy[2]:
                continue
            if cv2.pointPolygonTest(poly.astype(np.float32), (cx, cy), False) < 0:
                continue
            glyph_box = [x, y, x + w, y + h]
            covered = sum(_intersection(glyph_box, row) for row in replacement_rows)
            if covered < w * h * 0.9:
                uncovered = True
                break
        if not uncovered:
            return True
    return False


def _is_complete_row(row):
    return row[5] >= 6 and row[2] - row[0] >= row[4] * 5


def recover_paragraphs(img, blocks):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    components = _glyphs(gray)
    rows = _rows(gray, components)
    groups = []
    for row in rows:
        for group in reversed(groups):
            prev = group[-1]
            dy = row[1] - prev[1]
            regular_pitch = 0.9 * prev[4] <= dy <= 2.25 * prev[4]
            regular_height = 0.75 <= row[4]/prev[4] <= 1.35
            overlap = min(row[2], prev[2]) - max(row[0], prev[0])
            regular_alignment = (abs(row[0]-prev[0]) <= prev[4] * 0.7
                                 and overlap >= min(row[2]-row[0], prev[2]-prev[0]) * 0.75)
            # A paragraph can end with a short row. Decorative diamonds often
            # sit just left of that row, so use overlap and the established
            # paragraph cadence rather than requiring the same left edge.
            complete_rows = sum(_is_complete_row(candidate) for candidate in group)
            short_continuation = ((row[2]-row[0]) <= (prev[2]-prev[0]) * 0.8
                                  and overlap >= (row[2]-row[0]) * 0.5
                                  and complete_rows >= 3)
            if regular_pitch and regular_height and (regular_alignment or short_continuation):
                group.append(row)
                break
        else:
            groups.append([row])
    paragraphs = []
    for group in groups:
        # A short continuation is eligible only beside at least three regular
        # paragraph rows. This avoids inventing OCR regions from small marks.
        complete_rows = [row for row in group if _is_complete_row(row)]
        if len(complete_rows) < 3:
            continue
        heights = np.array([r[4] for r in group])
        pitch = np.diff([r[1] for r in group])
        if np.std(pitch) > np.median(heights) * 0.25:
            continue
        # Require every row to be supported by the text detector, including
        # horizontal geometry inside a misclassified block.
        support = []
        for block in blocks:
            horizontal = not block.vertical
            # Bad paragraph polygons sometimes get classified as vertical and
            # inflate the font size to two or three times the actual glyphs.
            # Regular paragraph spacing distinguishes this from a text grid.
            if (block.font_size > np.median(heights) * 1.6
                    and np.median(pitch) > np.median(heights) * 1.35):
                horizontal = True
            if not horizontal:
                for line in block.lines:
                    poly = np.asarray(line)
                    w, h = np.ptp(poly[:,0]), np.ptp(poly[:,1])
                    if w > h * 2.5:
                        horizontal = True
                        break
            if horizontal:
                support.append(block)
        if not all(any(_intersection(row, b.xyxy) > (row[2]-row[0])*(row[3]-row[1])*0.45
                       for b in support) for row in group):
            continue
        polygons = []
        anchor = float(np.median([row[0] for row in complete_rows]))
        row_width = float(np.median([row[2] - row[0] for row in complete_rows]))
        for index, (x1, y1, x2, y2, h, _) in enumerate(group):
            # Include furigana above the row without swallowing the previous
            # main text. Punctuation at the right edge is smaller than glyphs.
            if x2 - x1 < row_width * 0.8 and x1 < anchor - h * 0.5:
                x1 = int(anchor)
            top = max(0, int(y1-h*0.65))
            if index:
                top = max(top, polygons[-1][2][1]+1)
            right = min(gray.shape[1], int(x2+h*0.65))
            # A component box often ends above the baseline and any furigana
            # below a *final* row. Only its lower gutter is unambiguous;
            # widening an earlier row shifts and corrupts every later crop.
            if index + 1 == len(group):
                bottom = min(gray.shape[0], int(y2 + h * 0.65))
            else:
                bottom = min(gray.shape[0], y2 + 2)
            # Trim the right padding at a vertical panel border.
            band = gray[y1:y2, x2:right]
            if band.size:
                border = np.flatnonzero(np.mean(band < 100, axis=0) > 0.9)
                if border.size:
                    right = x2 + int(border[0])
            polygons.append([[x1-1,top],[right,top],[right,bottom],[x1-1,bottom]])
        bbox = [min(p[0][0] for p in polygons), min(p[0][1] for p in polygons),
                max(p[2][0] for p in polygons), max(p[2][1] for p in polygons)]
        paragraph = TextBlock(bbox, polygons, language="ja", vertical=False,
                              font_size=float(np.median(heights)))
        paragraph.mokuro_paragraph = True
        paragraphs.append(paragraph)
    if not paragraphs:
        return blocks
    retained = []
    for block in blocks:
        # Drop erroneous giant polygons as well as duplicate row fragments.
        # Retain real neighboring headings and speech bubbles as separate boxes.
        remaining = []
        for line in block.lines:
            if _line_is_replaced(line, paragraphs, components[1]):
                continue
            remaining.append(line)
        if remaining:
            if len(remaining) != len(block.lines):
                import copy
                block = copy.copy(block)
                block.lines = remaining
                block.adjust_bbox(with_bbox=False)
                sizes = []
                for line in remaining:
                    poly = np.asarray(line)
                    sizes.append(min(np.linalg.norm(poly[1]-poly[0]),np.linalg.norm(poly[3]-poly[0])))
                block.font_size = float(np.median(sizes))
            retained.append(block)
    return retained + paragraphs
