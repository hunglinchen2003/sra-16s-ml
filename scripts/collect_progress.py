#!/usr/bin/env python3
"""Collect SRA download + QIIME job progress as JSON (run on 10.0.1.118)."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

SRA = Path(os.environ.get("SRA16S_ROOT", "/home/hlc/SRA_16S_ML"))
DATA2026 = Path(os.environ.get("SRA_2026DATA", "/home/hlc/Desktop/2026data"))
QIIME = Path(os.environ.get("QIIME2_PROJECT", "/home/hlc/Desktop/QIIME2_2026"))
WEB = Path(os.environ.get("SRA16S_WEB", "/home/hlc/sra-16s-ml/docs"))
TARGETS = {"IBD": 77, "CRC": 113, "T2D": 100}


def sh(cmd: str) -> str:
    p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
    return (p.stdout or "").strip()


def dir_stats(path: Path) -> dict:
    if not path.is_dir():
        return {"files": 0, "bytes": 0}
    files = [p for p in path.iterdir() if p.is_file()]
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def fq_stats(disease: str) -> dict:
    roots = [DATA2026 / disease / "fastq", SRA / disease / "fastq"]
    for path in roots:
        if not path.is_dir():
            continue
        files = [
            p
            for p in path.rglob("*")
            if p.is_file()
            and any(p.name.endswith(ext) for ext in (".fastq.gz", ".fq.gz", ".fastq", ".fq"))
        ]
        by_name = {p.name: p for p in files}
        uniq = list(by_name.values())
        return {"files": len(uniq), "bytes": sum(p.stat().st_size for p in uniq), "source": str(path)}
    return {"files": 0, "bytes": 0, "source": ""}


def meta_rows(disease: str) -> int:
    p = QIIME / "data" / "metadata" / f"metadata_sra_{disease}.tsv"
    if not p.exists():
        return 0
    lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    return max(0, len(lines) - 1)


def qiime_runs() -> list[dict]:
    root = QIIME / "results"
    if not root.is_dir():
        return []
    runs = []
    for d in sorted(root.glob("run_*"), key=lambda x: x.stat().st_mtime, reverse=True)[:8]:
        cp = d / "checkpoints.json"
        item = {"name": d.name, "status": "unknown", "steps": {}}
        if cp.exists():
            try:
                j = json.loads(cp.read_text(encoding="utf-8"))
                item["status"] = j.get("status") or "running"
                item["steps"] = {
                    k: {"status": v.get("status"), "message": str(v.get("message") or "")[:160]}
                    for k, v in (j.get("steps") or {}).items()
                }
            except json.JSONDecodeError:
                pass
        runs.append(item)
    return runs


def procs() -> list[str]:
    out = sh("pgrep -af 'download_sra|wget|prefetch|fasterq-dump|ingest_sra' || true")
    lines = []
    for ln in out.splitlines():
        if "pgrep" in ln:
            continue
        lines.append(ln[:200])
    return lines[:12]


def log_tail() -> str:
    p = SRA / "download_subset.log"
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[-1500:]


def main() -> None:
    diseases = {}
    for name, target in TARGETS.items():
        fq = fq_stats(name)
        sra = dir_stats(SRA / name / "sra") if (SRA / name / "sra").is_dir() else {"files": 0, "bytes": 0}
        diseases[name] = {
            "target": target,
            "fastq_files": fq["files"],
            "fastq_bytes": fq["bytes"],
            "sra_files": sra["files"],
            "metadata_rows": meta_rows(name),
            "ready_for_analyze": meta_rows(name) >= 4,
            "fastq_source": fq.get("source") or "",
        }
    snapshot = {
        "updated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "host": "10.0.1.118",
        "note": "下載已完成（桌面 2026data）。QIIME 分析進度：http://10.0.1.118:8765/ ；區網搜尋 http://10.0.1.118:8770/",
        "analyze_url": "http://10.0.1.118:8765/",
        "diseases": diseases,
        "processes": procs(),
        "qiime_runs": qiime_runs(),
        "download_log_tail": log_tail(),
    }
    out = WEB / "data" / "progress.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
