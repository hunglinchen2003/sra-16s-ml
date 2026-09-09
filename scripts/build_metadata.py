#!/usr/bin/env python3
"""Build sample-grouping tables for three 16S disease studies."""
from __future__ import annotations

import csv
import io
import json
import re
import ssl
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

CTX = ssl.create_default_context()
UA = {"User-Agent": "sra-16s-ml/1.0 (teaching; hunglinchen2003)"}

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def runinfo(acc: str) -> list[dict]:
    text = get(f"https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo?acc={acc}").decode(
        "utf-8", "replace"
    )
    return list(csv.DictReader(io.StringIO(text)))


def ena_runs(acc: str) -> list[dict]:
    url = (
        "https://www.ebi.ac.uk/ena/portal/api/filereport"
        f"?accession={acc}&result=read_run&format=tsv"
        "&fields=run_accession,sample_accession,sample_title,library_strategy,"
        "library_layout,scientific_name,fastq_bytes,base_count"
    )
    text = get(url).decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def biosample_xml_attrs(accessions: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for i in range(0, len(accessions), 10):
        batch = accessions[i : i + 10]
        url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=biosample&retmode=xml&id={','.join(batch)}"
        )
        xml = get(url).decode("utf-8", "replace")
        time.sleep(0.35)
        root = ET.fromstring(xml)
        for bs in root.findall("BioSample"):
            acc = bs.get("accession") or ""
            attrs = {}
            for attr in bs.findall("./Attributes/Attribute"):
                name = attr.get("display_name") or attr.get("attribute_name") or ""
                attrs[name] = (attr.text or "").strip()
            title = bs.findtext("./Description/Title") or ""
            attrs["_title"] = title
            out[acc] = attrs
    return out


def ebi_chars(acc: str) -> dict:
    j = json.loads(get(f"https://www.ebi.ac.uk/biosamples/samples/{acc}.json"))
    chars = {}
    for k, vals in (j.get("characteristics") or {}).items():
        if vals and isinstance(vals, list):
            chars[k] = vals[0].get("text", "")
    return chars


def ibd_group(subject_id: str) -> str:
    sid = (subject_id or "").upper()
    if sid.startswith("HC"):
        return "Healthy"
    if sid.startswith("SMH"):
        return "IBD"
    return "Unknown"


def crc_group(sample_name: str, origin: str) -> str:
    origin_l = (origin or "").lower()
    name = sample_name or ""
    if "non tumoral" in origin_l or "non-tumoral" in origin_l:
        return "NonTumor"
    if origin_l == "tumoral" or origin_l.startswith("tumor"):
        return "Tumor"
    if re.search(r"-T(-|$)", name) or name.endswith("-T") or "-T-R" in name:
        return "Tumor"
    if re.search(r"-N(-|$)", name) or "-N-R" in name or name.endswith("-N"):
        return "NonTumor"
    if "-H" in name or name.endswith("-H"):
        return "StoolHealthyLike"
    return origin or "Unknown"


def t2d_group(phenotype: str, disease: str) -> str:
    p = (phenotype or "").lower()
    d = (disease or "").lower()
    if "hearing impairment" in p or "hearing loss" in d:
        return "T2D_hearing_loss"
    if "normal hearing" in p:
        return "T2D_normal_hearing"
    return "T2D"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def build_ibd() -> list[dict]:
    print("IBD metadata...")
    runs = runinfo("ERP170281")
    ena = {r["run_accession"]: r for r in ena_runs("PRJEB86986")}
    rows = []
    for i, r in enumerate(runs):
        bs = r.get("BioSample") or ""
        chars = ebi_chars(bs) if bs else {}
        time.sleep(0.08)
        subject = chars.get("host subject id", "")
        group = ibd_group(subject)
        rows.append(
            {
                "disease": "IBD",
                "bioproject": r.get("BioProject") or "PRJEB86986",
                "study": r.get("SRAStudy") or "ERP170281",
                "run": r.get("Run"),
                "biosample": bs,
                "sample_name": ena.get(r.get("Run"), {}).get("sample_title") or r.get("SampleName"),
                "host_subject_id": subject,
                "group": group,
                "ml_label": group,
                "sex": "",
                "age": "",
                "tissue": chars.get("host body product") or "stool",
                "library_strategy": r.get("LibraryStrategy"),
                "library_layout": r.get("LibraryLayout"),
                "spots": r.get("spots"),
                "size_MB": r.get("size_MB"),
                "instrument": r.get("Model"),
            }
        )
        if (i + 1) % 20 == 0:
            print(f"  IBD {i+1}/{len(runs)}")
    return rows


