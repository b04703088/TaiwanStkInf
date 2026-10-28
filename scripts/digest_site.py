"""data/digest/（scripts/digest.py 的數字摘要、notes/ 的每晚判讀）→ 盤後摘要頁（digest.html）用的檔案。

  data/digest/index.json        {dates: [{date, note, am}]}  由新到舊，最近 N 天
  data/digest/<日期>.md          數字摘要
  data/digest/notes/<日期>.md    判讀（有才有）
  data/digest/notes/<日期>-am.md 隔天早上 8 點的早盤更新（美股、Fed、夜盤；有才有）
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
        has = {}
        for k, name in (("note", f"{d}.md"), ("am", f"{d}-am.md")):
            f = src / "notes" / name
            has[k] = f.exists()
            if has[k]:
                (out / "notes").mkdir(exist_ok=True)
                shutil.copy(f, out / "notes" / name)
        rows.append({"date": d, **has})
    (out / "index.json").write_text(json.dumps({"dates": rows}, ensure_ascii=False), encoding="utf-8")
