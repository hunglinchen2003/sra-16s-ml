#!/usr/bin/env python3
"""Stage Desktop/2026data FASTQ+metadata into QIIME2 WebUI and start one job per disease.

Does not download anything. Source of truth:
  /home/hlc/Desktop/2026data/{IBD,CRC,T2D}/{fastq,metadata}
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import urllib.request
from pathlib import Path

SRC = Path(os.environ.get("SRA_2026DATA", "/home/hlc/Desktop/2026data"))
QIIME = Path(os.environ.get("QIIME2_PROJECT", "/home/hlc/Desktop/QIIME2_2026"))
ANALYZE_URL = os.environ.get("QIIME_ANALYZE_URL", "http://127.0.0.1:8765/api/analyze")
RAW = QIIME / "data" / "rawdata"
META = QIIME / "data" / "metadata"
ARCHIVE = QIIME / "data" / "rawdata_archive_20260914"

DISEASE_CSV = {
    "IBD": "ibd_groups.csv",
    "CRC": "crc_groups.csv",
    "T2D": "t2d_groups.csv",
}
# IBD PacBio ~1.5kb SE; CRC Ion Torrent variable-length SE; T2D MiSeq ~229/227 PE.
TRUNC = {
    "IBD": (0, 0),
    "CRC": (0, 0),
    "T2D": (220, 220),
}


def iter_fastq(disease: str) -> list[Path]:
    fq_root = SRC / disease / "fastq"
    out: list[Path] = []
    if not fq_root.is_dir():
        return out
    for p in sorted(fq_root.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name.endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
            out.append(p)
    return out


def link_fastq(paths: list[Path]) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in paths:
        dest = RAW / src.name
        if dest.exists() or dest.is_symlink():
            try:
                if dest.resolve() == src.resolve():
                    n += 1
                    continue
            except OSError:
                pass
            dest.unlink()
        try:
            dest.symlink_to(src)
        except OSError:
            shutil.copy2(src, dest)
        n += 1
    return n


def load_rows(disease: str) -> list[dict]:
    p = SRC / disease / "metadata" / DISEASE_CSV[disease]
    if not p.exists():
        p = Path("/home/hlc/sra-16s-ml/docs/data") / DISEASE_CSV[disease]
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_metadata(disease: str, rows: list[dict], ready: set[str]) -> Path:
    META.mkdir(parents=True, exist_ok=True)
    out = META / f"metadata_sra_{disease}.tsv"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["#SampleID", "Group", "Disease", "BioProject", "Study"])
        for r in rows:
            run = (r.get("run") or "").strip()
            if run not in ready:
                continue
            w.writerow(
                [
                    run,
                    r.get("ml_label") or r.get("group") or "NA",
                    disease,
                    r.get("bioproject") or "",
                    r.get("study") or "",
                ]
            )
    return out


def accessions(paths: list[Path]) -> dict[str, list[Path]]:
    by: dict[str, list[Path]] = {}
    for p in paths:
        stem = p.name
        for ext in (".fastq.gz", ".fq.gz", ".fastq", ".fq"):
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem.endswith("_1") or stem.endswith("_2"):
            acc = stem[:-2]
        else:
            acc = stem
        by.setdefault(acc, []).append(p)
    return by


def start_analyze(disease: str, metadata_file: str) -> dict:
    trunc_f, trunc_r = TRUNC[disease]
    boundary = "----SraQiimeBoundary"
    fields = {
        "metadata_file": metadata_file,
        "metadata_column": "Group",
        "sampling_depth": "0",
        "trunc_len_f": str(trunc_f),
        "trunc_len_r": str(trunc_r),
        "force": "true",
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


def archive_old_rawdata() -> int:
    if not RAW.exists():
        RAW.mkdir(parents=True, exist_ok=True)
        return 0
    items = list(RAW.iterdir())
    if not items:
        return 0
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in items:
        dest = ARCHIVE / p.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        p.rename(dest)
        n += 1
    return n


def archive_old_default_metadata() -> None:
    META.mkdir(parents=True, exist_ok=True)
    meta_archive = QIIME / "data" / "metadata_archive_20260914"
    meta_archive.mkdir(parents=True, exist_ok=True)
    for name in ("metadata.tsv", "metadata.csv"):
        p = META / name
        if p.exists():
            dest = meta_archive / name
            if dest.exists():
                dest.unlink()
            p.rename(dest)


def ingest_disease(disease: str) -> dict:
    paths = iter_fastq(disease)
    by = accessions(paths)
    usable: dict[str, list[Path]] = {}
    for acc, plist in by.items():
        names = [p.name for p in plist]
        paired = any("_1." in n for n in names) and any("_2." in n for n in names)
        single = (not any("_1." in n or "_2." in n for n in names)) and len(plist) >= 1
        if paired or single:
            usable[acc] = plist
    nlink = link_fastq([p for plist in usable.values() for p in plist])
    rows = load_rows(disease)
    meta_path = write_metadata(disease, rows, set(usable))
    return {
        "disease": disease,
        "fastq_files": nlink,
        "samples": len(usable),
        "metadata": meta_path.name,
        "layout": "paired" if disease == "T2D" else "single",
        "trunc": list(TRUNC[disease]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--disease", choices=["IBD", "CRC", "T2D", "all"], default="all")
    ap.add_argument("--no-analyze", action="store_true")
    ap.add_argument("--keep-old-rawdata", action="store_true")
    args = ap.parse_args()
    if not args.keep_old_rawdata:
        archived = archive_old_rawdata()
        archive_old_default_metadata()
        print(json.dumps({"archived_rawdata_items": archived}, ensure_ascii=False))
    diseases = ["IBD", "CRC", "T2D"] if args.disease == "all" else [args.disease]
    out = []
    for d in diseases:
        info = ingest_disease(d)
        if not args.no_analyze:
            try:
                info["analyze"] = start_analyze(d, info["metadata"])
            except Exception as exc:
                info["analyze_error"] = str(exc)
        out.append(info)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
