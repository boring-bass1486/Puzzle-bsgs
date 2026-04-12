#!/usr/bin/env python3
"""
Rukka BSGS - Bitcoin Private Key Search using Baby-Step Giant-Step Algorithm
Supports GPU (CUDA/CuPy) and CPU (multiprocessing) backends
"""

import time
import sys
import os
import json
import math
import signal
import random as _rnd
import argparse
import hashlib
import multiprocessing
from datetime import datetime

# Set by run_bsgs_cpu's KeyboardInterrupt handler so outer callers can detect it
_INTERRUPTED = False

# ── Optional fast integer backend ───────────────────────────────────────────
try:
    import gmpy2
    _HAVE_GMPY2 = True
    def _modinv(a, n):
        return int(gmpy2.invert(a, n))
    def _mul(a, b, n):
        return int(gmpy2.mpz(a) * b % n)
except ImportError:
    _HAVE_GMPY2 = False
    def _modinv(a, n):
        return pow(a, n - 2, n)
    def _mul(a, b, n):
        return a * b % n

# ── Optional GPU backend ─────────────────────────────────────────────────────
try:
    import numpy as np
    import cupy as cp
    _HAVE_GPU = True
except ImportError:
    try:
        import numpy as np
    except ImportError:
        np = None
    _HAVE_GPU = False

# ============================================================================
# DEFAULT CONFIGURATION
# ============================================================================

DEFAULT_PUBKEY = "03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6"
DEFAULT_START  = 0x2000000000000
DEFAULT_M_SIZE = 1 << 20   # 1M (CPU default; 4M for GPU)
DEFAULT_M_SIZE_GPU = 1 << 22  # 4M

DEFAULT_BABY_GEN_BLOCKS  = 512
DEFAULT_BABY_GEN_THREADS = 256
DEFAULT_BABY_BATCH       = 100000
DEFAULT_SEARCH_BLOCKS    = 2048
DEFAULT_SEARCH_THREADS   = 256
DEFAULT_GIANT_BATCH      = 5000000

CPU_MINI_BATCH = 2000   # giant-steps per sub-batch before batch-inversion
CPU_PROGRESS_EVERY = 200_000  # print progress every N giant steps

# ============================================================================
# SECP256K1 CONSTANTS
# ============================================================================

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (Gx, Gy)

# ============================================================================
# UTILITY
# ============================================================================

def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f} sec"
    elif seconds < 3600:
        return f"{seconds/60:.1f} min"
    else:
        return f"{seconds/3600:.2f} hr"

# ============================================================================
# BITCOIN ADDRESS / WIF HELPERS
# ============================================================================

def hash160(data):
    sha256_hash = hashlib.sha256(data).digest()
    rip = hashlib.new('ripemd160')
    rip.update(sha256_hash)
    return rip.digest()

def base58_encode(data):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    num = int.from_bytes(data, 'big')
    encoded = ''
    while num > 0:
        num, r = divmod(num, 58)
        encoded = alphabet[r] + encoded
    for byte in data:
        if byte == 0:
            encoded = '1' + encoded
        else:
            break
    return encoded

def pubkey_to_address(point, compressed=True):
    x, y = point
    if compressed:
        prefix = b'\x02' if y % 2 == 0 else b'\x03'
        pub = prefix + x.to_bytes(32, 'big')
    else:
        pub = b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')
    h160   = hash160(pub)
    ver    = b'\x00' + h160
    chk    = hashlib.sha256(hashlib.sha256(ver).digest()).digest()[:4]
    return base58_encode(ver + chk)

def privkey_to_wif(privkey, compressed=True):
    ext = b'\x80' + privkey.to_bytes(32, 'big')
    if compressed:
        ext += b'\x01'
    chk = hashlib.sha256(hashlib.sha256(ext).digest()).digest()[:4]
    return base58_encode(ext + chk)

# ============================================================================
# ELLIPTIC CURVE – AFFINE (used for key derivation / verification)
# ============================================================================

def modinv(a, n=P):
    return _modinv(a % n, n)

def ec_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if y1 == y2:
            m = (3 * x1 * x1 * modinv(2 * y1)) % P
        else:
            return None
    else:
        m = ((y2 - y1) * modinv(x2 - x1)) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)

def ec_mul(point, scalar):
    if scalar == 0: return None
    if scalar == 1: return point
    result, addend = None, point
    while scalar:
        if scalar & 1:
            result = ec_add(result, addend)
        addend = ec_add(addend, addend)
        scalar >>= 1
    return result

def decompress_pubkey(hex_str):
    prefix = int(hex_str[:2], 16)
    x = int(hex_str[2:], 16)
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (prefix == 0x02 and y % 2 != 0) or (prefix == 0x03 and y % 2 == 0):
        y = P - y
    return (x, y)

# ============================================================================
# ELLIPTIC CURVE – JACOBIAN (fast batch operations, no modinv in inner loop)
# ============================================================================
# Representation: (X, Y, Z) → affine (X/Z², Y/Z³)
# Infinity = Z == 0

def jac_double(X, Y, Z):
    """Double a Jacobian point (secp256k1, a=0)."""
    if Z == 0:
        return (1, 1, 0)
    Y2 = Y * Y % P
    S  = 4 * X * Y2 % P
    M  = 3 * X * X % P         # a = 0
    X3 = (M * M - 2 * S) % P
    Y3 = (M * (S - X3) - 8 * Y2 * Y2) % P
    Z3 = 2 * Y * Z % P
    return (X3, Y3, Z3)

def jac_add_mixed(X1, Y1, Z1, x2, y2):
    """Add Jacobian point (X1,Y1,Z1) + affine point (x2,y2)."""
    if Z1 == 0:
        return (x2, y2, 1)
    Z1sq = Z1 * Z1 % P
    U2   = x2 * Z1sq % P
    S2   = y2 * Z1sq * Z1 % P
    H    = (U2 - X1) % P
    R    = (S2 - Y1) % P
    if H == 0:
        if R == 0:
            return jac_double(X1, Y1, Z1)
        else:
            return (1, 1, 0)
    H2 = H * H % P
    H3 = H2 * H % P
    X3 = (R * R - H3 - 2 * X1 * H2) % P
    Y3 = (R * (X1 * H2 - X3) - Y1 * H3) % P
    Z3 = H * Z1 % P
    return (X3, Y3, Z3)

_INFINITY_X = -1   # sentinel for point-at-infinity in x-coordinate lists

def batch_to_affine_x(jac_points):
    """
    Convert a list of Jacobian points to their affine x-coordinates
    using Montgomery's batch inversion trick (one modinv for the whole batch).
    Returns list of x values in affine; points at infinity return _INFINITY_X.
    """
    n = len(jac_points)
    if n == 0:
        return []

    Zs = [pt[2] for pt in jac_points]

    # Identify infinity points (Z == 0)
    inf_mask = [z == 0 for z in Zs]

    # Replace Z=0 with 1 so the product stays valid
    safe_Zs = [1 if inf_mask[i] else Zs[i] for i in range(n)]

    # prefix products
    prods = [1] * (n + 1)
    for i in range(n):
        prods[i + 1] = prods[i] * safe_Zs[i] % P

    # single inversion
    inv = _modinv(prods[n], P)

    xs = [0] * n
    for i in range(n - 1, -1, -1):
        if inf_mask[i]:
            xs[i] = _INFINITY_X
            inv = inv * safe_Zs[i] % P   # keep running product correct
        else:
            inv_Z  = inv * prods[i] % P
            inv    = inv * safe_Zs[i] % P
            inv_Z2 = inv_Z * inv_Z % P
            xs[i]  = jac_points[i][0] * inv_Z2 % P
    return xs

def batch_to_affine(jac_points):
    """
    Convert Jacobian points to affine (x, y) pairs via batch inversion.
    """
    n = len(jac_points)
    if n == 0:
        return []
    Zs = [pt[2] for pt in jac_points]
    prods = [1] * (n + 1)
    for i in range(n):
        prods[i + 1] = prods[i] * Zs[i] % P
    inv = _modinv(prods[n], P)
    pts = [(0, 0)] * n
    for i in range(n - 1, -1, -1):
        inv_Z  = inv * prods[i] % P
        inv    = inv * Zs[i] % P
        inv_Z2 = inv_Z * inv_Z % P
        inv_Z3 = inv_Z2 * inv_Z % P
        X, Y, _ = jac_points[i]
        pts[i] = (X * inv_Z2 % P, Y * inv_Z3 % P)
    return pts

