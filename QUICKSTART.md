# Rukka BSGS GPU - Quick Start Guide

## 🚀 Quick Setup (5 minutes)

### Step 1: Install Dependencies
[WINDOWS]
```bash
# Install Python packages
pip install numpy cupy-cuda12x

# Verify installation
python -c "import cupy as cp; print(f'✓ CuPy installed, GPU: {cp.cuda.Device(0).name}')"
```

[LINUX]
```bash
python3 -m venv venv
source venv/bin/activate
pip install -U cupy-cuda12x
```


### Step 2: Run Your First Search
```bash
# Basic search (Bitcoin Puzzle #50)
python bsgs_scan.py -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6
```

## 📋 Common Use Cases

### Case 1: Search Known Range (Fastest)
When you know approximately where the key is:

```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x3ffffffffffff
```

**Why:** Searching a specific range is much faster than continuous searching.

### Case 2: Maximum Performance (High-end GPU)
For RTX 4090, RTX 3090, or similar:

```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -m 8388608 \
  --baby-batch 200000 \
  --giant-batch 10000000 \
  --search-blocks 4096
```

**Expected:** ~2.5-3.0 TKey/s (trillion keys/s) on RTX 4090

### Case 3: Memory-Constrained GPU (6-8 GB VRAM)
For RTX 3060, RTX 2070, or similar:

```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -m 4194304 \
  --baby-batch 100000 \
  --giant-batch 5000000
```

**Expected:** ~1.2-1.5 TKey/s on RTX 3060

### Case 4: Save Results Automatically
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x3ffffffffffff \
  -o found_keys.txt
```

Result will be saved to `found_keys.txt` with timestamp.

### Case 5: Random Scan - Search Different Random Segments
```bash
# Scan random 50 TKeys within the range
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x3ffffffffffff \
  -R 50
```

**Why:** Perfect for multiple GPUs - each searches a different random segment.

### Case 6: Multi-GPU Parallel Random Search
```bash
# Run on multiple GPUs simultaneously (each searches different random area)
CUDA_VISIBLE_DEVICES=0 python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu0.txt &
CUDA_VISIBLE_DEVICES=1 python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu1.txt &
CUDA_VISIBLE_DEVICES=2 python bsgs_scan.py -p 03f46f... -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o gpu2.txt &
```

**Expected:** 3x RTX 3080 = ~6 TKey/s combined = **1.5 minutes for 50% chance**

## 🎲 Random Scan Strategy

Random scan (`-R`) is a powerful feature for probabilistic key search:

### How It Works
```
Normal: Start → → → → → → → End (sequential)
Random: Start → [random] → scan 50T → [random] → scan 50T
```

### Quick Examples

**Single Run:**
```bash
python bsgs_scan.py -p <PUBLIC KEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 50
```
- Picks random position in range
- Scans 50 TKeys from there
- 8.9% chance of finding the key (50T / 562.95T)

**Multiple Runs (Better Coverage):**
```bash
# Run 6 times = 50% probability of finding key
for i in {1..6}; do
  python bsgs_scan.py -p <PUBLIC KEY> -s 0x2000000000000 -e 0x3ffffffffffff -R 50 -o "run${i}.txt"
done
```

**Multi-GPU (Best Strategy):**
```bash
# 3 GPUs searching simultaneously
CUDA_VISIBLE_DEVICES=0 python bsgs_scan.py -p <PUBLIC KEY> -R 50 -s 0x2000000000000 -e 0x3ffffffffffff &
CUDA_VISIBLE_DEVICES=1 python bsgs_scan.py -p <PUBLIC KEY> -R 50 -s 0x2000000000000 -e 0x3ffffffffffff &
CUDA_VISIBLE_DEVICES=2 python bsgs_scan.py -p <PUBLIC KEY> -R 50 -s 0x2000000000000 -e 0x3ffffffffffff &

