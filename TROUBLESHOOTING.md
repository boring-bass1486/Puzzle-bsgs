# 🔧 Troubleshooting

## 🔍 Other Common Errors

### 1. GPU not detected (nvidia-smi fails)

**Cause**: NVIDIA Driver not installed or outdated

**Solution**:
```bash
# Install NVIDIA drivers
sudo ubuntu-drivers autoinstall
sudo reboot

# Verify
nvidia-smi
```

### 2. Out of Memory during execution

**Symptoms**: 
```
CUDA error: out of memory
```

**Solution 1** - Reduce M_SIZE:
```python
M_SIZE = 8388608  # 8M instead of 32M
```
or 

```bash
python3 -m 8388608 ...
```

**Solution 2** - Reduce GIANT_BATCH_SIZE:
```python
GIANT_BATCH_SIZE = 2500000  # 2.5M instead of 5M
```

**Solution 3** - Liberar memória GPU:
```bash
# Kill processes using the GPU
nvidia-smi
sudo kill -9 <PID>

# Or restart
sudo systemctl restart nvidia-persistenced
```

### 3. Very low performance

**Symptoms**: 
- Speed < 0.5 Mpts/s
- Low GPU utilization (<30%)


**Verifications**:

```bash
# 1. Temperature (thermal throttling?)
nvidia-smi -l 1

# 2. Power limit
nvidia-smi -q -d POWER

# 3. Clock speed
nvidia-smi -q -d CLOCK
```

**Solutions**:
```bash
# Increase power limit (careful!)
sudo nvidia-smi -pl 350  # RTX 3080: up to 350W

# Persistente mode
sudo nvidia-smi -pm 1

# Disable compositing (if in a desktop environment)
# Helps reduce overhead
```

### 4. Kernel fails to load (ModuleNotFoundError)

**Symptoms**:
```python
cupy.cuda.function.Module.load: libcuda.so.1: cannot open shared object file
```

**Solution**:
```bash
# Verify CUDA libraries
ldconfig -p | grep cuda

# Add to PATH if necessary
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Permanent (add to ~/.bashrc)
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
```

### 5. CuPy import error

**Symptoms**:
```python
ModuleNotFoundError: No module named 'cupy'
```

**Solution**:
```bash
# Install CuPy
pip3 install cupy-cuda11x  # Para CUDA 11.x
pip3 install cupy-cuda12x  # Para CUDA 12.x

# Verify CUDA version
nvcc --version

# Verify CuPy installation
python3 -c "import cupy as cp; print(cp.__version__)"
```

### 6. Wrong values / key not found

**Verifications**:

```python
# 1. Test with a known puzzle
PUBKEY_HEX = "03f46f41027bbf44fafd6b059091b900dad41e6845b2241dc3254c7cdd3c5a16c6"  # Puzzle 50
START_RANGE = 0x2000000000000
# Known key: 0x2832ED74F2B5E35EE  (within range)

# 2. Verify compute capability is correct
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

---

## 🆘 If Nothing Works

1. **Validate basic environment:**:
```bash
# CUDA installed?
nvcc --version

# Correct driver?
nvidia-smi

# CuPy installed?
python3 -c "import cupy; print('OK')"
```

2. **Contact support** with:
   - Output de `nvidia-smi`
   - Output de `nvcc --version`
   - Full error message
   - GPU model

---

## 📝 Log de Versões

- **v1.0**: Versão original (0.72 Mpts/s)

---

**First Version**: 01 Feb 2026