# ============================================================================
# CPU BABY STEP GENERATION
# ============================================================================

def generate_baby_steps_cpu(m_size, verbose=True):
    """
    Build baby-step table: { affine_x : j }  for j*G, j = 1..m_size.

    Uses Jacobian coordinates + batch inversion for speed.
    Baby step 0 is skipped (j=0 means point at infinity).
    """
    if verbose:
        print(f"[*] Building baby-step table ({m_size:,} entries)...")
        print(f"    Using {'gmpy2 fast-math' if _HAVE_GMPY2 else 'Python built-in math'}")

    CHUNK = 50_000
    table = {}

    # Start: j=1 → G in Jacobian
    jX, jY, jZ = Gx, Gy, 1
    jac_buf  = []
    idx_buf  = []

    t0 = time.time()
    for j in range(1, m_size + 1):
        jac_buf.append((jX, jY, jZ))
        idx_buf.append(j)

        jX, jY, jZ = jac_add_mixed(jX, jY, jZ, Gx, Gy)

        if len(jac_buf) == CHUNK or j == m_size:
            xs = batch_to_affine_x(jac_buf)
            for k, x in zip(idx_buf, xs):
                table[x] = k
            jac_buf.clear()
            idx_buf.clear()
            if verbose:
                elapsed = time.time() - t0
                rate    = j / elapsed if elapsed > 0 else 0
                print(f"\r    [{j:,}/{m_size:,}] {rate/1000:.0f} Kpts/s", end='', flush=True)

    elapsed = time.time() - t0
    if verbose:
        print(f"\r    Done: {m_size:,} entries in {elapsed:.1f}s "
              f"({m_size/elapsed/1000:.0f} Kpts/s)" + " " * 10)
    return table

# ============================================================================
# CPU GIANT STEP WORKER
# ============================================================================

# Global baby-step table shared via fork (Linux copy-on-write)
_BABY_TABLE  = None
_M_SIZE      = None
_START_RANGE = None

def _worker_init(baby_table, m_size, start_range):
    global _BABY_TABLE, _M_SIZE, _START_RANGE
    _BABY_TABLE  = baby_table
    _M_SIZE      = m_size
    _START_RANGE = start_range

def _giant_step_chunk(args):
    """
    Search giant steps i in [i_start, i_end).
    base = P_target - start_range*G - i_start*M*G  (affine tuple or None=infinity)
    neg_mG = -(M*G)  (affine tuple)

    Uses Jacobian accumulation + batch inversion every CPU_MINI_BATCH steps.
    Returns (i_absolute, j) or None.

    Special j values:
      j == 0 means point-at-infinity hit (key = start + i*M exactly).
    """
    i_start, i_end, base_x, base_y, base_is_inf, neg_mG_x, neg_mG_y = args
    table = _BABY_TABLE

    CHUNK = CPU_MINI_BATCH

    # Init Jacobian
    if base_is_inf:
        cur_jX, cur_jY, cur_jZ = 1, 1, 0   # point at infinity in Jacobian
    else:
        cur_jX, cur_jY, cur_jZ = base_x, base_y, 1

    i = i_start
    while i < i_end:
        sub_end = min(i + CHUNK, i_end)
        count   = sub_end - i

        jac_buf = []
        for _ in range(count):
            jac_buf.append((cur_jX, cur_jY, cur_jZ))
            cur_jX, cur_jY, cur_jZ = jac_add_mixed(cur_jX, cur_jY, cur_jZ, neg_mG_x, neg_mG_y)

        xs = batch_to_affine_x(jac_buf)
        for local_k, x in enumerate(xs):
            if x == _INFINITY_X:
                # Point at infinity → key = start_range + (i+local_k)*M
                return (i + local_k, 0)
            if x in table:
                return (i + local_k, table[x])
        i = sub_end

    return None

# ============================================================================
# RESULT VERIFICATION
# ============================================================================

def verify_and_build_result(i, j, start_range, m_size, P_target, args):
    """
    Try both candidates:
      key = start + i*M + j   (baby step +j)
      key = start + i*M - j   (baby step -j, same x but opposite y)
    j == 0 means point at infinity hit → key = start + i*M exactly.
    """
    if j == 0:
        candidates = [start_range + i * m_size]
    else:
        candidates = [
            start_range + i * m_size + j,
            start_range + i * m_size - j,
        ]
    for k in candidates:
        if k <= 0:
            continue
        pt = ec_mul(G, k)
        if pt == P_target:
            return k
    return None

def print_found(final_key, P_target, args, total_start):
    btc_address = pubkey_to_address(P_target, compressed=True)
    wif         = privkey_to_wif(final_key, compressed=True)
    elapsed     = time.time() - total_start

    print(f"\n{'='*80}")
    print(f"  PRIVATE KEY FOUND!")
    print(f"{'='*80}")
    print(f"  Private Key (Hex): \033[1;32m{hex(final_key).upper()}\033[0m")
    print(f"  Private Key (Dec): {final_key:,}")
    print(f"  WIF (Compressed):  {wif}")
    print(f"  Bitcoin Address:   {btc_address}")
    print(f"  Public Key:        {args.pubkey}")
    print(f"{'─'*80}")
    print(f"  Search Time:       {format_time(elapsed)}")
    print(f"  Verification:      \033[32mPASSED\033[0m")
    print(f"{'='*80}\n")

    if args.output:
        with open(args.output, 'w') as f:
            f.write(f"BSGS CPU - Private Key Found\n")
            f.write(f"{'='*40}\n\n")
            f.write(f"Private Key (Hex): {hex(final_key)}\n")
            f.write(f"Private Key (Dec): {final_key}\n")
            f.write(f"WIF (Compressed):  {wif}\n")
            f.write(f"Bitcoin Address:   {btc_address}\n")
            f.write(f"Public Key:        {args.pubkey}\n\n")
            f.write(f"Search Details:\n")
            f.write(f"  Start Range:  {hex(args.start_range)}\n")
            f.write(f"  M_SIZE:       {args.m_size:,}\n")
            f.write(f"  Search Time:  {format_time(elapsed)}\n")
            f.write(f"  Found at:     {datetime.now()}\n")
        print(f"Result saved to: {args.output}\n")

# ============================================================================
# RESUME STATE — save / load / delete
# ============================================================================

def _state_path(args):
    """Return state-file path: explicit flag wins, else auto-named from pubkey+start."""
    if getattr(args, 'state_file', None):
        return args.state_file
    pk  = args.pubkey[:12] if args.pubkey else 'unknown'
    rng = hex(args.start_range)[2:14]
    return f"bsgs_{pk}_{rng}.state"

def save_state(path, args, giant_offset, total_elapsed):
    """Persist current search position to JSON."""
    data = {
        'pubkey':        args.pubkey,
        'start_range':   hex(args.start_range),
        'end_range':     hex(args.end_range) if args.end_range else None,
        'm_size':        args.m_size,
        'workers':       args.workers,
        'giant_offset':  giant_offset,
        'total_elapsed': total_elapsed,
        'saved_at':      datetime.now().isoformat(),
    }
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)           # atomic replace — no corrupt state on power loss

def load_state(path):
    """Load saved state; returns dict or raises FileNotFoundError / ValueError."""
    with open(path) as f:
        d = json.load(f)
    # Only the fields shared by both linear and random-scan states are required here.
    # Mode-specific fields (giant_offset / attempt) are checked by the caller.
    required = ('pubkey', 'start_range', 'm_size', 'total_elapsed')
    for k in required:
        if k not in d:
            raise ValueError(f"State file missing key: {k}")
    return d

