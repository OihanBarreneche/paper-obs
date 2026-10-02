"""For each count, list the V structures of domv.c that hold it slightly above the live value,
refine them all with vsweep.py and report the best against the live value.

Usage: python vdriver.py 20 50 [margin]
"""
import math
import subprocess
import sys
from pathlib import Path

r = math.sqrt(2)
LIVE = {1: 2 * r, 2: 1 + 2 * r, 3: 3 * r, 4: 2 + 2 * r, 5: 1 + 3 * r, 6: 4 * r, 7: 2 + 3 * r, 8: 5 + r, 9: 4 + 2 * r,
        10: 5 * r, 11: 6 + r, 12: 5 + 2 * r, 13: 8, 14: 4 + 3 * r, 15: 6 * r, 16: 6 + 2 * r, 17: 9, 18: 5 + 3 * r,
        19: 1 + 6 * r, 20: 7 + 2 * r, 21: 7 * r, 22: 3 + 5 * r, 23: 9 + r, 24: 10.57901, 25: 8 + 2 * r, 26: 10.99322,
        27: 4 + 5 * r, 28: 8 * r, 29: 3 + 6 * r, 30: 9 + 2 * r, 31: 2 + 7 * r, 32: 12.0569644, 33: 8 + 3 * r,
        34: 11 + r, 35: 12.59172, 36: 9 * r, 37: 3 + 7 * r, 38: 13.0569644, 39: 9 + 3 * r, 40: 12 + r,
        41: 8 + 4 * r, 42: 1 + 9 * r, 43: 4 + 7 * r, 44: 14.02663, 45: 10 * r, 46: 3 + 8 * r, 47: 6 + 6 * r,
        48: 9 + 4 * r, 49: 12 + 2 * r, 50: 5 + 7 * r}
WORK = "."  # this folder: wsl.exe starts in the directory it is launched from
first, last = int(sys.argv[1]), int(sys.argv[2])
margin = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
for n in range(first, last + 1):
    s = LIVE[n] + margin
    listing = Path("results") / f"list{n}.txt"
    with open(listing, "w") as out:
        subprocess.run(["wsl.exe", "--exec", "bash", "-c", f"cd {WORK} && nice -n 19 ./domv 0 list {n} {s:.6f} 3000"],
                       stdout=out, check=True)
    count = len(listing.read_text().splitlines())
    if count == 0:
        print(f"{n:2d}  live {LIVE[n]:.6f}  no V structure at {s:.4f}", flush=True)
        continue
    res = subprocess.run([sys.executable, "vsweep.py", str(listing), str(n), f"{s:.6f}"], capture_output=True, text=True)
    best = res.stdout.splitlines()[0] if res.stdout else "?"
    side = float(best.split()[0]) if best != "?" else math.inf
    mark = "BEATS" if side < LIVE[n] - 1e-7 else ""
    print(f"{n:2d}  live {LIVE[n]:.6f}  best {side:.6f} {mark}  ({count} structures)  {best[10:150]}", flush=True)
