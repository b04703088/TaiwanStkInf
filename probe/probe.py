import subprocess, sys, pathlib, shutil
root = pathlib.Path(__file__).resolve().parents[1]
out = root / "probe" / "out"; out.mkdir(exist_ok=True)
for p in out.iterdir():
    shutil.rmtree(p) if p.is_dir() else p.unlink()
r = subprocess.run([sys.executable, "fetch_etf_rebalance.py", "--etfs", "0056", "00878", "00919", "00929", "--max-minutes", "25"],
                   cwd=root, capture_output=True, text=True)
(out / "log.txt").write_text(r.stdout + "\n--- stderr\n" + r.stderr[-20000:], encoding="utf-8")
shutil.copytree(root / "data" / "etf" / "rebalance", out / "rebalance")
