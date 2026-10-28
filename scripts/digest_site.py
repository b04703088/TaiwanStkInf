"""data/digest/（scripts/digest.py 的數字摘要、notes/ 的每晚判讀）→ 盤後摘要頁（digest.html）用的檔案。

  data/digest/index.json        {dates: [{date, note}]}  由新到舊，最近 N 天
  data/digest/<日期>.md          數字摘要
  data/digest/notes/<日期>.md    判讀（有才有）
"""
import json
import shutil
from pathlib import Path

N = 60


def write_digest(data: Path, out: Path):
    src = data / "digest"
    out.mkdir(parents=True, exist_ok=True)
    days = sorted((p.stem for p in src.glob("[0-9]*.md")), reverse=True)[:N] if src.exists() else []
    rows = []
    for d in days:
        shutil.copy(src / f"{d}.md", out / f"{d}.md")
        note = src / "notes" / f"{d}.md"
        if note.exists():
            (out / "notes").mkdir(exist_ok=True)
            shutil.copy(note, out / "notes" / f"{d}.md")
        rows.append({"date": d, "note": note.exists()})
    (out / "index.json").write_text(json.dumps({"dates": rows}, ensure_ascii=False), encoding="utf-8")
