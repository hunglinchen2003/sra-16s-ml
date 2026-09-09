# SRA 16S Lab

搜尋 NCBI SRA 的人類 **16S microbiota** 資料，並提供三個疾病隊列的**樣品分群表**，給機器學習課程當監督式學習標籤。

- 網頁（GitHub Pages）：https://hunglinchen2003.github.io/sra-16s-ml/
- 區網即時搜尋／下載進度：http://10.0.1.100:8770/
- 原始碼：https://github.com/hunglinchen2003/sra-16s-ml

## 三個隊列

| 疾病 | BioProject | Study | 分群標籤 (`ml_label`) |
|------|------------|-------|------------------------|
| IBD 發炎性腸道疾病 | PRJEB86986 | ERP170281 | `IBD` / `Healthy`（host subject id：`SMH*` vs `HC*`） |
| CRC 大腸直腸癌 | PRJNA989099 | SRP446495 | `Tumor` / `NonTumor`（BioSample Sample origin） |
| T2D 第二型糖尿病 | PRJNA1447078 | SRP688705 | `T2D_hearing_loss` / `T2D_normal_hearing` |

序列仍屬原作者與 NCBI，僅供教學。

## 標籤檔

- [`docs/data/ml_labels.csv`](docs/data/ml_labels.csv) — 三病合併
- `ibd_groups.csv` / `crc_groups.csv` / `t2d_groups.csv`

課程用法：QIIME 2 得到 feature table 後，以 `run` 對上 `ml_label`，用 sklearn 做分類。

## 主機下載（10.0.1.100）

資料目錄：`/home/hlc/SRA_16S_ML/{IBD,CRC,T2D}/{sra,fastq,metadata}`

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate sratools
python scripts/download_sra.py --limit 24    # 課程子集（每病均衡抽樣）
# python scripts/download_sra.py              # 全數（CRC 約數 GB，較久）
```

Web UI 服務：`sra16s-webui.service`（port 8770）。
