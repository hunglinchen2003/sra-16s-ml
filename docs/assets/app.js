const PRESETS = [
  {
    id: "IBD",
    label: "IBD 16S 糞便",
    q: 'AMPLICON[Strategy] AND 16S AND "Homo sapiens"[Organism] AND (stool OR feces) AND (IBD OR Crohn)',
  },
  {
    id: "CRC",
    label: "CRC 16S",
    q: 'AMPLICON[Strategy] AND 16S AND "Homo sapiens"[Organism] AND ("colorectal cancer" OR CRC)',
  },
  {
    id: "T2D",
    label: "T2D 16S 糞便",
    q: 'AMPLICON[Strategy] AND 16S AND "Homo sapiens"[Organism] AND ("type 2 diabetes") AND (stool OR feces)',
  },
];

const API_CANDIDATES = [
  `${location.origin}/api`,
  "http://10.0.1.100:8770/api",
];

const $ = (id) => document.getElementById(id);

function parseExpxml(expxml) {
  const pick = (re) => ((expxml || "").match(re) || [, ""])[1];
  return {
    study: pick(/<Study acc="([^"]+)"/),
    studyName: pick(/<Study acc="[^"]+" name="([^"]*)"/),
    title: pick(/<Title>([^<]+)</),
    lib: pick(/<LIBRARY_STRATEGY>([^<]+)</),
    org: pick(/ScientificName="([^"]+)"/),
  };
}

async function firstOk(urls, init) {
  for (const url of urls) {
    try {
      const res = await fetch(url, { ...init, signal: AbortSignal.timeout(8000) });
      if (res.ok) return { url, res };
    } catch (_) {
      /* try next */
    }
  }
  return null;
}

async function searchSra(term) {
  const local = await firstOk(
    API_CANDIDATES.map((b) => `${b}/search?q=${encodeURIComponent(term)}&retmax=25`)
  );
  if (local) return local.res.json();

  const eutils =
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&retmode=json&retmax=25&term=" +
    encodeURIComponent(term);
  const es = await fetch(eutils);
  if (!es.ok) throw new Error("NCBI esearch 失敗（GitHub Pages 可能被 CORS 擋住，請用 10.0.1.100:8770）");
  const sj = await es.json();
  const ids = sj.esearchresult?.idlist || [];
  if (!ids.length) return { count: 0, hits: [] };
  const sum = await fetch(
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=sra&retmode=json&id=" + ids.join(",")
  );
  const sm = await sum.json();
  const hits = ids.map((id) => {
    const p = parseExpxml(sm.result?.[id]?.expxml || "");
    return { uid: id, ...p };
  });
  return { count: Number(sj.esearchresult.count || hits.length), hits };
}

function renderSearch(data) {
  $("search-meta").textContent = data.error
    ? data.error
    : `約 ${data.count || 0} 筆；下列為前 ${data.hits?.length || 0} 筆（依 study 摺疊顯示）。`;
  const tbody = $("search-table").querySelector("tbody");
  tbody.innerHTML = "";
  const by = new Map();
  for (const h of data.hits || []) {
    const key = h.study || h.uid;
    if (!by.has(key)) by.set(key, h);
  }
  for (const [study, h] of by) {
    const tr = document.createElement("tr");
    const acc = h.study || "";
    tr.innerHTML = `
      <td><code>${acc || "—"}</code></td>
      <td>${h.studyName || h.title || ""}</td>
      <td>${h.lib || ""}</td>
      <td>${h.org || ""}</td>
      <td>${
        acc
          ? `<a href="https://www.ncbi.nlm.nih.gov/sra/?term=${encodeURIComponent(acc)}" target="_blank" rel="noopener">SRA</a>`
          : ""
      }</td>`;
    tbody.appendChild(tr);
  }
}

async function loadCatalog() {
  const res = await fetch("data/catalog.json");
  const catalog = await res.json();
  const cards = $("cohort-cards");
  cards.innerHTML = "";
  for (const d of catalog.diseases) {
    const groups = Object.entries(d.groups || {})
      .map(([k, v]) => `<span class="bar">${k} ${v}</span>`)
      .join("");
    const el = document.createElement("article");
    el.className = "card";
    el.innerHTML = `
      <div class="id">${d.id} · ${d.bioproject}</div>
      <h3>${d.name_zh}</h3>
      <p>${d.name_en}</p>
      <dl>
        <dt>Study</dt><dd><code>${d.study}</code></dd>
        <dt>樣本數</dt><dd>${d.n}（約 ${d.size_MB} MB）</dd>
        <dt>區間</dt><dd>${d.region}</dd>
        <dt>取材</dt><dd>${d.site}</dd>
        <dt>分群</dt><dd>${d.grouping}</dd>
        <dt>ML 任務</dt><dd>${d.ml_task}</dd>
      </dl>
      <div class="bars">${groups}</div>`;
    cards.appendChild(el);
  }
  return catalog;
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const cols = [];
    let cur = "";
    let q = false;
    for (const ch of line) {
      if (ch === '"') q = !q;
      else if (ch === "," && !q) {
        cols.push(cur);
        cur = "";
      } else cur += ch;
    }
    cols.push(cur);
    const row = {};
    headers.forEach((h, i) => (row[h] = cols[i] || ""));
    return row;
  });
}

let LABELS = [];

function renderLabels() {
  const disease = $("label-disease").value;
  const rows = LABELS.filter((r) => disease === "all" || r.disease === disease);
  $("label-count").textContent = `${rows.length} 筆`;
  const tbody = $("label-table").querySelector("tbody");
  tbody.innerHTML = "";
  for (const r of rows.slice(0, 400)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.disease}</td>
      <td><a href="https://www.ncbi.nlm.nih.gov/sra/${r.run}" target="_blank" rel="noopener">${r.run}</a></td>
      <td>${r.sample_name}</td>
      <td><strong>${r.ml_label}</strong></td>
      <td>${r.sex}</td>
      <td>${r.age}</td>
      <td>${r.tissue}</td>
      <td>${r.size_MB}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadLabels() {
  const res = await fetch("data/ml_labels.csv");
  LABELS = parseCsv(await res.text());
  renderLabels();
}

async function loadStatus() {
  const box = $("download-status");
  const hit = await firstOk(API_CANDIDATES.map((b) => `${b}/status`));
  if (!hit) {
    box.textContent =
      "目前是 GitHub Pages 靜態站，看不到 10.0.1.100 的下載行程（HTTPS 不能呼叫區網 HTTP）。\n" +
      "請在區網開啟 http://10.0.1.100:8770/ 看進度。\n" +
      "主機目錄：/home/hlc/SRA_16S_ML/{IBD,CRC,T2D}/{sra,fastq,metadata}";
    return;
  }
  const js = await hit.res.json();
  box.textContent = JSON.stringify(js, null, 2);
}

function wirePresets() {
  const wrap = $("preset-chips");
  PRESETS.forEach((p, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (i === 0 ? " active" : "");
    b.textContent = p.label;
    b.addEventListener("click", () => {
      wrap.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      b.classList.add("active");
      $("q").value = p.q;
      $("search-form").requestSubmit();
    });
    wrap.appendChild(b);
  });
}

$("search-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("search-meta").textContent = "搜尋中…";
  try {
    const data = await searchSra($("q").value);
    renderSearch(data);
  } catch (err) {
    renderSearch({ error: String(err), hits: [], count: 0 });
  }
});

$("label-disease").addEventListener("change", renderLabels);

wirePresets();
loadCatalog();
loadLabels();
loadStatus();
setInterval(loadStatus, 15000);
$("search-form").requestSubmit();
