"""Generates the synthetic-document corpus for the Docling extraction-accuracy demo (see
README's Document Intake section). Renders a deterministic sample of properties already in
the seeded database as synthetic valuation-report PDFs (see app.synthetic_reports), degrades a
documented split of them to simulate the paper reality of a decades-old mortgage book (see
app.degrade), and records each as a `SyntheticDocument` row with its ground truth.

Requires the database to already be seeded (python scripts/seed_db.py) — unlike
generate_ingestion_sources.py, this reads Property rows from the database, not the raw CSV.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.degrade import degrade_pdf  # noqa: E402
from app.models import Property, SyntheticDocument, SyntheticReportStyle  # noqa: E402
from app.synthetic_reports import render_synthetic_report_pdf  # noqa: E402

OUT_DIR = ROOT / "data" / "synthetic_reports"
SEED = 20260711
DEFAULT_SAMPLE_SIZE = 200
DEGRADED_FRACTION = 0.30


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE,
                        help=f"how many properties to generate documents for (default {DEFAULT_SAMPLE_SIZE})")
    parser.add_argument("--degraded-fraction", type=float, default=DEGRADED_FRACTION,
                        help=f"fraction of the sample rendered as degraded scans (default {DEGRADED_FRACTION})")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()

    import random
    rng = random.Random(SEED)
    pids = [p.pid for p in db.query(Property.pid).all()]
    if not pids:
        raise SystemExit("No properties on file — run `python scripts/seed_db.py` first.")
    rng.shuffle(pids)
    sample = sorted(pids[:min(args.sample_size, len(pids))])

    n_degraded = round(len(sample) * args.degraded_fraction)
    degraded_pids = set(rng.sample(sample, n_degraded))

    created = 0
    for i, pid in enumerate(sample):
        style = SyntheticReportStyle.LEGACY_URAR if i % 2 == 0 else SyntheticReportStyle.MODERN
        result = render_synthetic_report_pdf(db, pid, style)
        if result is None:
            continue
        pdf_bytes, ground_truth = result
        degraded = pid in degraded_pids
        degradation_method = None
        if degraded:
            pdf_bytes = degrade_pdf(pdf_bytes, seed=str(pid))
            degradation_method = "img2pdf_photocopy_v1"

        suffix = "degraded" if degraded else "clean"
        filename = f"{pid}_{style.value}_{suffix}.pdf"
        path = OUT_DIR / filename
        path.write_bytes(pdf_bytes)

        db.add(SyntheticDocument(
            pid=pid, style=style, degraded=degraded, degradation_method=degradation_method,
            file_path=str(path.relative_to(ROOT)), ground_truth=ground_truth,
        ))
        created += 1

    db.commit()
    db.close()
    print(f"Generated {created} synthetic documents in {OUT_DIR} "
          f"({n_degraded} degraded, {created - n_degraded} clean).")


if __name__ == "__main__":
    main()
