# BSGS - Bitcoin Private Key Search

## Overview
High-performance Baby-Step Giant-Step (BSGS) algorithm for Bitcoin private key recovery.
Solves the discrete logarithm problem on the secp256k1 elliptic curve.
Supports both **CPU** (no GPU required) and **GPU** (CUDA/CuPy) backends.

## Tech Stack
- **Language**: Python 3.12
- **CPU backend**: multiprocessing + Jacobian coordinates + batch modular inversion (Montgomery's trick)
- **GPU backend**: CUDA via CuPy (requires NVIDIA GPU)
- **Fast math**: gmpy2 (optional, auto-detected)
- **CPU math**: Python built-in + numpy

## CPU Performance
- ~20–30 Gkeys/s on 8 CPU cores (M_SIZE=65536)
- Scales linearly with cores via `--workers`
- Jacobian coordinates avoid per-step modular inverses
- Montgomery batch inversion (one modinv per 2000 steps)
- Python dict for O(1) baby-step lookup

## Project Structure
- `bsgs_scan.py` — Main CLI (CPU + GPU backends, auto-detect)
- `run.py` — Environment check and quick-start guide
- `requirements.txt` — Python dependencies
- `*.fatbin` — Pre-compiled CUDA kernels (sm75/80/86/89/90)

## Dependencies
- `numpy>=1.19.0` — Installed
- `gmpy2` — Installed (optional fast-math backend)
- `cupy-cuda12x>=12.0.0` — Requires NVIDIA GPU (optional)

## Usage

### CPU Mode (no GPU required)
```bash
# Basic CPU search across all cores
python3 bsgs_scan.py --cpu -p <pubkey> -s <start> -e <end>

# Custom worker count and larger table
python3 bsgs_scan.py --cpu --workers 4 -m 262144 -p <pubkey> -s <start> -e <end>

# Random scan mode (probabilistic multi-attempt)
python3 bsgs_scan.py --cpu -p <pubkey> -s <start> -e <end> -R 50

# Save result to file
python3 bsgs_scan.py --cpu -p <pubkey> -s <start> -e <end> -o result.txt
```

### GPU Mode (requires CUDA)
```bash
python3 bsgs_scan.py -p <pubkey> -s <start> -e <end>
```

### All options
```bash
python3 bsgs_scan.py --help
```

## Key CLI Flags
| Flag | Description |
|------|-------------|
| `-p` | Compressed public key (66 hex chars) |
| `-s` | Start of search range (hex or decimal) |
| `-e` | End of search range (optional) |
| `-m` | Baby-step table size (default: 1M CPU / 4M GPU) |
| `--cpu` | Force CPU mode |
| `--workers N` | Number of CPU processes (default: all cores) |
| `-R N` | Random scan: scan N TKeys from a random position, repeat indefinitely |
| `--seed N` | RNG seed for `-R` mode — use different seeds on different machines to avoid overlap |
| `-o FILE` | Save found key to file |
| `--benchmark` | Calibrate CPU: measure speeds, find optimal M_SIZE, project time-to-completion |
| `--run` | After `--benchmark`, auto-run the search with optimal settings |

## Benchmark Feature
`--benchmark` runs a three-phase calibration:
1. **Phase 1** — Baby step generation rate vs M_SIZE (4K to 1M)
2. **Phase 2** — Giant step throughput vs chunk size (parallel, 500–8000), identifies pool overhead sweet spot
3. **Phase 3** — Projected total time for each M_SIZE accounting for pool dispatch overhead; selects the M_SIZE that minimises baby_time + giant_time

Outputs the recommended command with optimal `--m-size` and `--workers` for the current machine.

## Live Progress Bar
During CPU search, a live single-line progress bar updates every second:
```
  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 21.4% │ 23.1 Gkeys/s │ 1.4hr elapsed │ ETA 5.2hr
```
- **Bar fill** grows as range is covered (spinner for unbounded ranges)
- **Speed** — rolling average over the last 8 batches
- **ETA** — dynamic estimate based on current rolling speed
- Every 10 batches a one-line summary is printed above the bar with batch number, speed, elapsed, % and ETA
- On `KeyboardInterrupt`, prints total time, keys scanned, and % coverage

## Random Scan Mode (`-R`)
Probabilistic search that picks a random window of N TKeys within the range and searches it, repeating until the key is found or the user stops.

**Key features:**
- `--seed N` makes the sequence deterministic and reproducible. Run `--seed 0` on machine 1, `--seed 1` on machine 2 — completely non-overlapping sequences
- Coverage probability formula displayed at start: `P(found after n attempts) = 1 − (1−p)^n`
- Estimates how many attempts to reach 50% / 95% / 99% probability
- After each completed attempt: shows time per attempt, remaining attempts to 50%/99%, and writes state file
- `--resume` replays the RNG to the saved attempt count and continues from the right position

**Usage:**
```bash
# Machine 1 (seed 0)
python3 bsgs_scan.py --cpu -R 50 --seed 0 -p <pubkey> -s 0x2000000000000 -e 0x3ffffffffffff

# Machine 2 (seed 1) — completely independent random sequence
python3 bsgs_scan.py --cpu -R 50 --seed 1 -p <pubkey> -s 0x2000000000000 -e 0x3ffffffffffff

# Resume after Ctrl+C (seed must match)
python3 bsgs_scan.py --cpu --resume -R 50 --seed 0 -p <pubkey> -s 0x2000000000000 -e 0x3ffffffffffff
```

**State file:** auto-named `bsgs_rand_{pubkey[:12]}_{start[:8]}_s{seed}.state`

## Resume Feature
Interrupted searches are automatically saved to disk and can be resumed exactly where they left off.

**Triggered by:**
- `Ctrl+C` (SIGINT) — user interrupt
- `SIGTERM` (kill / timeout / system shutdown) — process termination
- Auto-save every 100 batches (insurance against crashes)
- State deleted automatically when key is found

**State file:** auto-named `bsgs_{pubkey[:12]}_{start[:12]}.state` (JSON), or custom path with `--state-file`.

**Usage:**
```bash
# Interrupt a long search (Ctrl+C or kill) — state is saved automatically.
# The interrupt message prints the exact --resume command to use.

python3 bsgs_scan.py --cpu --resume \
  -p <pubkey> -s <start> -e <end> -m <m_size>
```

**What resume does:**
1. Loads `giant_offset` and `total_elapsed` from the state file
2. Validates pubkey / start / m_size match the CLI args (aborts on mismatch)
3. Fast-forwards the EC base point to the saved position via a single `ec_mul` (O(log n), fast)
4. Initialises the progress bar with accumulated prior time so ETA is correct across sessions
5. Continues from the saved position — no re-scanning

## Workflow
- **Start application**: Runs `python3 run.py` — displays environment status and usage guide