def delete_state(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

def _validate_resume(state, args):
    """Check that the loaded state matches the current CLI args. Abort on mismatch."""
    mismatches = []
    if state['pubkey'] != args.pubkey:
        mismatches.append(f"  pubkey:  saved={state['pubkey'][:16]}…  now={args.pubkey[:16]}…")
    if int(state['start_range'], 16) != args.start_range:
        mismatches.append(f"  start:   saved={state['start_range']}  now={hex(args.start_range)}")
    if state.get('m_size') != args.m_size:
        mismatches.append(f"  m_size:  saved={state['m_size']:,}  now={args.m_size:,}")
    if mismatches:
        print("[!] State file does not match current arguments:")
        for m in mismatches:
            print(m)
        print("    Delete the state file or match the original arguments to resume.\n")
        sys.exit(1)

# ============================================================================
# LIVE PROGRESS BAR
# ============================================================================

class ProgressBar:
    """
    Single-line live progress bar that updates in place.

    Call .update(keys) after each batch completes.
    Call .render() to force a refresh (called automatically from the
    map_async polling loop, so the bar updates every second).
    Call .clear() before printing a multi-line summary.
    Call .close() when the search ends.
    """

    BAR_FILL = '█'
    BAR_EMPTY = '░'
    SPEED_WINDOW = 8          # number of recent batches to average speed over

    def __init__(self, total_keys=None, workers=1):
        self.total_keys   = total_keys
        self.workers      = workers
        self.keys_done    = 0
        self.start_time   = time.time()
        self._samples     = []   # [(timestamp, keys_done), ...]
        self._last_render = 0.0
        self._active      = True
        self._last_len    = 0    # chars printed on last render (for clean erase)
        self.current_key  = None # current key being scanned (hex string)

    # ── public API ───────────────────────────────────────────────────────

    def update(self, new_keys):
        """Add newly scanned keys and record a speed sample."""
        self.keys_done += new_keys
        now = time.time()
        self._samples.append((now, self.keys_done))
        if len(self._samples) > self.SPEED_WINDOW:
            self._samples.pop(0)

    def set_key(self, key_hex):
        """Update the current key being scanned."""
        self.current_key = key_hex

    def render(self, force=False):
        """Render (or refresh) the progress line. Throttled to ~1/s unless force=True."""
        now = time.time()
        if not force and now - self._last_render < 0.9:
            return
        if not self._active:
            return
        self._last_render = now
        line = self._build_line()
        self._write(line)

    def clear(self):
        """Erase the progress line so a summary can be printed below it."""
        if self._last_len:
            sys.stdout.write('\r' + ' ' * self._last_len + '\r')
            sys.stdout.flush()
            self._last_len = 0

    def close(self):
        """Stop the bar and leave the cursor on a fresh line."""
        self._active = False
        self.clear()

    # ── internals ────────────────────────────────────────────────────────

    def _speed(self):
        """Rolling average speed (keys/s) over the last SPEED_WINDOW samples."""
        if len(self._samples) < 2:
            elapsed = time.time() - self.start_time
            return self.keys_done / elapsed if elapsed > 0 else 0
        t0, k0 = self._samples[0]
        t1, k1 = self._samples[-1]
        dt = t1 - t0
        return (k1 - k0) / dt if dt > 0 else 0

    def _fmt_speed(self, s):
        if s >= 1e12: return f"{s/1e12:.2f} Tkeys/s"
        if s >= 1e9:  return f"{s/1e9:.2f} Gkeys/s"
        if s >= 1e6:  return f"{s/1e6:.1f} Mkeys/s"
        return f"{s/1e3:.1f} Kkeys/s"

    def _fmt_time(self, sec):
        if sec is None:      return "?"
        if sec < 60:         return f"{sec:.0f}s"
        if sec < 3600:       return f"{sec/60:.1f}min"
        if sec < 86400:      return f"{sec/3600:.2f}hr"
        return f"{sec/86400:.1f}d"

    def _fmt_keys(self, k):
        if k >= 1e15: return f"{k/1e15:.3f} P"
        if k >= 1e12: return f"{k/1e12:.2f} T"
        if k >= 1e9:  return f"{k/1e9:.2f} G"
        if k >= 1e6:  return f"{k/1e6:.1f} M"
        return f"{k:,}"

    def _build_line(self):
        try:
            term_w = os.get_terminal_size().columns
        except Exception:
            term_w = 100
        term_w = max(term_w, 60)

        elapsed = time.time() - self.start_time
        speed   = self._speed()
        spd_str = self._fmt_speed(speed)
        ela_str = self._fmt_time(elapsed)
        scn_str = self._fmt_keys(self.keys_done)

        key_str = ""
        if self.current_key:
            key_str = f" │ key {self.current_key}"

        if self.total_keys and self.total_keys > 0:
            pct  = min(self.keys_done / self.total_keys * 100, 100.0)
            rem  = (self.total_keys - self.keys_done) / speed if speed > 0 else None
            eta  = self._fmt_time(rem)
            meta = f" {pct:5.2f}% │ {spd_str} │ {ela_str} elapsed │ ETA {eta} │ {scn_str}{key_str}"
        else:
            meta = f" {spd_str} │ {ela_str} elapsed │ {scn_str} scanned{key_str}"

        # Bar width = remaining terminal space after meta
        bar_w = max(term_w - len(meta) - 4, 8)

        if self.total_keys and self.total_keys > 0:
            filled = int(bar_w * pct / 100)
        else:
            # Spinner-style: animate a moving block for unbounded search
            pos    = int(elapsed * 4) % (bar_w * 2)
            filled = pos if pos < bar_w else bar_w * 2 - pos

        bar  = self.BAR_FILL * filled + self.BAR_EMPTY * (bar_w - filled)
        line = f"  [{bar}]{meta}"
        return line

    def _write(self, line):
        # Pad or trim to erase previous line fully
        prev = self._last_len
        if len(line) < prev:
            line = line + ' ' * (prev - len(line))
        sys.stdout.write('\r' + line)
        sys.stdout.flush()
        self._last_len = len(line)


# ============================================================================
# CPU BSGS SEARCH
# ============================================================================

def _affine_to_job_tuple(pt, neg_mG_x, neg_mG_y):
    """Return (x, y, is_inf, nmGx, nmGy) suitable for worker args."""
    if pt is None:
        return (0, 0, True, neg_mG_x, neg_mG_y)
    return (pt[0], pt[1], False, neg_mG_x, neg_mG_y)

def run_bsgs_cpu(args):
    workers     = args.workers or multiprocessing.cpu_count()
    m_size      = args.m_size
    start_range = args.start_range
    end_range   = args.end_range

    # ── Resume: load prior state if requested ─────────────────────────────
    resume_offset   = 0
    resume_elapsed  = 0.0
    state_path      = _state_path(args)

    if getattr(args, 'resume', False):
        try:
            state = load_state(state_path)
            if state.get('mode') == 'random':
                raise ValueError("State file is from a random scan — use -R to resume it.")
            _validate_resume(state, args)
            if 'giant_offset' not in state:
                raise ValueError("State file missing 'giant_offset'.")
            resume_offset  = state['giant_offset']
            resume_elapsed = state.get('total_elapsed', 0.0)
            saved_at       = state.get('saved_at', '?')
            print(f"[*] Resuming from state file: {state_path}")
            print(f"    Saved at      : {saved_at}")
            print(f"    Giant offset  : {resume_offset:,}")
            print(f"    Prior elapsed : {format_time(resume_elapsed)}")
            if end_range and resume_offset > 0:
                keys_done = resume_offset * m_size
                rng       = end_range - start_range
                pct       = min(keys_done / rng * 100, 100.0)
                print(f"    Coverage done : {pct:.4f}%")
            print()
        except FileNotFoundError:
            print(f"[!] No state file found at: {state_path}")
            print(f"    Starting from the beginning.\n")
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[!] Could not read state file ({exc}) — starting fresh.\n")

    print("=" * 80)
    print("  BSGS CPU - BITCOIN PRIVATE KEY SEARCH")
    print("=" * 80)
    print(f"  Public Key    : {args.pubkey[:20]}...{args.pubkey[-20:]}")
    print(f"  M_SIZE        : {m_size:,}")
    print(f"  CPU Workers   : {workers}")
    print(f"  Fast math     : {'gmpy2' if _HAVE_GMPY2 else 'built-in'}")
    print(f"  Start Range   : {hex(start_range)}")
    if end_range:
        print(f"  End Range     : {hex(end_range)}")
        print(f"  Total Keys    : {end_range - start_range:,}")
    if resume_offset:
        print(f"  Resuming from : giant step {resume_offset:,}  "
              f"(key {hex(start_range + resume_offset * m_size)})")
    print("=" * 80 + "\n")

    P_target = decompress_pubkey(args.pubkey)

    # ── Baby steps ────────────────────────────────────────────────────────
    baby_table = generate_baby_steps_cpu(m_size, verbose=True)
    print()

    # ── Derived EC points ─────────────────────────────────────────────────
    # Q = P_target − start_range·G   (giant step i=0 starting point)
    start_pt  = ec_mul(G, start_range)
    neg_start = (start_pt[0], (P - start_pt[1]) % P) if start_pt else None
    Q         = ec_add(P_target, neg_start) if neg_start else P_target

    # −M·G  (giant step increment)
    mG        = ec_mul(G, m_size)
    neg_mG    = (mG[0], (P - mG[1]) % P)
    neg_mG_x, neg_mG_y = neg_mG

    # −(chunk_size · M)·G  (inter-chunk advance, precomputed once)
    adv_scalar  = CPU_MINI_BATCH * m_size
    adv_pt      = ec_mul(G, adv_scalar)
    neg_advance = (adv_pt[0], (P - adv_pt[1]) % P)

    # Max giant steps
    if end_range:
        max_giant = (end_range - start_range + m_size - 1) // m_size
    else:
        max_giant = None

    # ── Quick check: key == start_range? ─────────────────────────────────
    if Q is None:
        print(f"[*] Key found immediately at start of range!\n")
        print_found(start_range, P_target, args, time.time())
        return True

    range_size = (end_range - start_range) if end_range else None

    print(f"[*] Starting giant-step search with {workers} workers...")
    print(f"    Chunk size : {CPU_MINI_BATCH:,} giant steps × {m_size:,} M = "
          f"{CPU_MINI_BATCH * m_size / 1e6:.1f} M keys per chunk")
    print(f"    Baby table : O(1) Python dict")
    if range_size:
        print(f"    Total keys : {range_size:,}")
    print()
    print("─" * 80 + "\n")

    DISPATCH_CHUNKS = max(workers * 4, 16)
    AUTOSAVE_EVERY  = 100          # batches between automatic state saves

    # ── Fast-forward outer_pt to resume position ──────────────────────────
    outer_pt = Q
    if resume_offset > 0:
        print(f"[*] Fast-forwarding EC point to offset {resume_offset:,}...")
        fwd_pt   = ec_mul(G, resume_offset * m_size)
        neg_fwd  = (fwd_pt[0], (P - fwd_pt[1]) % P)
        outer_pt = ec_add(Q, neg_fwd)
        print(f"    Done.\n")

    # total_start is set so that time.time()-total_start gives *session* elapsed,
    # while resume_elapsed holds the accumulated prior time across sessions.
    total_start  = time.time()
    giant_offset = resume_offset
    batch_num    = 0
    false_pos    = 0

    # Live progress bar — pre-seed with keys already covered in prior sessions
    bar = ProgressBar(total_keys=range_size, workers=workers)
    if resume_offset > 0:
        bar.update(resume_offset * m_size)   # seed the speed samples baseline
        # Shift start_time back so elapsed = resume_elapsed + session_time
        bar.start_time = time.time() - resume_elapsed

    # Convert SIGTERM → KeyboardInterrupt so state is saved on kill/timeout
    def _sigterm_handler(signo, frame):
        raise KeyboardInterrupt

    _orig_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        ctx = multiprocessing.get_context('fork')
        with ctx.Pool(
            processes=workers,
            initializer=_worker_init,
            initargs=(baby_table, m_size, start_range),
        ) as pool:

            while True:
                if max_giant is not None and giant_offset >= max_giant:
                    bar.close()
                    print(f"\n[*] Full range searched — key not found.")
                    return False

                batch_num += 1

                # How many chunks this dispatch?
                if max_giant is not None:
                    rem_giants = max_giant - giant_offset
                    n_chunks = min(DISPATCH_CHUNKS,
                                   (rem_giants + CPU_MINI_BATCH - 1) // CPU_MINI_BATCH)
                else:
                    n_chunks = DISPATCH_CHUNKS

                # Build job list; advance outer_pt chunk-by-chunk
                jobs = []
                pt   = outer_pt
                for c in range(n_chunks):
                    i_s = giant_offset + c * CPU_MINI_BATCH
                    i_e = i_s + CPU_MINI_BATCH
                    if max_giant is not None:
                        i_e = min(i_e, max_giant)
                    if i_s >= (max_giant if max_giant else i_e + 1):
                        break
                    bx, by, binf, nmx, nmy = _affine_to_job_tuple(pt, neg_mG_x, neg_mG_y)
                    jobs.append((i_s, i_e, bx, by, binf, nmx, nmy))
                    pt = neg_advance if pt is None else ec_add(pt, neg_advance)

                # ── Dispatch + live-update loop ───────────────────────────
                t_batch      = time.time()
                async_result = pool.map_async(_giant_step_chunk, jobs)

                while True:
                    try:
                        results = async_result.get(timeout=0.25)
                        break
                    except multiprocessing.TimeoutError:
                        bar.render()   # updates at most once per second

                batch_time = time.time() - t_batch

                # ── Process results ───────────────────────────────────────
                found_key = None
                for res in results:
                    if res is not None and found_key is None:
                        i_found, j_found = res
                        k = verify_and_build_result(
                            i_found, j_found, start_range, m_size, P_target, args)
                        if k:
                            found_key = k
                        else:
                            false_pos += 1
                            bar.clear()
                            print(f"  [!] False positive #{false_pos} "
                                  f"at i={i_found} j={j_found} — continuing...")

                if found_key:
                    pool.terminate()
                    bar.close()
                    delete_state(state_path)   # key found — no reason to resume
                    print_found(found_key, P_target, args, total_start)
                    return True

                # ── Advance outer_pt ──────────────────────────────────────
                actual_chunks   = len(jobs)
                new_offset      = giant_offset + actual_chunks * CPU_MINI_BATCH
                keys_this_batch = actual_chunks * CPU_MINI_BATCH * m_size
                keys_covered    = new_offset * m_size
                elapsed         = time.time() - total_start

                for _ in range(actual_chunks):
                    outer_pt = neg_advance if outer_pt is None else ec_add(outer_pt, neg_advance)

                # Update progress bar data
                cur_hex = hex(start_range + giant_offset * m_size)
                bar.update(keys_this_batch)
                bar.set_key(cur_hex)

                # ── Periodic summary (every 10 batches or first batch) ────
                SUMMARY_EVERY = 10
                if batch_num == 1 or batch_num % SUMMARY_EVERY == 0:
                    speed = keys_this_batch / batch_time if batch_time > 0 else 0
                    bar.clear()
                    summary = (f"  Batch #{batch_num:>5}  │  "
                               f"{bar._fmt_speed(speed):>14}  │  "
                               f"{format_time(elapsed):>8} elapsed")
                    if range_size:
                        pct = min(keys_covered / range_size * 100, 100.0)
                        rem = (range_size - keys_covered) / speed if speed > 0 else None
                        eta_s = format_time(rem) if rem else "?"
                        summary += f"  │  {pct:6.2f}%  │  ETA {eta_s}"
                    print(summary)
                    print(f"  Current Key : {cur_hex}")
                    if false_pos:
                        print(f"    False positives so far: {false_pos}")

                # Force bar render after summary
                bar.render(force=True)

                giant_offset = new_offset

                # ── Periodic auto-save ────────────────────────────────────
                if batch_num % AUTOSAVE_EVERY == 0:
                    total_elapsed_acc = resume_elapsed + (time.time() - total_start)
                    save_state(state_path, args, giant_offset, total_elapsed_acc)

    except KeyboardInterrupt:
        global _INTERRUPTED
        _INTERRUPTED = True
        bar.close()
        session_time      = time.time() - total_start
        total_elapsed_acc = resume_elapsed + session_time
        keys_scanned      = giant_offset * m_size

        in_random_mode = bool(getattr(args, 'random_scan', None))

        if in_random_mode:
            # Random-scan wrapper handles its own state; just report the attempt interruption
            print(f"\n\n[!] Attempt interrupted after {format_time(session_time)}"
                  f"  ({keys_scanned:,} keys scanned this attempt)")
        else:
            # Linear search — save full resume state
            save_state(state_path, args, giant_offset, total_elapsed_acc)
            print(f"\n\n[!] Search interrupted — progress saved to: {state_path}")
            print(f"    Session time  : {format_time(session_time)}")
            print(f"    Total elapsed : {format_time(total_elapsed_acc)}")
            print(f"    Giant steps   : {giant_offset:,}")
            print(f"    Keys scanned  : {keys_scanned:,}")
            if range_size and keys_scanned > 0:
                print(f"    Coverage      : {keys_scanned / range_size * 100:.4f}%")
            print(f"\n  Resume with:")
            print(f"    python3 bsgs_scan.py --cpu --resume \\")
            print(f"      -p {args.pubkey} \\")
            print(f"      -s {hex(start_range)} -e {hex(end_range) if end_range else '?'} \\")
            print(f"      -m {m_size} --workers {workers}")
            print()

    finally:
        signal.signal(signal.SIGTERM, _orig_sigterm)

    return False

# ============================================================================
# GPU BABY STEPS GENERATION
# ============================================================================

def point_to_u64_array(point):
    x, y = point
    x_arr = np.array([(x >> (64 * i)) & 0xFFFFFFFFFFFFFFFF for i in range(4)], dtype=np.uint64)
    y_arr = np.array([(y >> (64 * i)) & 0xFFFFFFFFFFFFFFFF for i in range(4)], dtype=np.uint64)
    return x_arr, y_arr

def generate_baby_steps_gpu(m_size, module, config):
    print(f"[*] Generating {m_size:,} baby steps on GPU...")
    kernel  = module.get_function('generate_baby_steps_gpu')
    d_table = cp.zeros(m_size * 2, dtype=np.uint64)
    total   = 0
    t0      = time.time()
    while total < m_size:
        batch = min(config['baby_batch'], m_size - total)
        kernel(
            (config['baby_blocks'],), (config['baby_threads'],),
            (d_table, cp.uint32(m_size), cp.uint32(total), cp.uint32(batch))
        )
        cp.cuda.Stream.null.synchronize()
        total += batch
        if batch >= 10000:
            print(f"\r    [{total:,}/{m_size:,}] {total/(time.time()-t0)/1000:.0f} Kpts/s",
                  end='', flush=True)
    print(f"\r    Done: {m_size:,} in {time.time()-t0:.1f}s" + " " * 20)
    return d_table

# ============================================================================
# GPU ARCHITECTURE DETECTION
# ============================================================================

def detect_gpu_architecture():
    try:
        device = cp.cuda.Device(0)
        props  = cp.cuda.runtime.getDeviceProperties(device.id)
        cc     = f"{props['major']}{props['minor']}"
        arch_map = {'75': 'sm75', '80': 'sm80', '86': 'sm86', '89': 'sm89', '90': 'sm90'}
        arch = arch_map.get(cc, 'sm86')
        return f"bsgs_scan_{arch}.fatbin"
    except Exception:
        return "bsgs.fatbin"

# ============================================================================
# GPU BSGS SEARCH
# ============================================================================

def run_bsgs_gpu(args):
    config = {
        'baby_blocks':   args.baby_blocks,
        'baby_threads':  args.baby_threads,
        'baby_batch':    args.baby_batch,
        'search_blocks': args.search_blocks,
        'search_threads':args.search_threads,
        'giant_batch':   args.giant_batch,
    }

    print("=" * 80)
    print("  Rukka BSGS GPU - BITCOIN PRIVATE KEY SEARCH")
    print("=" * 80)
    print(f"  Public Key      : {args.pubkey[:20]}...{args.pubkey[-20:]}")
    print(f"  M_SIZE          : {args.m_size:,}")
    print(f"  Baby gen batch  : {config['baby_batch']:,}")
    print(f"  Giant batch     : {config['giant_batch']:,}")
    print(f"\n  Search Range:")
    print(f"    Start         : {hex(args.start_range)}")
    if args.end_range:
        print(f"    End           : {hex(args.end_range)}")
        print(f"    Total         : {args.end_range - args.start_range:,} keys")
    else:
        print(f"    Mode          : Continuous (until found)")
    print(f"\n  GPU Configuration:")
    print(f"    Baby  : {config['baby_blocks']} blocks x {config['baby_threads']} threads")
    print(f"    Search: {config['search_blocks']} blocks x {config['search_threads']} threads")
    print("=" * 80 + "\n")

    gpu_device = args.kernel if args.kernel else detect_gpu_architecture()
    print(f"[*] GPU Kernel: {gpu_device}")
    print(f"[*] Loading kernel...")
    if not os.path.exists(gpu_device):
        print(f"[!] {gpu_device} not found!")
        sys.exit(1)

    module       = cp.RawModule(path=gpu_device)
    print(f"    Kernel loaded\n")
    d_baby_table = generate_baby_steps_gpu(args.m_size, module, config)

    print(f"[*] Preparing search...")
    P_target  = decompress_pubkey(args.pubkey)
    start_pt  = ec_mul(G, args.start_range)
    neg_start = (start_pt[0], (P - start_pt[1]) % P)
    P_base    = ec_add(P_target, neg_start)
    mG        = ec_mul(G, args.m_size)
    neg_mG    = (mG[0], (P - mG[1]) % P)
    print(f"    Setup complete\n")

    search_kernel = module.get_function('bsgs_batch_precomputed')
    giant_kernel  = module.get_function('generate_giant_steps_gpu')
    d_result      = cp.zeros(4, dtype=cp.uint64)
    neg_mG_x, neg_mG_y = point_to_u64_array(neg_mG)
    d_neg_mG_x = cp.asarray(neg_mG_x)
    d_neg_mG_y = cp.asarray(neg_mG_y)

    batch_jump_scalar = config['giant_batch'] * args.m_size
    batch_jump        = ec_mul(G, batch_jump_scalar)
    neg_batch_jump    = (batch_jump[0], (P - batch_jump[1]) % P)

    print(f"[*] Starting search...\n")
    print("─" * 80 + "\n")

    giant_offset  = 0
    current_base  = P_base
    batch_num     = 0
    false_positives = 0
    total_start   = time.time()

    try:
        while True:
            batch_num += 1
            current_start = args.start_range + (giant_offset * args.m_size)
            current_end   = args.start_range + ((giant_offset + config['giant_batch']) * args.m_size)

            if args.end_range and current_start >= args.end_range:
                print(f"\n[*] Complete range searched without finding key.")
                break

            print(f"\n{'='*80}")
            print(f"[BATCH #{batch_num}]")
            print(f"{'='*80}")
            print(f"  Giant steps     : {giant_offset:,} → {giant_offset+config['giant_batch']:,}")
            print(f"  Current range   : {hex(current_start)} → {hex(current_end)}")
            if args.end_range:
                progress = (current_start - args.start_range) / (args.end_range - args.start_range) * 100
                print(f"  Progress        : {progress:.2f}%")
            print(f"{'─'*80}")

            base_x, base_y = point_to_u64_array(current_base)
            d_base_x = cp.asarray(base_x)
            d_base_y = cp.asarray(base_y)
            d_x_coords = cp.zeros(config['giant_batch'], dtype=np.uint64)

            print(f"    Generating giant steps on GPU...", end='', flush=True)
            t0 = time.time()
            giant_kernel(
                (config['search_blocks'],), (config['search_threads'],),
                (d_x_coords, d_base_x, d_base_y,
                 d_neg_mG_x, d_neg_mG_y, cp.uint32(config['giant_batch']))
            )
            cp.cuda.Stream.null.synchronize()
            giant_time = time.time() - t0
            print(f"\r    Giant steps: {giant_time:.2f}s | {config['giant_batch']/giant_time/1e6:.2f} Mpts/s" + " " * 10)

            print(f"    Searching in hash table...", end='', flush=True)
            d_result.fill(0)
            t0 = time.time()
            search_kernel(
                (config['search_blocks'],), (config['search_threads'],),
                (d_baby_table, cp.uint32(args.m_size),
                 d_x_coords, cp.uint32(config['giant_batch']),
                 cp.uint32(giant_offset), d_result)
            )
            cp.cuda.Stream.null.synchronize()
            search_time = time.time() - t0
            print(f"\r    Search: {search_time:.2f}s" + " " * 30)

            result = d_result.get()
            if result[2] == 1:
                baby_idx  = int(result[1])
                giant_idx = int(result[0])
                final_key = args.start_range + (giant_idx * args.m_size) + baby_idx
                test_point = ec_mul(G, final_key)
                if test_point == P_target:
                    print_found(final_key, P_target, args, total_start)
                    return True
                else:
                    false_positives += 1
                    print(f"\n  [!] False positive #{false_positives} — continuing...")

            total_batch_time = giant_time + search_time
            batch_keys   = config['giant_batch'] * args.m_size
            elapsed      = time.time() - total_start
            total_giants = giant_offset + config['giant_batch']
            covered      = total_giants * args.m_size

            print(f"\n  Batch time  : {total_batch_time:.2f}s")
            print(f"  Batch speed : {batch_keys/total_batch_time/1e9:.2f} GKey/s")
            print(f"  Total time  : {format_time(elapsed)}")
            print(f"  Keys covered: {covered:,}")
            if false_positives:
                print(f"  False pos   : {false_positives}")
            print(f"{'='*80}\n")

            giant_offset  += config['giant_batch']
            current_base   = ec_add(current_base, neg_batch_jump)

    except KeyboardInterrupt:
        print(f"\n[!] Interrupted by user\n")

    elapsed = time.time() - total_start
    print(f"  Total time: {format_time(elapsed)}\n")
    return False

# ============================================================================
# BENCHMARK / CALIBRATION
# ============================================================================

def _bench_giant_chunk(args):
    """Minimal worker for benchmarking giant step throughput."""
    return _giant_step_chunk(args)

def run_benchmark(args):
    """
    Three-phase CPU calibration:
      1. Baby step generation rate vs M_SIZE
      2. Giant step throughput vs chunk size (parallel)
      3. Optimal M_SIZE based on total projected time

    Returns (best_m, best_chunk) — or (None, None) if no range given.
    """
    import math

    workers     = args.workers or multiprocessing.cpu_count()
    start_range = args.start_range
    end_range   = args.end_range
    range_size  = (end_range - start_range) if end_range else None

    W = 70
    print("=" * W)
    print("  BSGS CPU BENCHMARK & CALIBRATION")
    print("=" * W)
    print(f"  CPU cores   : {multiprocessing.cpu_count()}")
    print(f"  Workers     : {workers}")
    print(f"  Fast math   : {'gmpy2' if _HAVE_GMPY2 else 'built-in (install gmpy2 for ~10% boost)'}")
    if range_size:
        print(f"  Range size  : {range_size:,} keys")
        sq = int(math.isqrt(range_size))
        print(f"  √(range)    : {sq:,}  (theoretical ideal M_SIZE)")
    print("=" * W)

    # ── Phase 1: baby step rate ───────────────────────────────────────────
    print("\n  Phase 1 — Baby step generation speed")
    print("  " + "─" * (W - 2))

    test_ms   = [2**k for k in range(12, 21, 2)]   # 4K, 16K, 64K, 256K, 1M
    baby_rate_sum = 0
    baby_rate_count = 0

    for m in test_ms:
        t0 = time.time()
        _ = generate_baby_steps_cpu(m, verbose=False)
        dt = max(time.time() - t0, 1e-9)
        rate = m / dt
        baby_rate_sum   += rate
        baby_rate_count += 1
        print(f"    M={m:>9,}  build={dt:.2f}s  rate={rate/1000:.0f} Kpts/s")

    avg_baby_rate = baby_rate_sum / baby_rate_count
    print(f"\n    Average baby step rate: {avg_baby_rate/1000:.0f} Kpts/s")

    # ── Phase 2: giant step throughput ───────────────────────────────────
    print(f"\n  Phase 2 — Giant step throughput ({workers} workers)")
    print("  " + "─" * (W - 2))

    bench_m   = 2**14        # small table for speed test
    bench_tbl = generate_baby_steps_cpu(bench_m, verbose=False)

    # EC setup — use a dummy starting point
    probe_pt  = ec_mul(G, start_range + 999_983)  # arbitrary affine point
    mG_bench  = ec_mul(G, bench_m)
    neg_mG_b  = (mG_bench[0], (P - mG_bench[1]) % P)
    nmGx, nmGy = neg_mG_b

    best_chunk = CPU_MINI_BATCH
    best_speed = 0.0
    chunk_results = {}

    ctx = multiprocessing.get_context('fork')

    for chunk in [500, 1000, 2000, 4000, 8000]:
        n_jobs = workers * 4
        adv    = ec_mul(G, chunk * bench_m)
        neg_adv = (adv[0], (P - adv[1]) % P)

        pt   = probe_pt
        jobs = []
        for j in range(n_jobs):
            bx  = pt[0] if pt else 0
            by  = pt[1] if pt else 0
            inf = pt is None
            jobs.append((j * chunk, (j + 1) * chunk, bx, by, inf, nmGx, nmGy))
            pt = ec_add(pt, neg_adv) if pt else neg_adv

        with ctx.Pool(
            processes=workers,
            initializer=_worker_init,
            initargs=(bench_tbl, bench_m, start_range),
        ) as pool:
            t0 = time.time()
            pool.map(_bench_giant_chunk, jobs)
            dt = max(time.time() - t0, 1e-9)

        total_keys = n_jobs * chunk * bench_m
        speed      = total_keys / dt / 1e9
        chunk_results[chunk] = speed

        marker = ""
        if speed > best_speed:
            best_speed = speed
            best_chunk = chunk
            marker     = "  ◄"
        print(f"    chunk={chunk:>5}  time={dt:.2f}s  speed={speed:.2f} Gkeys/s{marker}")

    print(f"\n    Best chunk size: {best_chunk}  →  {best_speed:.2f} Gkeys/s")

    # ── Phase 3: optimal M_SIZE ───────────────────────────────────────────
    print(f"\n  Phase 3 — Optimal M_SIZE analysis")
    print("  " + "─" * (W - 2))

    speed_kps = best_speed * 1e9   # keys per second

    # Pool dispatch overhead per chunk (empirical: ~1–3 ms per subprocess round-trip)
    # We scale the effective giant-step speed by: effective = pure / (1 + overhead/compute)
    # With chunk=best_chunk and bench_m=2^14:
    #   compute_time ≈ best_chunk * bench_m / speed_kps
    #   overhead     ≈ 0.0015 s (measured ~1.5ms per chunk round-trip)
    POOL_OVERHEAD_PER_CHUNK_S = 0.002   # conservative estimate

    def effective_speed(m):
        """Effective keys/s accounting for pool dispatch overhead."""
        compute_s   = best_chunk * m / speed_kps
        overhead_s  = POOL_OVERHEAD_PER_CHUNK_S
        efficiency  = compute_s / (compute_s + overhead_s)
        return speed_kps * efficiency

    # Minimum practical M: pool overhead < 20% of compute time
    min_practical_m = int(POOL_OVERHEAD_PER_CHUNK_S * speed_kps / best_chunk / 0.20)
    min_practical_m = max(min_practical_m, 1024)

    # Estimate available RAM for baby table (each Python dict entry ≈ 200 bytes)
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
        avail = soft if soft > 0 else hard
        max_m_ram = min(4 * 1024 * 1024, avail // 200) if avail > 0 else 4 * 1024 * 1024
    except Exception:
        max_m_ram = 4 * 1024 * 1024

    candidate_ms = [2**k for k in range(10, 23)]   # 1K → 4M

    best_m     = None
    best_total = None
    rows       = []

    for m in candidate_ms:
        if m > max_m_ram:
            break
        baby_time = m / avg_baby_rate
        if range_size:
            eff_speed   = effective_speed(m)
            giant_steps = (range_size + m - 1) // m
            giant_time  = (giant_steps * m) / eff_speed
            total_time  = baby_time + giant_time
            too_small   = m < min_practical_m
            is_best     = (not too_small) and (best_total is None or total_time < best_total)
            if is_best:
                best_total = total_time
                best_m     = m
            rows.append((m, baby_time, giant_steps, total_time, is_best, too_small))
        else:
            rows.append((m, baby_time, None, None, False, m < min_practical_m))

    def fmt_time_precise(s):
        if s is None: return "─"
        if s < 60:    return f"{s:.1f}s"
        if s < 3600:  return f"{s/60:.1f}min"
        if s < 86400: return f"{s/3600:.2f}hr"
        return f"{s/86400:.1f}d"

    header = f"    {'M_SIZE':>10}  {'Baby build':>10}  {'Giant steps':>13}  {'Est. total':>12}  Note"
    print(header)
    print("    " + "─" * (len(header) - 2))
    for row in rows:
        m, bt, gs, tt, best, small = row
        gs_s   = f"{gs:>13,}" if gs is not None else f"{'(no range)':>13}"
        tt_s   = f"{fmt_time_precise(tt):>12}" if tt is not None else f"{'─':>12}"
        flag   = "  ◄ BEST" if best else ""
        note   = "pool overhead dominant" if small else ""
        print(f"    {m:>10,}  {fmt_time_precise(bt):>10}  {gs_s}  {tt_s}{flag}  {note}")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("=" * W)
    print("  BENCHMARK SUMMARY")
    print("=" * W)
    print(f"  Giant step speed     : {best_speed:.2f} Gkeys/s  ({workers} workers)")
    print(f"  Baby step rate       : {avg_baby_rate/1000:.0f} Kpts/s")
    print(f"  Optimal chunk size   : {best_chunk}")
    print(f"  Min practical M_SIZE : {min_practical_m:,}  (pool overhead <20% of compute)")

    if best_m and range_size:
        print(f"  Optimal M_SIZE       : {best_m:,}")
        print(f"  Estimated time       : {fmt_time_precise(best_total)}")

    if args.pubkey and best_m and range_size:
        print()
        print("  Recommended command:")
        e_flag = f"-e {hex(end_range)} " if end_range else ""
        print(f"    python3 bsgs_scan.py --cpu -m {best_m} --workers {workers} \\")
        print(f"      -p {args.pubkey} \\")
        print(f"      -s {hex(start_range)} {e_flag}-o result.txt")
    elif best_m and range_size:
        print()
        print("  To run with optimal settings, add -p <pubkey>:")
        e_flag = f"-e {hex(end_range)} " if end_range else ""
        print(f"    python3 bsgs_scan.py --cpu -m {best_m} --workers {workers} \\")
        print(f"      -p <pubkey> -s {hex(start_range)} {e_flag}-o result.txt")

    print("=" * W)
    return best_m, best_chunk


# ============================================================================
# COMMAND LINE ARGUMENTS
# ============================================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='BSGS - Bitcoin Private Key Search (GPU + CPU)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # CPU search (auto-selects all cores):
  python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff --cpu

  # CPU with custom worker count:
  python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff --cpu --workers 4

  # GPU search (requires CUDA GPU):
  python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff

  # Random scan mode:
  python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 --cpu

  # Larger M_SIZE for better performance (uses more RAM):
  python bsgs_scan.py -p 03f46f... --m-size 4194304 --cpu

  # Save result to file:
  python bsgs_scan.py -p 03f46f... --cpu -o result.txt

  # Calibrate this machine and show optimal settings:
  python bsgs_scan.py --benchmark -s 0x2000000000000 -e 0x3ffffffffffff

  # Calibrate then auto-run with optimal settings:
  python bsgs_scan.py --benchmark --run -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff
        '''
    )

    parser.add_argument('-p', '--pubkey', type=str, default=None,
                        help='Compressed public key (hex, 66 chars). Required for search.')
    parser.add_argument('-s', '--start-range', type=lambda x: int(x, 0),
                        default=DEFAULT_START,
                        help=f'Start range (hex or decimal, default: {hex(DEFAULT_START)})')
    parser.add_argument('-e', '--end-range', type=lambda x: int(x, 0),
                        default=None,
                        help='End range (optional)')
    parser.add_argument('-R', '--random-scan', type=float, default=None,
                        metavar='TKEYS',
                        help='Random scan: pick random start and scan X TKeys per attempt')
    parser.add_argument('-m', '--m-size', type=int, default=None,
                        help=f'Baby-step table size (default: {DEFAULT_M_SIZE:,} CPU / {DEFAULT_M_SIZE_GPU:,} GPU)')

    # Backend selection
    parser.add_argument('--cpu', action='store_true',
                        help='Force CPU mode (default: auto-detect GPU)')
    parser.add_argument('--workers', type=int, default=None,
                        help='Number of CPU worker processes (default: all cores)')

    # GPU config
    parser.add_argument('--baby-blocks',   type=int, default=DEFAULT_BABY_GEN_BLOCKS)
    parser.add_argument('--baby-threads',  type=int, default=DEFAULT_BABY_GEN_THREADS)
    parser.add_argument('--baby-batch',    type=int, default=DEFAULT_BABY_BATCH)
    parser.add_argument('--search-blocks', type=int, default=DEFAULT_SEARCH_BLOCKS)
    parser.add_argument('--search-threads',type=int, default=DEFAULT_SEARCH_THREADS)
    parser.add_argument('--giant-batch',   type=int, default=DEFAULT_GIANT_BATCH)
    parser.add_argument('-k', '--kernel',  type=str, default=None,
                        help='Custom CUDA kernel (.fatbin)')
    parser.add_argument('-o', '--output',  type=str, default=None,
                        help='Output file for found key')
    parser.add_argument('-v', '--verbose', action='store_true')

    # Benchmark / calibration
    parser.add_argument('--benchmark', action='store_true',
                        help='Calibrate this CPU: measure baby+giant step speeds, '
                             'find optimal M_SIZE, show time-to-completion projection')
    parser.add_argument('--run', action='store_true',
                        help='After --benchmark, automatically run the search with '
                             'the recommended settings (requires -p, -s, -e)')

    # Resume / state
    parser.add_argument('--resume', action='store_true',
                        help='Resume a previously interrupted CPU search from its saved state file')
    parser.add_argument('--state-file', type=str, default=None, metavar='FILE',
                        help='Path to state file (default: auto-named from pubkey+start)')

    # Random scan options
    parser.add_argument('--seed', type=int, default=None,
                        help='RNG seed for -R random scan (default: random). '
                             'Use different seeds on different machines to avoid overlap.')

    return parser.parse_args()

# ============================================================================
# RANDOM SCAN WRAPPER
# ============================================================================

def run_random_scan(args, search_fn):
    original_start = args.start_range
    original_end   = args.end_range if args.end_range else (
        (1 << (args.start_range.bit_length() + 1)) - 1)
    scan_size     = int(args.random_scan * 1_000_000_000_000)
    range_size    = original_end - original_start
    max_rnd_start = original_end - scan_size

    if max_rnd_start <= original_start:
        print(f"[!] Random scan size ({args.random_scan} TKeys) is too large for the range.")
        sys.exit(1)

    # ── Seed ──────────────────────────────────────────────────────────────
    seed = getattr(args, 'seed', None)
    if seed is None:
        seed = _rnd.randrange(0, 2**32)
    rng = _rnd.Random(seed)

    # ── State path for random mode ─────────────────────────────────────────
    if getattr(args, 'state_file', None):
        state_path = args.state_file
    else:
        pk  = args.pubkey[:12]
        rng_hex = hex(original_start)[2:10]
        state_path = f"bsgs_rand_{pk}_{rng_hex}_s{seed}.state"

    # ── Coverage helpers ──────────────────────────────────────────────────
    p = min(scan_size / range_size, 1.0)

    def attempts_for(target):
        if p >= 1.0: return 1
        log1mp = math.log1p(-p) if p < 1.0 else -math.inf
        if log1mp == 0:
            return math.ceil(-math.log(1.0 - target) / p)
        return math.ceil(math.log1p(-target) / log1mp)

    def coverage_after(n):
        return (1.0 - (1.0 - p) ** n) * 100.0

    n_50 = attempts_for(0.50)
    n_95 = attempts_for(0.95)
    n_99 = attempts_for(0.99)

    # ── Resume ────────────────────────────────────────────────────────────
    resume_attempt = 0
    resume_elapsed = 0.0

    if getattr(args, 'resume', False):
        try:
            state = load_state(state_path)
            if state.get('mode') != 'random':
                print("[!] State file is not a random-scan state — starting fresh.\n")
            elif state.get('seed') != seed:
                print(f"[!] State seed ({state.get('seed')}) ≠ --seed ({seed}) — starting fresh.\n")
            else:
                _validate_resume(state, args)
                resume_attempt = state['attempt']
                resume_elapsed = state.get('total_elapsed', 0.0)
                # Replay RNG so we pick up from exactly the right position
                for _ in range(resume_attempt):
                    rng.randint(original_start, max_rnd_start)
                print(f"[*] Resuming random scan (seed={seed}) from attempt #{resume_attempt + 1}")
                print(f"    Prior time  : {format_time(resume_elapsed)}")
                print(f"    Coverage    : {coverage_after(resume_attempt):.4f}%\n")
        except FileNotFoundError:
            print(f"[!] No state file found ({state_path}) — starting fresh.\n")
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[!] Could not read state file ({exc}) — starting fresh.\n")

    # ── Header ────────────────────────────────────────────────────────────
    print(f"{'='*80}")
    print(f"  CONTINUOUS RANDOM SCAN  (seed={seed})")
    print(f"{'='*80}")
    print(f"  Public Key   : {args.pubkey[:20]}...{args.pubkey[-20:]}")
    print(f"  Range        : {hex(original_start)} → {hex(original_end)}")
    print(f"  Range size   : {range_size:,}")
    print(f"  Scan / attempt: {args.random_scan} TKeys = {scan_size:,}")
    print(f"  Seed         : {seed}  ← save this to resume or run in parallel")
    print(f"  p per attempt: {p*100:.4f}%")
    print(f"  50% coverage : ~{n_50:,} attempts")
    print(f"  95% coverage : ~{n_95:,} attempts")
    print(f"  99% coverage : ~{n_99:,} attempts")
    print(f"{'─'*80}")
    print(f"  Multi-machine: run on other machines with different --seed values to avoid overlap")
    for s in [seed + 1, seed + 2, seed + 3]:
        print(f"    --seed {s}  → completely independent random sequence")
    print(f"  State file   : {state_path}")
    print(f"  Ctrl+C stops and saves progress; --resume continues")
    print(f"{'='*80}\n")

    # ── State-save helper ─────────────────────────────────────────────────
    def _save_rnd_state(att, elapsed_total):
        data = {
            'mode':          'random',
            'pubkey':        args.pubkey,
            'start_range':   hex(original_start),
            'end_range':     hex(original_end),
            'm_size':        args.m_size,
            'workers':       getattr(args, 'workers', None),
            'scan_tkeys':    args.random_scan,
            'seed':          seed,
            'attempt':       att,
            'total_elapsed': elapsed_total,
            'saved_at':      datetime.now().isoformat(),
        }
        tmp = state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, state_path)

    # ── Main loop ─────────────────────────────────────────────────────────
    attempt      = resume_attempt
    global_start = time.time()

    try:
        while True:
            global _INTERRUPTED
            _INTERRUPTED = False        # reset before each attempt

            attempt += 1
            rnd_start = rng.randint(original_start, max_rnd_start)
            rnd_end   = min(rnd_start + scan_size, original_end)
            cov       = coverage_after(attempt)

            print(f"\n{'╔'+'═'*78+'╗'}")
            att_label = f"ATTEMPT #{attempt}  (seed={seed})"
            print(f"║  {att_label:<76}  ║")
            print(f"{'╚'+'═'*78+'╝'}")
            print(f"  Start      : {hex(rnd_start)}")
            print(f"  End        : {hex(rnd_end)}")
            print(f"  Coverage   : {cov:.4f}%  after {attempt} attempt(s)")
            n_left_50 = max(n_50 - attempt, 0)
            n_left_95 = max(n_95 - attempt, 0)
            print(f"  To 50%/95% : ~{n_left_50:,} / ~{n_left_95:,} more attempts")
            print()

            args.start_range = rnd_start
            args.end_range   = rnd_end

            t0    = time.time()
            found = search_fn(args)
            t_att = time.time() - t0
            total_elapsed = resume_elapsed + (time.time() - global_start)

            if found:
                delete_state(state_path)
                print(f"\n  KEY FOUND in attempt #{attempt}!  (seed={seed})")
                break

            # Attempt interrupted mid-way by Ctrl+C / SIGTERM
            if _INTERRUPTED:
                _save_rnd_state(attempt - 1, total_elapsed)
                print(f"\n  Random scan paused — state saved to: {state_path}")
                print(f"  Last completed attempt : #{attempt - 1}")
                print(f"  Coverage               : {coverage_after(max(attempt-1,0)):.4f}%")
                print(f"  Total elapsed          : {format_time(total_elapsed)}")
                print(f"\n  Resume with:")
                print(f"    python3 bsgs_scan.py --cpu --resume --seed {seed} -R {args.random_scan} \\")
                print(f"      -p {args.pubkey} \\")
                print(f"      -s {hex(original_start)} -e {hex(original_end)} \\")
                print(f"      -m {args.m_size} --workers {getattr(args,'workers',1)}")
                print()
                break

            print(f"\n  Attempt #{attempt}: not found | {format_time(t_att)} | "
                  f"total elapsed {format_time(total_elapsed)}")

            # Save state after every completed attempt (atomic write)
            _save_rnd_state(attempt, total_elapsed)
            print(f"  [State saved → {state_path}]")

            # Speed estimate for remaining attempts
            session_s = time.time() - global_start
            if session_s > 0 and attempt > resume_attempt:
                secs_per_att = session_s / (attempt - resume_attempt)
                print(f"  Speed: ~{format_time(secs_per_att)}/attempt  "
                      f"| 50% coverage ETA: {format_time(secs_per_att * n_left_50)}"
                      f"  | 99%: {format_time(secs_per_att * max(n_99-attempt,0))}")

    except KeyboardInterrupt:
        total_elapsed = resume_elapsed + (time.time() - global_start)
        # Ctrl+C pressed between attempts (not inside search_fn)
        _save_rnd_state(attempt, total_elapsed)
        cov = coverage_after(attempt)
        print(f"\n\n  Random scan paused — state saved to: {state_path}")
        print(f"  Seed        : {seed}")
        print(f"  Completed   : {attempt} attempt(s)")
        print(f"  Coverage    : {cov:.4f}%")
        print(f"  Total time  : {format_time(total_elapsed)}")
        print(f"\n  Resume with:")
        print(f"    python3 bsgs_scan.py --cpu --resume --seed {seed} -R {args.random_scan} \\")
        print(f"      -p {args.pubkey} \\")
        print(f"      -s {hex(original_start)} -e {hex(original_end)} \\")
        print(f"      -m {args.m_size} --workers {getattr(args,'workers',1)}")
        print()

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n\033[1;32mBSGS\033[0m - \033[36mBitcoin Private Key Search\033[0m\n")
    args = parse_arguments()

    # ── Benchmark mode ────────────────────────────────────────────────────
    if args.benchmark:
        if not args.workers:
            args.workers = multiprocessing.cpu_count()
        if args.end_range and args.end_range <= args.start_range:
            print("[!] End range must be greater than start range")
            sys.exit(1)

        best_m, best_chunk = run_benchmark(args)

        if args.run:
            # Validate that we have everything needed to actually search
            if not args.pubkey:
                print("\n[!] --run requires -p (public key)")
                sys.exit(1)
            if len(args.pubkey) != 66 or not args.pubkey.startswith(('02', '03')):
                print("[!] Public key must be 66 hex chars starting with 02 or 03")
                sys.exit(1)
            if not args.end_range:
                print("\n[!] --run requires -e (end range) for bounded search")
                sys.exit(1)

            print(f"\n[*] Proceeding with benchmark-recommended settings:")
            if best_m:
                print(f"    M_SIZE  = {best_m:,}")
                args.m_size = best_m
            if best_chunk:
                # Patch the module-level constant for this run
                global CPU_MINI_BATCH
                CPU_MINI_BATCH = best_chunk
                print(f"    chunk   = {best_chunk}")
            print()

            # Force CPU (benchmark is CPU-only)
            args.cpu = True
            if not args.m_size:
                args.m_size = DEFAULT_M_SIZE
            try:
                run_bsgs_cpu(args)
            except Exception as e:
                print(f"\n[!] ERROR: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
        return

    # ── Normal search mode ────────────────────────────────────────────────
    if not args.pubkey:
        print("[!] -p / --pubkey is required for search mode")
        print("    Use --benchmark to calibrate without a pubkey")
        sys.exit(1)

    if len(args.pubkey) != 66 or not args.pubkey.startswith(('02', '03')):
        print("[!] Public key must be 66 hex chars starting with 02 or 03")
        sys.exit(1)

    # Choose backend
    use_gpu = _HAVE_GPU and not args.cpu
    if use_gpu:
        print(f"[*] Backend: GPU (CuPy)\n")
        if args.m_size is None:
            args.m_size = DEFAULT_M_SIZE_GPU
        search_fn = run_bsgs_gpu
    else:
        reason = "CPU mode forced" if args.cpu else "CuPy/CUDA not available"
        print(f"[*] Backend: CPU ({reason})")
        if args.m_size is None:
            args.m_size = DEFAULT_M_SIZE
        if not args.workers:
            args.workers = multiprocessing.cpu_count()
        print(f"[*] Workers: {args.workers} (logical CPU cores: {multiprocessing.cpu_count()})\n")
        search_fn = run_bsgs_cpu

    if args.m_size < 1000:
        print("[!] M_SIZE too small (minimum: 1000)")
        sys.exit(1)

    if args.random_scan:
        run_random_scan(args, search_fn)
    else:
        if args.end_range and args.end_range <= args.start_range:
            print("[!] End range must be greater than start range")
            sys.exit(1)
        try:
            search_fn(args)
        except Exception as e:
            print(f"\n[!] ERROR: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    main()
