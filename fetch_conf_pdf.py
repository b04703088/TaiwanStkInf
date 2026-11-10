"""法說會簡報 → 給每晚「法說 memo」排程讀的文字與圖片（data/conf/）

來源：data/mops/calls.csv（fetch_mops_news.py 的法說會一覽）的 file 欄
      → https://mopsov.twse.com.tw/nas/STR/<file>
挑選：
  - 法說日已到（今天或以前）、最近 DAYS 天內
  - 同一份簡報只做一次（以檔名為準；券商論壇常重複用同一份）
  - 檔名裡的上傳日（代號後 8 碼）在 STALE 天內；更早的是幾個月前的舊簡報被拿來重複用
  - 近 5 日平均成交值 ≥ MIN_LIQ（預設 5 億），控制每天要寫的份數
輸出：
  data/conf/index.csv          key, code, name, market, date, time, place, pages, chars, imgs, liq, status, tries
                               status：ok（可以寫 memo）、fail（下載或轉檔失敗，下次再試，最多 3 次）
  data/conf/text/<key>.txt     pdftotext -layout 的文字，每頁開頭標 [p.N]；去掉每頁重複的頁首頁尾、免責聲明頁
  data/conf/img/<key>/pNN.jpg  文字很少的頁（多半是圖表、截圖）轉成圖片，最多 MAX_IMG 頁
  data/conf/memo/<key>.md      memo 本身，由每晚的排程（Claude）寫；這支只負責把寫好的那份圖片刪掉
需要 pdftotext / pdftoppm（apt 套件 poppler-utils）。
"""
import argparse
import csv
import re
import subprocess
import tempfile
import time
import urllib.request
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "conf"
URL = "https://mopsov.twse.com.tw/nas/STR/{}"
COLS = ["key", "code", "name", "market", "date", "time", "place", "pages", "chars", "imgs", "liq", "status", "tries"]
DAYS = 14
MIN_LIQ = 5e8
MAX_IMG = 8
STALE = 30
FILE = re.compile(r"^\d{4}(\d{8})M\d+\.pdf$", re.I)
IMG_CHARS = 150          # 一頁非空白字元少於這個數就當圖片頁
MAX_TEXT = 60000
DISCLAIMER = re.compile(r"免責聲明|Safe\s*Harbor|Forward[- ]Looking\s+Statements?|前瞻性(陳述|聲明)|Disclaimer", re.I)


def _read(p):
    if not Path(p).exists():
        return []
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})


def liquidity():
    files = [f for f in sorted(DATA.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name) if len(f.stem) == 8][-5:]
    val = Counter()
    for f in files:
        for r in _read(f):
            try:
                val[r["code"]] += float(r["value"].replace(",", "")) / len(files)
            except (KeyError, ValueError, AttributeError):
                pass
    return val


def pick(calls, done, today, liq, days=DAYS, min_liq=MIN_LIQ):
    """每份簡報取第一場已舉行的法說；回傳 [(key, row)]。"""
    since = (today - timedelta(days=days)).isoformat()
    stale = (today - timedelta(days=STALE)).strftime("%Y%m%d")
    first = {}
    for r in sorted(calls, key=lambda r: (r["date"], r["time"])):
        f = (r.get("file") or "").strip()
        m = FILE.match(f)
        if not m or m.group(1) < stale or r["date"] > today.isoformat():
            continue
        first.setdefault(f, r)
    out = []
    for f, r in first.items():
        key = f[:-4]
        if key in done or r["date"] < since or liq.get(r["code"], 0) < min_liq:
            continue
        out.append((key, r))
    out.sort(key=lambda x: -liq.get(x[1]["code"], 0))
    return out


