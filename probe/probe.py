import subprocess, sys, pathlib, shutil
root = pathlib.Path(__file__).resolve().parents[1]
out = root / "probe" / "out"; out.mkdir(exist_ok=True)
for p in out.iterdir(): p.unlink()
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl"], check=False)
r = subprocess.run([sys.executable, "fetch_cb_pre.py", "--max-minutes", "40"], cwd=root, capture_output=True, text=True)
(out / "log.txt").write_text(r.stdout + "\n--- stderr\n" + r.stderr[-20000:], encoding="utf-8")
for f in ["sfb.csv", "mops_events.csv", "mops_days.txt", "pre_sources.json"]:
    p = root / "data" / "cb" / f
    if p.exists(): shutil.copy(p, out / f)
