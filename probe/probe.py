import pathlib, subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pdfplumber"], check=False)
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(__file__).parent / "out"; OUT.mkdir(exist_ok=True)
r = subprocess.run([sys.executable, str(ROOT / "fetch_tip_schedule.py"), "--pages", "3"], cwd=ROOT, capture_output=True, text=True)
(OUT / "tip.txt").write_text(f"rc={r.returncode}\n{r.stdout}\n--stderr--\n{r.stderr[-8000:]}", encoding="utf-8")
