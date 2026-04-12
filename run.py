#!/usr/bin/env python3
"""
BSGS - Bitcoin Private Key Search
Environment check and quick-start guide
"""

import sys
import multiprocessing

def check_environment():
    print("=" * 65)
    print("  BSGS - Bitcoin Private Key Search")
    print("  Baby-Step Giant-Step Algorithm")
    print("=" * 65)
    print()

    py = sys.version_info
    print(f"  Python      : {py.major}.{py.minor}.{py.micro}")
    print(f"  CPU cores   : {multiprocessing.cpu_count()}")

    try:
        import numpy as np
        print(f"  NumPy       : {np.__version__} (OK)")
    except ImportError:
        print("  NumPy       : NOT INSTALLED — run: pip install numpy")

    try:
        import gmpy2
        print(f"  gmpy2       : {gmpy2.version()} (OK, fast math enabled)")
    except ImportError:
        print("  gmpy2       : not installed (optional, speeds up math)")
        print("                install: pip install gmpy2")

    try:
        import cupy as cp
        devs = cp.cuda.runtime.getDeviceCount()
        print(f"  CuPy/CUDA   : OK — {devs} GPU device(s) found")
        gpu_ok = True
    except ImportError:
        print("  CuPy/CUDA   : not installed (GPU mode unavailable)")
        gpu_ok = False
    except Exception as e:
        print(f"  CuPy/CUDA   : error ({e})")
        gpu_ok = False

    print()
    print("─" * 65)
    print("  CPU MODE IS AVAILABLE (no GPU required)")
    print("─" * 65)
    print()
    print("  Quick-start (CPU):")
    print("  python3 bsgs_scan.py --cpu -p <pubkey> -s <start> -e <end>")
    print()
    print("  Example (puzzle #49):")
    print("  python3 bsgs_scan.py --cpu \\")
    print("    -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \\")
    print("    -s 0x2000000000000 -e 0x3ffffffffffff")
    print()
    print("  Benchmark (calibrate this CPU, find optimal M_SIZE, project time):")
    print("  python3 bsgs_scan.py --benchmark -s 0x2000000000000 -e 0x3ffffffffffff")
    print()
    print("  Benchmark then auto-run with optimal settings:")
    print("  python3 bsgs_scan.py --benchmark --run \\")
    print("    -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \\")
    print("    -s 0x2000000000000 -e 0x3ffffffffffff -o result.txt")
    print()
    print("  Random scan (probabilistic, multi-machine, resumable):")
    print("  python3 bsgs_scan.py --cpu -R 50 --seed 0 \\")
    print("    -p <pubkey> -s 0x2000000000000 -e 0x3ffffffffffff")
    print("  # Other machines: --seed 1, --seed 2, ... (no overlap)")
    print("  # After Ctrl+C:   add --resume to continue from same position")
    print()
    if gpu_ok:
        print("  GPU mode (faster, requires CUDA):")
        print("  python3 bsgs_scan.py -p <pubkey> -s <start> -e <end>")
        print()
    print("  All options:")
    print("  python3 bsgs_scan.py --help")
    print()
    print("=" * 65)

if __name__ == "__main__":
    check_environment()
