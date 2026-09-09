#!/usr/bin/env python3
"""Stage SRA FASTQs + group labels into the QIIME2 WebUI at :8765 and start analysis."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

SRA_ROOT = Path(os.environ.get("SRA16S_ROOT", "/home/hlc/SRA_16S_ML"))
QIIME_ROOT = Path(os.environ.get("QIIME2_PROJECT", "/home/hlc/Desktop/QIIME2_2026"))
ANALYZE_URL = os.environ.get("QIIME_ANALYZE_URL", "http://127.0.0.1:8765/api/analyze")
MIN_BYTES = int(os.environ.get("SRA_MIN_BYTES", "80000"))
MIN_SAMPLES = int(os.environ.get("SRA_ANALYZE_MIN", "4"))

RAW = QIIME_ROOT / "data" / "rawdata"
META = QIIME_ROOT / "data" / "metadata"
STAMP_DIR = SRA_ROOT / ".qiime_ingest"

DISEASE_CSV = {
    "IBD": "ibd_groups.csv",
    "CRC": "crc_groups.csv",
    "T2D": "t2d_groups.csv",
}
TRUNC = {
    "IBD": (0, 0),       # PacBio single-end: no truncation
    "CRC": (250, 200),
    "T2D": (250, 200),
}


def complete_files(fq_dir: Path) -> dict[str, list[Path]]:
    """Map run accession -> list of ready FASTQ paths."""
    by_run: dict[str, list[Path]] = {}
    if not fq_dir.is_dir():
        return by_run
    now = time.time()
    for p in sorted(fq_dir.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        if not any(name.endswith(ext) for ext in (".fastq", ".fastq.gz", ".fq", ".fq.gz")):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size < MIN_BYTES:
            continue
        if now - st.st_mtime < 20:
            continue
        run = name.split(".")[0]
        run = run.replace("_1", "").replace("_2", "") if run.endswith(("_1", "_2")) else run
        # keep original _1/_2 grouping via stem
        stem = name
        for ext in (".fastq.gz", ".fq.gz", ".fastq", ".fq"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem.endswith("_1") or stem.endswith("_2"):
            acc = stem[:-2]
        else:
            acc = stem
        by_run.setdefault(acc, []).append(p)
    return by_run


def link_into_rawdata(paths: list[Path]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for src in paths:
        dest = RAW / src.name
        if dest.exists() or dest.is_symlink():
            try:
                if dest.resolve() == src.resolve() and dest.stat().st_size == src.stat().st_size:
                    continue
            except OSError:
                pass
            dest.unlink()
        try:
            dest.symlink_to(src)
        except OSError:
            import shutil

            shutil.copy2(src, dest)


def write_metadata(disease: str, rows: list[dict], ready: set[str]) -> Path:
    META.mkdir(parents=True, exist_ok=True)
    out = META / f"metadata_sra_{disease}.tsv"
    used = [r for r in rows if r.get("run") in ready]
    with out.open("w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["#SampleID", "Group", "Disease", "BioProject", "Study"])
        for r in used:
            w.writerow(
                [
                    r["run"],
                    r.get("ml_label") or r.get("group") or "NA",
                    disease,
                    r.get("bioproject") or "",
                    r.get("study") or "",
                ]
            )
    return out


def load_group_rows(disease: str) -> list[dict]:
    csv_name = DISEASE_CSV[disease]
    candidates = [
        SRA_ROOT / disease / "metadata" / csv_name,
        Path("/home/hlc/sra-16s-ml/docs/data") / csv_name,
    ]
    for p in candidates:
        if p.exists():
            with p.open(encoding="utf-8") as f:
                return list(csv.DictReader(f))
    return []


def already_ran(disease: str, n: int) -> bool:
    stamp = STAMP_DIR / f"{disease}.json"
    if not stamp.exists():
        return False
    try:
        prev = json.loads(stamp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return int(prev.get("n") or 0) == n and prev.get("status") in ("started", "queued")


def mark(disease: str, n: int, payload: dict) -> None:
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    (STAMP_DIR / f"{disease}.json").write_text(
        json.dumps({"n": n, **payload, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2),
        encoding="utf-8",
    )


def start_analyze(disease: str, metadata_file: str) -> dict:
    trunc_f, trunc_r = TRUNC[disease]
    boundary = "----SraQiimeBoundary"
    fields = {
        "metadata_file": metadata_file,
        "metadata_column": "Group",
        "sampling_depth": "0",
        "trunc_len_f": str(trunc_f),
        "trunc_len_r": str(trunc_r),
        "force": "false",
    }
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        ANALYZE_URL,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def ingest_disease(disease: str, trigger: bool) -> dict:
    fq_dir = SRA_ROOT / disease / "fastq"
    ready_map = complete_files(fq_dir)
    rows = load_group_rows(disease)
    # paired: need 2 files; single: 1
    usable = {}
    for acc, paths in ready_map.items():
        names = [p.name for p in paths]
        paired = any("_1." in n for n in names) and any("_2." in n for n in names)
        single = (not any("_1." in n or "_2." in n for n in names)) and len(paths) >= 1
        if paired or single:
            usable[acc] = paths
    for paths in usable.values():
        link_into_rawdata(paths)
    meta_path = write_metadata(disease, rows, set(usable))
    info = {
        "disease": disease,
        "ready": len(usable),
        "metadata": meta_path.name,
        "samples": sorted(usable),
    }
    if trigger and len(usable) >= MIN_SAMPLES and not already_ran(disease, len(usable)):
        try:
            resp = start_analyze(disease, meta_path.name)
            info["analyze"] = resp
            mark(disease, len(usable), {"status": "started", **resp})
        except urllib.error.URLError as exc:
            info["analyze_error"] = str(exc)
            mark(disease, len(usable), {"status": "error", "error": str(exc)})
    elif trigger and already_ran(disease, len(usable)):
        info["analyze"] = "skip_same_count"
    else:
        info["analyze"] = f"wait (need>={MIN_SAMPLES})"
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--disease", choices=["IBD", "CRC", "T2D", "all"], default="all")
    ap.add_argument("--no-analyze", action="store_true")
    args = ap.parse_args()
    diseases = ["IBD", "CRC", "T2D"] if args.disease == "all" else [args.disease]
    out = [ingest_disease(d, trigger=not args.no_analyze) for d in diseases]
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