def build_crc() -> list[dict]:
    print("CRC metadata...")
    runs = runinfo("SRP446495")
    accs = [r.get("BioSample") for r in runs if r.get("BioSample")]
    attrs = biosample_xml_attrs(accs)
    rows = []
    for r in runs:
        a = attrs.get(r.get("BioSample") or "", {})
        origin = a.get("Sample origin") or ""
        name = r.get("SampleName") or ""
        group = crc_group(name, origin)
        rows.append(
            {
                "disease": "CRC",
                "bioproject": r.get("BioProject") or "PRJNA989099",
                "study": r.get("SRAStudy") or "SRP446495",
                "run": r.get("Run"),
                "biosample": r.get("BioSample"),
                "sample_name": name,
                "host_subject_id": a.get("isolate") or "",
                "group": group,
                "ml_label": group,
                "sex": a.get("sex") or r.get("Sex") or "",
                "age": a.get("age") or "",
                "tissue": a.get("tissue") or "",
                "sample_origin": origin,
                "bmi_class": a.get("Weight") or "",
                "stage": a.get("Stage") or "",
                "library_strategy": r.get("LibraryStrategy"),
                "library_layout": r.get("LibraryLayout"),
                "spots": r.get("spots"),
                "size_MB": r.get("size_MB"),
                "instrument": r.get("Model"),
            }
        )
    return rows


def build_t2d() -> list[dict]:
    print("T2D metadata...")
    runs = runinfo("SRP688705")
    accs = [r.get("BioSample") for r in runs if r.get("BioSample")]
    attrs = biosample_xml_attrs(accs)
    rows = []
    for r in runs:
        a = attrs.get(r.get("BioSample") or "", {})
        group = t2d_group(a.get("phenotype") or "", a.get("disease") or "")
        rows.append(
            {
                "disease": "T2D",
                "bioproject": r.get("BioProject") or "PRJNA1447078",
                "study": r.get("SRAStudy") or "SRP688705",
                "run": r.get("Run"),
                "biosample": r.get("BioSample"),
                "sample_name": r.get("SampleName"),
                "host_subject_id": a.get("isolate") or r.get("SampleName"),
                "group": group,
                "ml_label": group,
                "sex": a.get("sex") or "",
                "age": a.get("age") or "",
                "tissue": a.get("tissue") or "feces",
                "phenotype": a.get("phenotype") or "",
                "disease_annotation": a.get("disease") or "",
                "disease_stage": a.get("disease_stage") or "",
                "library_strategy": r.get("LibraryStrategy"),
                "library_layout": r.get("LibraryLayout"),
                "spots": r.get("spots"),
                "size_MB": r.get("size_MB"),
                "instrument": r.get("Model"),
            }
        )
    return rows


def main() -> None:
    ibd = build_ibd()
    crc = build_crc()
    t2d = build_t2d()

    common = [
        "disease",
        "bioproject",
        "study",
        "run",
        "biosample",
        "sample_name",
        "host_subject_id",
        "group",
        "ml_label",
        "sex",
        "age",
        "tissue",
        "library_strategy",
        "library_layout",
        "spots",
        "size_MB",
        "instrument",
    ]
    write_csv(OUT / "ibd_groups.csv", ibd, common + ["host_subject_id"])
    write_csv(
        OUT / "crc_groups.csv",
        crc,
        common + ["sample_origin", "bmi_class", "stage"],
    )
    write_csv(
        OUT / "t2d_groups.csv",
        t2d,
        common + ["phenotype", "disease_annotation", "disease_stage"],
    )
    all_rows = []
    for rows in (ibd, crc, t2d):
        for r in rows:
            all_rows.append({k: r.get(k, "") for k in common})
    write_csv(OUT / "ml_labels.csv", all_rows, common)

    def stats(rows):
        return {
            "n": len(rows),
            "groups": dict(Counter(r["ml_label"] for r in rows)),
            "size_MB": sum(int(r.get("size_MB") or 0) for r in rows),
            "bioproject": rows[0]["bioproject"] if rows else "",
            "study": rows[0]["study"] if rows else "",
        }

    catalog = {
        "updated": time.strftime("%Y-%m-%d"),
        "diseases": [
            {
                "id": "IBD",
                "name_zh": "發炎性腸道疾病",
                "name_en": "Inflammatory bowel disease",
                "bioproject": "PRJEB86986",
                "study": "ERP170281",
                "region": "16S (PacBio Sequel IIe)",
                "site": "stool",
                "grouping": "IBD (SMH*) vs Healthy (HC*) from host subject id",
                "ml_task": "binary classification",
                **stats(ibd),
            },
            {
                "id": "CRC",
                "name_zh": "大腸直腸癌",
                "name_en": "Colorectal cancer",
                "bioproject": "PRJNA989099",
                "study": "SRP446495",
                "region": "16S V3–V4 amplicon",
                "site": "tumor / adjacent non-tumor / paired samples",
                "grouping": "Tumor vs NonTumor (BioSample Sample origin + sample name)",
                "ml_task": "binary / multiclass classification",
                **stats(crc),
            },
            {
                "id": "T2D",
                "name_zh": "第二型糖尿病",
                "name_en": "Type 2 diabetes",
                "bioproject": "PRJNA1447078",
                "study": "SRP688705",
                "region": "16S rRNA amplicon",
                "site": "stool",
                "grouping": "T2D with vs without sensorineural hearing loss",
                "ml_task": "binary classification (comorbidity phenotype)",
                **stats(t2d),
            },
        ],
    }
    (OUT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(catalog, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
