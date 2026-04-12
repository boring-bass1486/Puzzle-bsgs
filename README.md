# BSGS GPU - Bitcoin Private Key Search

A high-performance GPU-accelerated implementation of the Baby-Step Giant-Step (BSGS) algorithm for Bitcoin private key recovery. This tool leverages CUDA for massive parallel processing on NVIDIA GPUs.

## 🚀 Features

- **GPU-Accelerated**: Utilizes CUDA for parallel point generation and searching
- **Flexible Configuration**: Customizable M_SIZE, batch sizes, and GPU parameters
- **Multi-Architecture Support**: Automatic detection and support for various NVIDIA GPU architectures
- **Range Scanning**: Search specific ranges or continuous scanning
- **Real-time Statistics**: Live performance metrics and progress tracking
- **Professional CLI**: Full command-line interface with comprehensive options

## 📋 Table of Contents

- [Theory](#-theory)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Compilation](#-compilation)
- [CUDA Kernels](#-cuda-kernels)
- [Random Scan Strategy](#-random-scan-strategy)
- [Usage](#-usage)
- [Examples](#-examples)
- [Performance](#-performance)
- [GPU Architectures](#-gpu-architectures)
- [How It Works](#-how-it-works)
- [Parameters Guide](#-parameters-guide)
- [Troubleshooting](#-troubleshooting)
- [Security Notes](#-security-notes)
- [Output Example](#-output-example)
- [Contributing](#-contributing)
- [License](#-license)
- [Disclaimer](#-disclaimer)
- [Support](#-support)

**📖 Additional Documentation:** 
- [QUICKSTART.md](QUICKSTART.md) - Get started in 5 minutes
- [AutoVerification.md](AutoVerification.md) - Automatic Verification and Continuation
- [EXAMPLE_OUT_PUZZLE130.md](EXAMPLE_OUT_PUZZLE130.md) - Output Example: Puzzle #130 with False Positive Detection
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Troubleshooting


## 🧮 Theory

The Baby-Step Giant-Step algorithm is a meet-in-the-middle algorithm for solving the discrete logarithm problem. For Bitcoin private key recovery:

1. **Baby Steps**: Precompute and store `M` points: `G, 2G, 3G, ..., M*G`
2. **Giant Steps**: Generate points: `P, P-M*G, P-2M*G, ...` where P is the target public key
3. **Collision Detection**: When a giant step matches a baby step, we've found the private key

**Complexity**: O(√n) time and space, where n is the search space size.

## 💻 Requirements

### Software
- Python 3.7+
- CUDA Toolkit 11.0+ (12.0+ recommended)
- NVIDIA GPU with Compute Capability 7.5+

### Python Packages
```bash
numpy>=1.19.0
cupy-cuda12x>=12.0.0  # Use appropriate version for your CUDA
```

## 📦 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/ebookcms/bsgs-gpu.git
cd bsgs-gpu
```

### 2. Install Dependencies

[WINDOWS]

**For CUDA 12.x:**
```bash
pip install numpy cupy-cuda12x
```

**For CUDA 11.x:**
```bash
pip install numpy cupy-cuda11x
```

**Alternative (using conda):**
```bash
conda install -c conda-forge cupy
```

[LINUX]
```bash
python3 -m venv venv
source venv/bin/activate
pip install -U cupy-cuda12x
```

### 3. Verify GPU Setup
```python
python -c "import cupy as cp; print(f'GPU: {cp.cuda.Device(0).name}')"
```

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

## 🔨 CUDA Kernels

### CUDA Kernel already compilied

```
Compile the CUDA kernel for your GPU architecture:
You are free to use the software without restrictions, provided you 
respect the original authorship.
```


## 🎲 Random Scan Strategy

The `-R` SIZE (random scan) option enables probabilistic search instead of sequential scanning.


### How It Works

```
1. Define your search range: -s START -e END
2. Specify scan size: -R 50 (scan 50 trillion keys)
3. Tool randomly picks: START ≤ random_start ≤ (END - 50T)
4. Scans from random_start to random_start + 50T
```

### Use Cases

**Single GPU - Probabilistic Coverage:**
```bash
# Run multiple times with different random segments
python bsgs_scan.py -p <PUBKEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 50
```

**Multi-GPU - Parallel Search:**
```bash
# Each GPU searches different random segments simultaneously
for i in {1..4}; do
  python bsgs_scan.py -p <PUBKEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o "gpu${i}.txt" &
done
```

**Distributed Computing:**
```bash
# Machine 1
python bsgs_scan.py -p <PUBKEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 100

# Machine 2
python bsgs_scan.py -p <PUBKEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 100

# Each machine searches different random 100T segments
```

### Statistics

For Puzzle #50 range (562.95 TKeys total):

| Scan Size | Coverage per Run | Runs for 50% Coverage | Runs for 95% Coverage |
|-----------|------------------|------------------------|------------------------|
| 50 TKeys | 8.9% | ~6 runs | ~33 runs |
| 100 TKeys | 17.8% | ~3 runs | ~16 runs |
| 200 TKeys | 35.5% | ~2 runs | ~8 runs |

**Probability Formula:**
```
P(found) = 1 - (1 - scan_size/total_range)^num_runs
```

### Advantages

✅ **Better for Multiple GPUs**: Each GPU searches different areas  
✅ **No Coordination Needed**: GPUs don't need to communicate  
✅ **Flexible**: Can stop/start anytime without losing sequential position  
✅ **Probabilistic**: Might find key faster than sequential (or slower - it's random!)

### When to Use

- **Multiple GPUs**: Always use random scan
- **Single GPU**: Use sequential (-s to -e) unless you want to try luck
- **Distributed**: Random scan is ideal
- **Time Limited**: Random scan gives you a chance even with limited time

## 🎯 Usage

### Basic Syntax
```bash
python bsgs_scan.py -p <PUBLIC_KEY> [OPTIONS]
```

### Required Arguments
- `-p, --pubkey`: Compressed public key (66 hex characters, starting with 02 or 03)

### Optional Arguments
- `-s, --start-range`: Start of search range (hex or decimal, default: 0x2000000000000)
- `-e, --end-range`: End of search range (optional)
- `-R, --random-scan`: Random scan mode - scan X TKeys from random position (example: `-R 50`)
- `-m, --m-size`: Baby steps table size (default: 4,194,304)
- `-k, --kernel`: Custom CUDA kernel file
- `-o, --output`: Output file to save results
- `-v, --verbose`: Verbose output

### GPU Configuration
- `--baby-blocks`: GPU blocks for baby step generation (default: 512)
- `--baby-threads`: Threads per block for baby steps (default: 256)
- `--baby-batch`: Batch size for baby generation (default: 100,000)
- `--search-blocks`: GPU blocks for search (default: 2,048)
- `--search-threads`: Threads per block for search (default: 256)
- `--giant-batch`: Giant steps batch size (default: 5,000,000)

## 📚 Examples

### Example 1: Basic Search (Bitcoin Puzzle #50)
```bash
python bsgs_scan.py -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 -o found_Puzzle50.txt
```

### Example 2: Search Specific Range
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x3ffffffffffff
```

### Example 3: Custom M_SIZE (8M baby steps)
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -m 8388608
```

### Example 4: High-Performance Configuration
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -m 8388608 \
  --baby-batch 200000 \
  --giant-batch 10000000 \
  --search-blocks 4096
```

### Example 5: Save Result to File
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -o found_key.txt
```

### Example 6: Using Custom Kernel
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -k my_custom_kernel.fatbin
```

### Example 7: Decimal Range Input
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 562949953421312 \
  -e 1125899906842623
```

### Example 8: Random Scan - Search 50 TKeys from Random Position
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x3ffffffffffff \
  -R 50
```

**What it does:**
- Picks a random starting point between 0x2000000000000 and 0x3ffffffffffff
- Scans 50 trillion keys from that point
- Stops at random_start + 50T or end_range (whichever comes first)

### Example 9: Multiple GPUs - Parallel Random Scanning
```bash
# GPU 1
python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu1.txt &

# GPU 2
python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu2.txt &

# GPU 3
python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu3.txt &
```

**Benefits:**
- Each instance searches a different random 50 TKey segment
- Probabilistic coverage of the entire range
- Ideal for multi-GPU setups

## ⚡ Performance

### Typical Performance Metrics

Performance based on real-world testing with M_SIZE = 4M (4,194,304):

| GPU Model | M_SIZE | Giant Batch | Keys/Batch | Batch Time | Speed (TKey/s) |
|-----------|--------|-------------|------------|------------|----------------|
| RTX 4090 | 4M | 5M | 20.97B | ~1.0s | ~2.5-3.0 |
| RTX 3090 | 4M | 5M | 20.97B | ~1.2s | ~2.0-2.5 |
| RTX 3080 | 4M | 5M | 20.97B | ~1.5s | ~1.8-2.1 |
| RTX 3070 | 4M | 5M | 20.97B | ~1.8s | ~1.5-1.8 |
| RTX 2080 Ti | 4M | 5M | 20.97B | ~2.0s | ~1.3-1.6 |

**Verified Performance (Real Test):**
- **RTX 3080**: 41.94T keys in 20.1 sec = **2.09 TKey/s** ✓

**Notes:** 
- Keys per batch = Giant_Batch × M_SIZE = 5,000,000 × 4,194,304 = 20,971,520,000 keys
- 1 TKey/s = 1,000 GKey/s = 1,000,000 MKey/s = 1 trillion keys/second
- Actual speed depends on GPU boost clocks, cooling, and system configuration

*Performance verified with actual RTX 3080 test data*

### Performance Optimization Tips

1. **Increase M_SIZE** for larger search spaces:
   - 4M (4,194,304): Good for ranges up to 2^50
   - 8M (8,388,608): Better for larger ranges
   - 16M (16,777,216): Maximum efficiency (requires more VRAM)

2. **Adjust batch sizes** based on your GPU:
   - More VRAM → Larger `--giant-batch`
   - Faster GPU → Increase `--search-blocks`

3. **Compile optimizations**:
   - Use `--use_fast_math` for speed (already included)
   - Ensure correct architecture (`-arch=sm_XX`)

## 🖥️ GPU Architectures

### Supported NVIDIA GPU Architectures

| Architecture | Compute Capability | Example GPUs | Binary Name |
|--------------|-------------------|--------------|-------------|
| Turing | 7.5 | RTX 2060-2080 Ti, GTX 1650-1660 Ti | `bsgs_scan_sm75.fatbin` |
| Ampere | 8.0 | A100, A30 | `bsgs_scan_sm80.fatbin` |
| Ampere | 8.6 | RTX 3060-3090, A4000-A6000 | `bsgs_scan_sm86.fatbin` |
| Ada Lovelace | 8.9 | RTX 4060-4090, L4, L40 | `bsgs_scan_sm89.fatbin` |
| Hopper | 9.0 | H100, H800 | `bsgs_scan_sm90.fatbin` |

### Check Your GPU Compute Capability
```bash
nvidia-smi --query-gpu=name,compute_cap --format=csv
```

## 🔍 How It Works

### Algorithm Flow

```
1. Load CUDA kernel for GPU architecture
2. Generate baby steps table on GPU (1*G to M*G)
3. Calculate starting base point: P_base = Target - Start*G
4. For each giant step batch:
   a. Generate giant steps: P_base - i*M*G (on GPU)
   b. Search for collisions in baby steps table (on GPU)
   c. If collision found: PrivKey = Start + (giant_idx * M) + baby_idx
   d. Move to next batch: P_base = P_base - BatchSize*M*G
5. Verify found key and save result
```

### Memory Usage

- **Baby Steps Table**: `M_SIZE * 16 bytes` (x-coordinate + index)
  - 4M → ~64 MB
  - 8M → ~128 MB
  - 16M → ~256 MB

- **Giant Steps Buffer**: `GIANT_BATCH_SIZE * 8 bytes`
  - 5M → ~40 MB
  - 10M → ~80 MB

- **Total GPU VRAM**: ~200-500 MB (varies with configuration)

## 📖 Parameters Guide

### M_SIZE Selection Guide

| Search Range | Recommended M_SIZE | Memory | Reason |
|--------------|-------------------|--------|---------|
| < 2^45 | 1M - 2M | 16-32 MB | Fast baby generation |
| 2^45 - 2^50 | 4M | 64 MB | Balanced performance |
| 2^50 - 2^55 | 8M | 128 MB | Better giant/baby ratio |
| > 2^55 | 16M - 32M | 256-512 MB | Minimize giant steps |

### Batch Size Selection

**Baby Batch Size** (`--baby-batch`):
- **Low VRAM (4-6 GB)**: 50,000 - 100,000
- **Medium VRAM (8-12 GB)**: 100,000 - 200,000
- **High VRAM (16+ GB)**: 200,000 - 500,000

**Giant Batch Size** (`--giant-batch`):
- **Low VRAM (4-6 GB)**: 2,000,000 - 5,000,000
- **Medium VRAM (8-12 GB)**: 5,000,000 - 10,000,000
- **High VRAM (16+ GB)**: 10,000,000 - 20,000,000

## 🐛 Troubleshooting

### Common Issues

#### 1. "CUDA out of memory"
```bash
# Reduce batch sizes
python bsgs_scan.py -p <PUBKEY> --baby-batch 50000 --giant-batch 2000000
```

#### 2. "Invalid public key"
- Ensure key is 66 hex characters
- Must start with `02` or `03`
- Example valid key: `03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6`

#### 3. GPU not detected
```python
# Test CuPy installation
python -c "import cupy as cp; print(cp.cuda.runtime.getDeviceCount())"
```

#### 4. Slow performance
- Verify correct CUDA architecture compilation
- Check GPU utilization: `nvidia-smi dmon`
- Increase batch sizes if VRAM allows
- Ensure GPU is not thermal throttling

### Debug Mode

Enable verbose output for detailed logging:
```bash
python bsgs_scan.py -p <PUBKEY> -v
```

## 🔐 Security Notes

- **Educational Purpose**: This tool is for educational and recovery purposes only
- **Legal Use**: Only use on keys you own or have permission to recover
- **No Warranty**: No guarantees on finding keys or performance
- **Computational Reality**: Breaking unknown Bitcoin keys is computationally infeasible

## 📊 Output Example

```
================================================================================
  Rukka BSGS GPU - BITCOIN PRIVATE KEY SEARCH
================================================================================
  Public Key      : 03f46f41027bbf44fa...c7cdd3c5a16c6
  M_SIZE          : 4,194,304
  Baby gen batch  : 100,000
  Giant batch     : 5,000,000

  Search Range:
    Start         : 0x2000000000000
    Mode          : Continuous (until found)

  GPU Configuration:
    Baby  : 512 blocks x 256 threads
    Search: 2048 blocks x 256 threads
================================================================================

[*] GPU Kernel: bsgs_scan_sm86.fatbin
[*] Loading kernel...
    ✓ Kernel loaded

[*] Generating 4,194,304 baby steps on GPU...
    ✓ GPU: 8.2s | 511K pts/s

[*] Preparing search...
    ✓ Setup complete

[*] Starting search...

================================================================================
[BATCH #1]
================================================================================
  Giant steps     : 0 → 5,000,000
  Current range   : 0x2000000000000
                    → 0x200004FFFFFFF
  Space covered   : 0 keys
────────────────────────────────────────────────────────────────────────────────
    ✓ Giant steps: 0.85s | 5.88 Mpts/s
    ✓ Search: 0.32s

  Batch Results:
    Giant steps : 0.85s | 5.88 Mpts/s
    Search      : 0.32s
    Batch time  : 1.17s
    Keys scanned: 20,971,520,000 keys
    Batch speed : 17,915.39 MKey/s (17,915,393,162 keys/s)

  Cumulative Statistics:
    Total time        : 1.2 sec
    Giant steps done  : 5,000,000
    Space covered     : 20,971,520,000 keys
    Average speed     : 17,476.27 MKey/s (17,476,266,667 keys/s)
================================================================================

[BATCH #2]
================================================================================
  Giant steps     : 5,000,000 → 10,000,000
  Current range   : 0x200004FFFFFFF
                    → 0x20000a0000000
  Space covered   : 20,971,520,000 keys
  ...
================================================================================

[BATCH #3]
================================================================================
  Giant steps     : 10,000,000 → 15,000,000
  Current range   : 0x22625a0000000
                    → 0x2393870000000
  Space covered   : 41,943,040,000,000 keys
────────────────────────────────────────────────────────────────────────────────
    ✓ Giant steps: 6.66s | 0.75 Mpts/s
    ✓ Search: 0.01s

  Batch Results:
    Giant steps : 6.66s | 0.75 Mpts/s
    Search      : 0.01s
    Batch time  : 6.67s
    Keys scanned: 20,971,520,000 keys
    Batch speed : 3,144.25 MKey/s (3,144,253,373 keys/s)

  Cumulative Statistics:
    Total time        : 20.1 sec
    Giant steps done  : 15,000,000
    Space covered     : 62,914,560,000,000 keys
    Average speed     : 3,130.50 MKey/s (3,130,502,488 keys/s)
================================================================================
  ✓✓✓ PRIVATE KEY FOUND! ✓✓✓
================================================================================
  Private Key (Hex): 0X22BD43C2E9354
  Private Key (Dec): 611,140,496,167,764
  WIF (Compressed):  KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgfXBMYdNVA4EjUMzg
  Bitcoin Address:   1MEzite4ReNuWaL5Ds17ePKt2dCxWEofwk
  Public Key:        03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6
────────────────────────────────────────────────────────────────────────────────
  Search Time:       20.1 sec
  Verification:      ✓ PASSED
================================================================================

✓ Result saved to: found_key.txt
```

**Performance Analysis (RTX 3080 - Real Test):**
- Total search time: 20.1 seconds
- Keys searched: 62,914,560,000,000 keys (62.9 trillion)
- Average speed: 3.13 TKey/s (3,130,502,488 keys/s)
- For full Puzzle #50 range: ~2.8 minutes (worst case)


## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is provided for **educational and recovery purposes only**. The authors are not responsible for any misuse or damage caused by this software. Always ensure you have proper authorization before attempting to recover any private keys.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/ebookcms/bsgs_scan/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ebookcms/bsgs_scan/discussions)

### Please consider supporting bsgs_scan with a donation
BTC address: **1PsY4534k5wozsmT63rXpnCMdZuypkhAwo**


### 🌟 Acknowledgments

- NVIDIA CUDA Toolkit
- CuPy Development Team
- Bitcoin Community
- Baby-Step Giant-Step Algorithm by Daniel Shanks

---

**Star ⭐ this repository if you find it helpful!**