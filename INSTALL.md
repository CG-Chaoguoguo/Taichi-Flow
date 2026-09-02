# Taichi-Flow Installation Guide

## System Requirements

### Python Version
- **Required**: Python 3.9 - 3.13
- **Not Supported**: Python 3.14+ (Taichi 1.7.4 limitation)

### Default Web UI
- **Required for the default Presentation Layer**: Node.js 22.12+ and npm (Electron 43.2.0)
- The default UI is the React/Vite app under `frontend/taichi-flow/`.
- The Streamlit UI remains available only as a legacy fallback / diagnostic path.

### Operating System
- Windows 10/11
- Linux (Ubuntu 20.04+, CentOS 7+)
- macOS 10.15+

### Hardware
- **GPU (Recommended)**: NVIDIA GPU with CUDA support for GPU acceleration
- **CPU**: Multi-core processor (minimum 4 cores recommended)
- **RAM**: Minimum 8GB, 16GB+ recommended for large simulations
- **Storage**: 2GB+ free space

## Installation Methods

### Method 1: Standard Installation (Recommended)

#### Step 1: Create Virtual Environment

**Windows:**
```bash
# Using py launcher (recommended)
py -3.11 -m venv .venv

# Activate
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
python3.11 -m venv .venv

# Activate
source .venv/bin/activate
```

#### Step 2: Upgrade pip
```bash
python -m pip install --upgrade pip
```

#### Step 3: Install Taichi-Flow

**Option A: From source (for development)**
```bash
# Clone repository
git clone https://github.com/CG-Chaoguoguo/Taichi-Flow.git
cd Taichi-Flow

# Install in editable mode
pip install -e .

# Install development tools
pip install -e ".[dev]"
```

**Option B: Install dependencies only**
```bash
pip install -r requirements.txt
```

### Method 2: Installation without GDAL

GDAL requires compilation on Windows and can be problematic. For core simulation functionality, GDAL is optional.

```bash
# Install all dependencies except GDAL
pip install taichi numpy scipy rasterio pyproj geopandas shapely \
    fastapi "uvicorn[standard]" websockets websocket-client python-multipart \
    streamlit plotly pandas pydantic python-dotenv tqdm pyyaml psutil matplotlib

# Install development tools
pip install pytest black mypy flake8
```

### Default React UI Setup

After installing the Python environment, install the browser UI dependencies:

```bash
cd frontend/taichi-flow
npm ci
```

Run the full default application from the repository root:

```bash
# One-command development stack, from repository root
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

The script starts FastAPI and React/Vite, waits for both health checks, then
opens the React UI in Electron with Vite HMR. It does not open a browser.
Use `-Browser` for the explicit browser presentation, or `-ServicesOnly` (the
legacy `-NoBrowser` alias remains supported) to start only the services.
Manual startup remains available:

```bash
# Terminal 1: FastAPI Service Layer
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000

# Terminal 2: React/Vite default Presentation Layer
cd frontend/taichi-flow
npm run dev -- --host 127.0.0.1 --port 3000
```

Open the Vite URL, normally `http://127.0.0.1:3000`, only when using the
explicit browser or services-only mode.

Stop the managed development stack with:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

The desktop development shell is also available by double-clicking
`scripts\desktop-dev\Start-Taichi-Flow-Desktop-Dev.bat` (Vite HMR) or running it
with `preview` (compiled `dist` through `app://taichi-flow`). The launcher owns
only services it created; reused services remain running, and Python, Taichi,
GDAL, and the solver are never bundled in ASAR.

Legacy fallback only:

```bash
python -m streamlit run frontend/streamlit_app.py --server.port 8501
```

### Method 3: Installation with GDAL (Advanced)