# Each GPU: ~2 TKey/s × 50T = ~25 seconds per run
# Combined: 3 GPUs = 3 runs in 25 sec = 24% coverage in 25 sec
```

### When to Use Random Scan

| Scenario | Use Random? | Why |
|----------|-------------|-----|
| Single GPU, time unlimited | ❌ No | Sequential is systematic |
| Single GPU, time limited | ✅ Yes | Chance to get lucky |
| 2+ GPUs | ✅✅ YES | No coordination needed, parallel search |
| Distributed mining | ✅✅ YES | Perfect for multiple machines |
| Want to cover specific % | ✅ Yes | Calculate runs needed |

### Coverage Calculator

For Puzzle #50 (562.95 TKeys):

| Scan Size | Runs for 50% | Runs for 90% | Runs for 99% |
|-----------|--------------|--------------|--------------|
| 25 TKeys | 12 runs | 42 runs | 93 runs |
| 50 TKeys | 6 runs | 21 runs | 46 runs |
| 100 TKeys | 3 runs | 11 runs | 23 runs |
| 200 TKeys | 2 runs | 5 runs | 12 runs |

**Formula:** `runs_needed = ln(1 - target_probability) / ln(1 - scan_size/total_size)`

## 🎯 Configuration Presets

### Preset 1: Speed Priority (Large VRAM)
```bash
M_SIZE=8388608         # 8M baby steps
BABY_BATCH=200000      # 200K baby batch
GIANT_BATCH=10000000   # 10M giant batch
SEARCH_BLOCKS=4096     # More GPU blocks
```

**Best for:** RTX 4090, RTX 3090, A6000 (24GB+)  
**VRAM usage:** ~600 MB  
**Speed:** ~2.5-3.0 TKey/s (with Giant_Batch=10M, M_SIZE=8M)

### Preset 2: Balanced (Medium VRAM)
```bash
M_SIZE=4194304         # 4M baby steps
BABY_BATCH=100000      # 100K baby batch
GIANT_BATCH=5000000    # 5M giant batch
SEARCH_BLOCKS=2048     # Standard blocks
```

**Best for:** RTX 3080, RTX 3070, RTX 2080 Ti (10-12GB)  
**VRAM usage:** ~300 MB  
**Speed:** ~1.8-2.1 TKey/s (with Giant_Batch=5M, M_SIZE=4M)

### Preset 3: Low Memory (Small VRAM)
```bash
M_SIZE=2097152         # 2M baby steps
BABY_BATCH=50000       # 50K baby batch
GIANT_BATCH=2000000    # 2M giant batch
SEARCH_BLOCKS=1024     # Fewer blocks
```

**Best for:** RTX 3060, RTX 2060, GTX 1660 Ti (6-8GB)  
**VRAM usage:** ~150 MB  
**Speed:** ~1.2-1.5 TKey/s (with Giant_Batch=2M, M_SIZE=2M)

## 🔧 Optimization Guide

### 1. Determine Optimal M_SIZE

Rule of thumb:
```
Optimal M_SIZE ≈ √(search_range_size)
```

Examples:
- Range 2^50 (1,125,899,906,842,624 keys) → M_SIZE ≈ 33M (use 4M-8M for practical reasons)
- Range 2^48 (281,474,976,710,656 keys) → M_SIZE ≈ 16M (use 2M-4M)
- Range 2^45 (35,184,372,088,832 keys) → M_SIZE ≈ 5M (use 1M-2M)

### 2. Balance Baby vs Giant Steps

More baby steps (higher M_SIZE):
- ✓ Fewer giant steps needed
- ✓ Less GPU memory transfers
- ✗ Longer initial setup time
- ✗ More VRAM required

Fewer baby steps (lower M_SIZE):
- ✓ Faster setup
- ✓ Less VRAM
- ✗ More giant steps needed
- ✗ More memory operations

### 3. GPU Utilization Check

Monitor GPU usage while running:
```bash
# In another terminal
watch -n 1 nvidia-smi
```

**Target metrics:**
- GPU Utilization: 95-100%
- Memory Usage: 60-80% of available VRAM
- Temperature: Below 80°C

If GPU utilization < 90%:
```bash
# Increase batch sizes
--baby-batch 200000
--giant-batch 10000000
--search-blocks 4096
```

## ⚡ Performance Troubleshooting

### Problem: Slow baby step generation
**Solution:** Increase `--baby-batch`
```bash
python bsgs_scan.py -p <PUBLIC KEY> --baby-batch 200000
```

### Problem: Slow giant step generation
**Solution:** Increase `--search-blocks` and `--giant-batch`
```bash
python bsgs_scan.py -p <PUBLIC KEY> --giant-batch 10000000 --search-blocks 4096
```

### Problem: Out of memory error
**Solution:** Decrease batch sizes and M_SIZE
```bash
python bsgs_scan.py -p <PUBLIC KEY> -m 2097152 --baby-batch 50000 --giant-batch 2000000
```

### Problem: GPU underutilized
**Solution:** Increase thread blocks
```bash
python bsgs_scan.py -p <PUBLIC KEY> --search-blocks 4096 --baby-blocks 1024
```

## 📊 Expected Search Times

### For Bitcoin Puzzle #50 (Range: 2^49 to 2^50)

**Range size:** ~562.95 trillion keys (0x2000000000000 to 0x3ffffffffffff)

| GPU Model | M_SIZE | Speed (TKey/s) | Worst Case* | Average Case** |
|-----------|--------|----------------|-------------|----------------|
| RTX 4090 | 8M | 2.5-3.0 | ~3-4 min | ~1.5-2 min |
| RTX 3090 | 8M | 2.0-2.5 | ~4-5 min | ~2-2.5 min |
| RTX 3080 | 4M | 1.8-2.1 | ~4.5-5 min | ~2.2-2.5 min |
| RTX 3070 | 4M | 1.5-1.8 | ~5-6 min | ~2.5-3 min |
| RTX 2080 Ti | 4M | 1.3-1.6 | ~6-7 min | ~3-3.5 min |

**Real Test Results:**
```
RTX 3080 Performance (Verified):
- Keys searched: 41,943,040,000,000 keys
- Time: 20.1 seconds
- Speed: 2,086,618,905,472 keys/s = 2.09 TKey/s ✓
```

**Calculations for full Puzzle #50 range:**
```
Total range: 0x3ffffffffffff - 0x2000000000000 = 562,949,953,421,311 keys