def clean_pages(pages):
    """去掉每頁都出現的頁首頁尾、前 3 頁裡的免責聲明頁、壓縮空白。回傳 [(頁碼, 文字)]。"""
    n = len(pages)
    cnt = Counter()
    for p in pages:
        cnt.update({ln.strip() for ln in p.splitlines() if ln.strip()})
    rep = {ln for ln, c in cnt.items() if n >= 4 and c >= max(3, n * 0.5) and len(ln) < 80}
    out = []
    for i, p in enumerate(pages, 1):
        if i <= 3 and DISCLAIMER.search(p) and len(re.sub(r"\s", "", p)) < 1500:
            continue
        lines = [re.sub(r" {3,}", "  ", ln.rstrip()) for ln in p.splitlines() if ln.strip() and ln.strip() not in rep]
        out.append((i, "\n".join(lines)))
    return out


def image_pages(pages, n_pages):
    """文字很少的頁（第 1 頁封面、最後 1 頁致謝不算），最多 MAX_IMG 頁。"""
    lens = {i: len(re.sub(r"\s", "", t)) for i, t in pages}
    cand = [i for i in range(2, n_pages) if lens.get(i, 0) < IMG_CHARS and i in lens]
    return cand[:MAX_IMG]


def process(key, pdf_bytes):
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "a.pdf"
        pdf.write_bytes(pdf_bytes)
        txt = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
        raw = txt.split("\f")
        if raw and not raw[-1].strip():
            raw = raw[:-1]
        pages = clean_pages(raw)
        body = "\n\n".join(f"[p.{i}]\n{t}" for i, t in pages)[:MAX_TEXT]
        (OUT / "text").mkdir(parents=True, exist_ok=True)
        (OUT / "text" / f"{key}.txt").write_text(body, encoding="utf-8")
        imgs = image_pages(pages, len(raw))
        if imgs:
            d = OUT / "img" / key
            d.mkdir(parents=True, exist_ok=True)
            for i in imgs:
                subprocess.run(["pdftoppm", "-jpeg", "-jpegopt", "quality=60", "-scale-to", "1100", "-f", str(i), "-l", str(i),
                                "-singlefile", str(pdf), str(d / f"p{i:02d}")], capture_output=True, timeout=120)
        return len(raw), len(re.sub(r"\s", "", body)), len(imgs)


def cleanup():
    """memo 寫好的就把圖片刪掉（文字留著，日後重寫可用）。"""
    memo = {p.stem for p in (OUT / "memo").glob("*.md")}
    for d in (OUT / "img").glob("*"):
        if d.is_dir() and d.name in memo:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--min-liq", type=float, default=MIN_LIQ)
    ap.add_argument("--max", type=int, default=40, help="一次最多抓幾份")
    args = ap.parse_args()
    today = date.fromisoformat(subprocess.run(["date", "+%F"], capture_output=True, text=True, env={"TZ": "Asia/Taipei"}).stdout.strip())
    idx = {r["key"]: r for r in _read(OUT / "index.csv")}
    done = {k for k, r in idx.items() if r["status"] == "ok" or int(r.get("tries") or 0) >= 3}
    liq = liquidity()
    todo = pick(_read(DATA / "mops" / "calls.csv"), done, today, liq, args.days, args.min_liq)[:args.max]
    print(f"{today} 待抓簡報 {len(todo)} 份")
    for key, r in todo:
        row = {k: r.get(k, "") for k in ("code", "name", "market", "date", "time", "place")}
        row.update(key=key, liq=round(liq.get(r["code"], 0) / 1e8, 1), tries=int((idx.get(key) or {}).get("tries") or 0) + 1)
        try:
            req = urllib.request.Request(URL.format(key + ".pdf"), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                b = resp.read(40 * 1024 * 1024)
            if not b.startswith(b"%PDF"):
                raise ValueError("不是 PDF")
            pages, chars, imgs = process(key, b)
            row.update(status="ok", pages=pages, chars=chars, imgs=imgs)
            print(f"  {key} {r['code']} {r['name']} {r['date']} 頁 {pages} 字 {chars} 圖 {imgs}")
        except Exception as e:  # noqa: BLE001
            row.update(status="fail")
            print(f"  {key} {r['code']} 失敗：{e}")
        idx[key] = row
        time.sleep(2)
    cleanup()
    _write(OUT / "index.csv", sorted(idx.values(), key=lambda r: (r["date"], r["time"], r["code"]), reverse=True))


if __name__ == "__main__":
    main()
