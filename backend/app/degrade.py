"""Degrades a clean synthetic valuation-report PDF (see app.synthetic_reports) into something
that reads like a scanned page from a decades-old paper mortgage file — skewed, noisy,
low-contrast — so the Docling extraction demo has a "hard" bucket to compare against the
"clean" bucket, not just a trivial one. Nothing here touches the document's actual content;
it only affects how legible that content is to an OCR/layout pipeline.

Pipeline: rasterize each page with pypdfium2 (pure-Python wheel, no system dependency, unlike
pdf2image's poppler-utils) -> apply a "photocopy" filter with Pillow (skew, noise, contrast
shift, low-quality JPEG re-encode) -> repackage the degraded images back into a PDF with
img2pdf.
"""
import io
import random

import img2pdf
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter

RENDER_SCALE = 2.0  # pdfium render scale; higher = sharper source raster before degrading


def _photocopy_filter(img: Image.Image, rng: random.Random) -> Image.Image:
    img = img.convert("L")  # grayscale, like a black-and-white photocopier/scanner

    angle = rng.uniform(-4.0, 4.0)
    img = img.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)

    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.8, 1.6)))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.55, 0.75))  # faded toner/old scan

    # Salt-and-pepper style noise via a random per-pixel offset, cheap and dependency-free.
    noise = Image.effect_noise(img.size, rng.uniform(24, 40))
    img = Image.blend(img, noise, alpha=rng.uniform(0.14, 0.24))

    # Two JPEG re-encode passes at low quality — a real scanner/fax/photocopy round-trip
    # compounds compression artifacts rather than applying just one.
    for _ in range(2):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=rng.randint(20, 35))
        buf.seek(0)
        img = Image.open(buf).convert("L")
    return img.convert("RGB")


def degrade_pdf(pdf_bytes: bytes, seed: str, method: str = "img2pdf_photocopy_v1") -> bytes:
    """Returns degraded PDF bytes. `seed` should be stable per document (e.g. the pid) so a
    given document always degrades the same way."""
    rng = random.Random(seed)
    jpeg_pages = []
    with pdfium.PdfDocument(pdf_bytes) as doc:  # holds native resources — must be closed
        for page in doc:
            bitmap = page.render(scale=RENDER_SCALE)
            img = bitmap.to_pil()
            degraded = _photocopy_filter(img, rng)
            buf = io.BytesIO()
            degraded.save(buf, format="JPEG", quality=70)
            jpeg_pages.append(buf.getvalue())
    return img2pdf.convert(jpeg_pages)