#### Windows (using OSGeo4W)
1. Download and install [OSGeo4W](https://trac.osgeo.org/osgeo4w/)
2. Install GDAL through OSGeo4W installer
3. Set environment variables:
   ```cmd
   set GDAL_DATA=C:\OSGeo4W\share\gdal
   set PROJ_LIB=C:\OSGeo4W\share\proj
   ```
4. Install Python bindings:
   ```bash
   pip install gdal==$(gdal-config --version)
   ```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install gdal-bin libgdal-dev
pip install gdal==$(gdal-config --version)
```

#### Using Conda (Cross-platform)
```bash
conda create -n taichi-flow python=3.11
conda activate taichi-flow
conda install -c conda-forge gdal
pip install -e .
```

## Verification

### Test Installation
```bash
# Run test suite
pytest tests/ -v

# Quick test
python -c "import taichi as ti; ti.init(arch=ti.gpu); print('Taichi GPU initialized successfully')"

# React UI checks
cd frontend/taichi-flow
npm test
npm run test:desktop
npm run build
```

### Expected Test Results
- **Total tests**: 127
- **Expected pass**: 108+ (85%+)
- **Expected skip**: 17 (comparison tests requiring specific data)
- **Expected fail**: 0-2 (minor issues with test data)

## Troubleshooting

### Issue 1: Python Version Incompatibility
**Error**: `Could not find a version that satisfies the requirement taichi>=1.6.0`

**Solution**: Check Python version
```bash
python --version  # Must be 3.9-3.13
```

If using Python 3.14+, downgrade to 3.13:
```bash
# Windows
py -3.13 -m venv .venv

# Linux/macOS
python3.13 -m venv .venv
```

### Issue 2: GDAL Installation Failure
**Error**: `building 'osgeo._gdal' extension` compilation errors

**Solution**: Skip GDAL (not required for core functionality)
```bash
# Edit setup.py and comment out gdal line
# Or use Method 2 installation
```

### Issue 3: Taichi GPU Initialization Failure
**Error**: `[Taichi] version 1.7.4, llvm 15.0.1, commit 2fd24490, win, python 3.11.9`

**Solution**: 
1. Update GPU drivers (NVIDIA/AMD/Intel)
2. Fall back to CPU:
   ```python
   import taichi as ti
   ti.init(arch=ti.cpu)  # Use CPU instead of GPU
   ```

### Issue 4: UnicodeDecodeError on Windows
**Error**: `UnicodeDecodeError: 'gbk' codec can't decode byte`

**Solution**: Already fixed in setup.py (encoding='utf-8')
```bash
# If still occurs, set environment variable
set PYTHONUTF8=1
```

### Issue 5: Import Errors
**Error**: `ModuleNotFoundError: No module named 'matplotlib'`

**Solution**: Install missing dependencies
```bash
pip install matplotlib
```

## GPU Acceleration Setup

### NVIDIA CUDA
1. Install [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) (11.0+)
2. Verify installation:
   ```bash
   nvidia-smi
   ```
3. Taichi will automatically detect CUDA

### AMD ROCm (Experimental)
Taichi has limited ROCm support. Use CPU backend for AMD GPUs.

### Apple Metal (macOS)
Taichi supports Metal backend on Apple Silicon:
```python
import taichi as ti
ti.init(arch=ti.metal)
```

## Performance Optimization

### Recommended Settings
```python
import taichi as ti

# GPU with optimization
ti.init(arch=ti.gpu, device_memory_GB=4.0, debug=False)

# CPU with multi-threading
ti.init(arch=ti.cpu, cpu_max_num_threads=8)
```

### Memory Configuration
For large simulations, increase device memory:
```python
ti.init(arch=ti.gpu, device_memory_GB=8.0)
```

## Development Setup

### Install Development Tools
```bash
pip install -e ".[dev]"
```

### Pre-commit Hooks (Optional)
```bash
pip install pre-commit
pre-commit install
```

### Code Formatting
```bash
# Format code
black edda/ tests/

# Type checking
mypy edda/

# Linting
flake8 edda/ tests/
```

## Docker Installation (Alternative)

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Clone and install
WORKDIR /app
RUN git clone https://github.com/CG-Chaoguoguo/Taichi-Flow.git
WORKDIR /app/Taichi-Flow
RUN pip install -e .

CMD ["python"]
```

Build and run:
```bash
docker build -t taichi-flow .
docker run -it --gpus all taichi-flow
```

## Next Steps

After successful installation:
1. Read [Getting Started Guide](docs/getting_started.md)
2. Review [API Reference](docs/api_reference.md)
3. Try [Example Simulations](examples/)
4. Check [Project Reports](PROJECT_REPORTS/)

## Support

- **Issues**: https://github.com/CG-Chaoguoguo/Taichi-Flow/issues
- **Documentation**: [docs/](docs/)
- **Test Reports**: [PROJECT_REPORTS/FIX_LOGS/](PROJECT_REPORTS/FIX_LOGS/)

## Version Compatibility Matrix

| Component | Minimum | Tested | Maximum |
|-----------|---------|--------|---------|
| Python | 3.9 | 3.11 | 3.13 |
| Taichi | 1.6.0 | 1.7.4 | <1.8.0 |
| NumPy | 1.24.0 | 2.4.4 | <3.0.0 |
| CUDA | 11.0 | 12.x | - |
| Windows | 10 | 11 | - |
| Ubuntu | 20.04 | 22.04 | - |

---
**Last Updated**: 2026-04-12  
**Taichi Version**: 1.7.4  
**Python Version**: 3.9-3.13
