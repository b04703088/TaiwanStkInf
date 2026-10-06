import subprocess, sys, pathlib, shutil
root = pathlib.Path(__file__).resolve().parents[1]
out = root / "probe" / "out"; out.mkdir(exist_ok=True)
for p in out.iterdir(): p.unlink()
r = subprocess.run([sys.executable, "fetch_industry.py"], cwd=root, capture_output=True, text=True)
(out / "log.txt").write_text(r.stdout + "\n--- stderr\n" + r.stderr[-20000:], encoding="utf-8")
for p in (root / "data" / "industry").glob("*"):
    shutil.copy(p, out / p.name)