RTX 3080 @ 2.09 TKey/s:
- Worst case (key at end): 562.95T / 2.09T/s = 269.4 sec = 4.49 min ✓
- Average case (key at 50%): 562.95T / 2 / 2.09T/s = 134.7 sec = 2.24 min ✓
```

*\*Worst case: Key is at the very end of the range*  
*\*\*Average case: Key is somewhere in the middle of the range (50% probability)*

**Note:** These times assume continuous operation at peak performance. Real-world times may vary due to:
- GPU boost behavior and thermal throttling
- System load and background processes
- Batch overhead and kernel launch latency

## 🎓 Learning Examples

### Example 1: Understanding M_SIZE Impact

Search with M_SIZE = 1M:
```bash
python bsgs_scan.py -p <PUBLIC KEY> -m 1048576 -s 0x2000000000000 -e 0x2000000100000
```

Search with M_SIZE = 4M:
```bash
python bsgs_scan.py -p <PUBLIC KEY> -m 4194304 -s 0x2000000000000 -e 0x2000000100000
```

**Observe:** 
- 4M setup takes longer but searches faster
- Total time should be similar for small ranges
- 4M is better for larger ranges

### Example 2: Batch Size Testing

Test small batches:
```bash
python bsgs_scan.py -p <PUBLIC KEY> --giant-batch 1000000
```

Test large batches:
```bash
python bsgs_scan.py -p <PUBLIC KEY> --giant-batch 10000000
```

**Observe:**
- Larger batches = fewer kernel launches
- Better GPU utilization
- May hit memory limits

## 🔍 Debugging

### Enable verbose output:
```bash
python bsgs_scan.py -p <PUBLIC KEY> -v
```

### Test with small range:
```bash
python bsgs_scan.py \
  -p 03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6 \
  -s 0x2000000000000 \
  -e 0x2000000001000 \
  -m 1048576
```

### Check CUDA compilation:
```bash
nvcc --version
nvidia-smi
ls -lh bsgs_scan_*.fatbin
```

## 📞 Need Help?

1. **Check README.md** for detailed documentation
2. **Run with `-v`** for verbose output
3. **Check GPU temp/usage** with `nvidia-smi`
4. **Verify CUDA version** matches CuPy installation
5. **Open GitHub issue** with error details

## 🎯 Next Steps

1. ✅ Verify setup with quick test
2. ✅ Run performance benchmark
3. ✅ Optimize for your GPU
4. ✅ Start actual search
5. ✅ Monitor and adjust as needed

Good luck with your search! 🚀
