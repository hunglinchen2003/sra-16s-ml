#!/usr/bin/env python3
"""Download 16S runs + keep grouping tables on 10.0.1.100."""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SRA16S_ROOT", "/home/hlc/SRA_16S_ML"))
PREFETCH = os.environ.get(
    "PREFETCH", "/home/hlc/anaconda3/envs/sratools/bin/prefetch"
)
FASTERQ = os.environ.get(
    "FASTERQ", "/home/hlc/anaconda3/envs/sratools/bin/fasterq-dump"
)
MAX_SIZE = os.environ.get("SRA_MAX_SIZE", "2G")

DISEASES = {
    "IBD": "ibd_groups.csv",
    "CRC": "crc_groups.csv",
    "T2D": "t2d_groups.csv",
}


def log(path: Path, msg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")
    print(msg, flush=True)


def load_runs(csv_path: Path, limit: int | None) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit:
        # keep label balance: take up to limit//n_groups per group, then fill
        by = {}
        for r in rows:
            by.setdefault(r.get("ml_label") or "NA", []).append(r)
        picked = []
        per = max(1, limit // max(1, len(by)))
        for grp, items in by.items():
            picked.extend(items[:per])
        if len(picked) < limit:
            rest = [r for r in rows if r not in picked]
            picked.extend(rest[: limit - len(picked)])
        return picked[:limit]
    return rows


def run_cmd(cmd: list[str], log_path: Path) -> int:
    log(log_path, "$ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.stdout:
        log(log_path, p.stdout[-2000:])
    if p.stderr:
        log(log_path, p.stderr[-2000:])
    log(log_path, f"exit={p.returncode}")
    return p.returncode


def download_one(run: str, dest: Path, log_path: Path) -> None:
    sra_dir = dest / "sra"
    fq_dir = dest / "fastq"
    sra_dir.mkdir(parents=True, exist_ok=True)
    fq_dir.mkdir(parents=True, exist_ok=True)
    if list(fq_dir.glob(f"{run}*")):
        log(log_path, f"skip existing fastq {run}")
        return
    rc = run_cmd(
        [PREFETCH, run, "--max-size", MAX_SIZE, "-O", str(sra_dir)],
        log_path,
    )
    if rc != 0:
        log(log_path, f"prefetch failed {run}")
        return
    run_cmd(
        [FASTERQ, run, "-O", str(fq_dir), "-e", "4", "--split-files", "-t", str(dest / "tmp")],
        log_path,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-data", default=str(Path(__file__).resolve().parents[1] / "docs" / "data"))
    ap.add_argument("--disease", choices=["IBD", "CRC", "T2D", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="0 = all runs")
    args = ap.parse_args()
    web_data = Path(args.web_data)
    diseases = DISEASES if args.disease == "all" else {args.disease: DISEASES[args.disease]}
    ROOT.mkdir(parents=True, exist_ok=True)
    for disease, fname in diseases.items():
        dest = ROOT / disease
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "metadata").mkdir(exist_ok=True)
        src = web_data / fname
        if src.exists():
            (dest / "metadata" / fname).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        unified = web_data / "ml_labels.csv"
        if unified.exists():
            (dest / "metadata" / "ml_labels.csv").write_text(
                unified.read_text(encoding="utf-8"), encoding="utf-8"
            )
        log_path = dest / "download.log"
        rows = load_runs(src, args.limit or None)
        log(log_path, f"=== {disease} n={len(rows)} ===")
        for i, row in enumerate(rows, 1):
            run = row["run"]
            log(log_path, f"[{i}/{len(rows)}] {run} label={row.get('ml_label')}")
            try:
                download_one(run, dest, log_path)
            except Exception as exc:
                log(log_path, f"error {run}: {exc}")
    print("done")


if __name__ == "__main__":
    sys.exit(main())
