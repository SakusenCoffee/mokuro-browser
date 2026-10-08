// Shared by the worker and content script: completed geometry, not a promise
// that OCR recognized every word on the source image.
globalThis.MokuroResults = {
  verticalParts(text) {
    // Tate-chu-yoko: a two-digit number occupies one vertical character cell.
    // Preserve original characters for copying and dictionary lookup.
    return text.match(/(?<![0-9０-９])[0-9０-９]{2}(?![0-9０-９])|[\s\S]/gu) || [];
  },
  valid(result) {
    const point = value => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite);
    return !!result && Number.isFinite(result.img_width) && result.img_width > 0
      && Number.isFinite(result.img_height) && result.img_height > 0
      && Array.isArray(result.blocks) && result.blocks.every(block =>
        Array.isArray(block.box) && block.box.length === 4 && block.box.every(Number.isFinite)
        && block.box[2] > block.box[0] && block.box[3] > block.box[1]
        && Number.isFinite(block.font_size) && block.font_size > 0 && typeof block.vertical === "boolean"
        && Array.isArray(block.lines) && block.lines.every(line => typeof line === "string")
        && Array.isArray(block.lines_coords) && block.lines_coords.length === block.lines.length
        && block.lines_coords.every(polygon => Array.isArray(polygon) && polygon.length === 4 && polygon.every(point)));
  },
  key(target) {
    return target.kind === "image" ? JSON.stringify([target.src, target.width, target.height]) : null;
  },
  lines(result) { return result.blocks.flatMap(block => block.lines.filter(Boolean)); }
};
