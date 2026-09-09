#!/usr/bin/env python3
"""SRA 16S Lab API — search NCBI and report download status on 10.0.1.100."""
from __future__ import annotations

import csv
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

ROOT = Path(os.environ.get("SRA16S_ROOT", "/home/hlc/SRA_16S_ML")).resolve()
WEB = Path(os.environ.get("SRA16S_WEB", str(Path(__file__).resolve().parents[1] / "docs")))
DATA = WEB / "data"

app = FastAPI(title="SRA 16S Lab", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def http_get(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sra-16s-ml/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_expxml(expxml: str) -> dict:
    def pick(pat: str) -> str:
        m = re.search(pat, expxml or "")
        return m.group(1) if m else ""

    return {
        "study": pick(r'<Study acc="([^"]+)"'),
        "studyName": pick(r'<Study acc="[^"]+" name="([^"]*)"'),
        "title": pick(r"<Title>([^<]+)<"),
        "lib": pick(r"<LIBRARY_STRATEGY>([^<]+)<"),
        "org": pick(r'ScientificName="([^"]+)"'),
    }


@app.get("/api/search")
def api_search(q: str = Query(...), retmax: int = 25) -> dict:
    es_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=sra&retmode=json&retmax={int(retmax)}&term={urllib.parse.quote(q)}"
    )
    es = json.loads(http_get(es_url))
    ids = es.get("esearchresult", {}).get("idlist") or []
    count = int(es.get("esearchresult", {}).get("count") or 0)
    hits = []
    if ids:
        sm = json.loads(
            http_get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                f"?db=sra&retmode=json&id={','.join(ids)}"
            )
        )
        for uid in ids:
            p = parse_expxml((sm.get("result") or {}).get(uid, {}).get("expxml", ""))
            hits.append({"uid": uid, **p})
    return {"count": count, "hits": hits, "query": q}


@app.get("/api/status")
def api_status() -> dict:
    diseases = {}
    for name in ("IBD", "CRC", "T2D"):
        d = ROOT / name
        sra = list((d / "sra").glob("*")) if (d / "sra").exists() else []
        fq = list((d / "fastq").glob("*")) if (d / "fastq").exists() else []
        meta = list((d / "metadata").glob("*")) if (d / "metadata").exists() else []
        log = d / "download.log"
        diseases[name] = {
            "sra_items": len(sra),
            "fastq_items": len(fq),
            "metadata_files": [p.name for p in meta],
            "log_tail": log.read_text(encoding="utf-8", errors="replace")[-1200:]
            if log.exists()
            else "",
        }
    return {
        "host": "10.0.1.100",
        "root": str(ROOT),
        "diseases": diseases,
        "web": str(WEB),
    }


@app.get("/api/labels")
def api_labels() -> dict:
    path = DATA / "ml_labels.csv"
    if not path.exists():
        return {"rows": []}
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {"n": len(rows), "rows": rows}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/data", StaticFiles(directory=str(DATA)), name="data")
app.mount("/assets", StaticFiles(directory=str(WEB / "assets")), name="assets")
