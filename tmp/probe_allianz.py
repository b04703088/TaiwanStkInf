import sys, time
sys.path.insert(0, ".")
import etf_adapters as A
for fn, codes in [(A.allianz, ["00984A", "00993A", "00402A", "00412A"]), (A.nomura, ["00980A", "00985A", "00999A"]),
                  (A.esun, ["009803", "00413A"])]:
    for c in codes:
        t = time.time()
        try:
            r = fn(c, {"009803": "玉山市值動能50", "00413A": "主動玉山關鍵科技"}.get(c, ""))
            print(c, fn.__name__, r[0], len(r[1]), f"{time.time()-t:.1f}s")
        except Exception as e:
            print(c, fn.__name__, "ERR", e)
