import subprocess, sys, pathlib, shutil
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
root = pathlib.Path(__file__).resolve().parents[1]
out = root / "probe" / "out"; out.mkdir(exist_ok=True)
for p in out.iterdir(): p.unlink()
r = subprocess.run([sys.executable, "fetch_cb.py"], cwd=root, capture_output=True, text=True)
(out / "log.txt").write_text(r.stdout + "\n--- stderr\n" + r.stderr, encoding="utf-8")
for f in (root / "data" / "cb").glob("*"):
    shutil.copy(f, out / f.name)
