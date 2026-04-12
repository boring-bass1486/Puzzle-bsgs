#!/usr/bin/env python3
"""
BSGS - Bitcoin Private Key Search
Environment check and quick-start guide
"""

import sys
import os
import multiprocessing

PUBKEY = "022769bf9a08e9c08a343de2a1c1c2b36aaece3d58af1e6a77c69afdfc47bc90bc"
START  = "0x1000000000000000000000000000000000000"
END    = "0x1ffffffffffffffffffffffffffffffffffff"

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
    print("  Example (puzzle #145):")
    print(f"  python3 bsgs_scan.py --cpu \\")
    print(f"    -p {PUBKEY} \\")
    print(f"    -s {START} -e {END}")
    print()
    print("  Sequential scan (full range, resumable):")
    print(f"  python3 bsgs_scan.py --cpu \\")
    print(f"    -p {PUBKEY} \\")
    print(f"    -s {START} -e {END}")
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
    print()

if __name__ == "__main__":
    check_environment()

    print("  AUTO-STARTING puzzle #145 sequential scan ...")
    print(f"  From: {START}")
    print(f"  To  : {END}")
    print("  Press Ctrl+C to stop. Add --resume to continue from last position.")
    print("=" * 65)
    print()

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bsgs_scan.py")
    args = [
        sys.executable, script,
        "--cpu",
        "-p", PUBKEY,
        "-s", START,
        "-e", END,
    ]
    os.execv(sys.executable, args)
