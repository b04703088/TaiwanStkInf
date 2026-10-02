import subprocess, sys, pathlib
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
root = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(root))
import fetch_cb as F
out = root / "probe" / "out"; out.mkdir(exist_ok=True)
for p in out.iterdir(): p.unlink()
want = {2025: ["114196", "114053", "114388", "114225", "114310", "114448", "114056"],
        2026: ["115060", "115010", "115366", "115096", "115034", "115379", "115240"]}
log = []
for y, sns in want.items():
    ed = F.Edoc(y, "UnderwritingNotice")
    for tds, btn in ed.rows:
        if tds[0] in sns:
            try:
                txt = F.pdf_text(ed.pdf(btn))
                (out / f"n_{tds[0]}.txt").write_text(txt, encoding="utf-8")
                log.append(f"{tds[0]} ok {len(txt)}")
            except Exception as e:
                log.append(f"{tds[0]} {e!r}")
(out / "dbg.txt").write_text("\n".join(log), encoding="utf-8")
