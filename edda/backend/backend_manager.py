"""
Backend manager for Taichi initialization and configuration.
"""
import taichi as ti
import logging
from threading import RLock
from typing import Optional

logger = logging.getLogger(__name__)

_RUNTIME_LOCK = RLock()
_RUNTIME_SIGNATURE = None


class BackendManager:
    """
    Manage Taichi backend initialization and configuration.
    Supports automatic backend selection and fallback.
    """

    SUPPORTED_BACKENDS = {
        'cuda': ti.cuda,
        'vulkan': ti.vulkan,
        'opengl': ti.opengl,
        'metal': ti.metal,
        'cpu': ti.cpu,
        'auto': None,  # Let Taichi choose
    }

    def __init__(self):
        self.backend = None
        self.is_initialized = False
        self.device_info = {}
        self._runtime_signature = None

    def initialize(
        self,
        backend: str = 'auto',
        use_double_precision: bool = False,
        num_threads: Optional[int] = None,
        device_memory_GB: float = 1.0,
        **kwargs
    ):
        """
        Initialize Taichi with specified backend.

        Args:
            backend: Backend name ('auto', 'cuda', 'cpu', 'vulkan', etc.)
            use_double_precision: Use f64 instead of f32
            num_threads: Number of CPU threads (for CPU backend)
            device_memory_GB: Device memory limit in GB
            **kwargs: Additional Taichi init arguments
        """
        global _RUNTIME_SIGNATURE
        backend = backend.lower()

        if backend not in self.SUPPORTED_BACKENDS:
            logger.warning(f"Unknown backend '{backend}', falling back to 'auto'")
            backend = 'auto'

        signature = (backend, bool(use_double_precision), num_threads, float(device_memory_GB), tuple(sorted(kwargs.items())))
        with _RUNTIME_LOCK:
            if self.is_initialized:
                if self._runtime_signature != signature:
                    raise RuntimeError(
                        "Taichi runtime configuration is incompatible with the active simulation set: "
                        f"active={self._runtime_signature!r}, requested={signature!r}"
                    )
                logger.info("Taichi already initialized with a compatible signature; reusing runtime.")
                return
            if _RUNTIME_SIGNATURE is not None and _RUNTIME_SIGNATURE != signature:
                raise RuntimeError(
                    "Taichi runtime configuration is incompatible with the active simulation set: "
                    f"active={_RUNTIME_SIGNATURE!r}, requested={signature!r}"
                )

        logger.info(f"Initializing Taichi with backend: {backend}")

        # Prepare initialization arguments
        init_args = {
            'default_fp': ti.f64 if use_double_precision else ti.f32,
            'device_memory_GB': device_memory_GB,
            'fast_math': False,
            **kwargs
        }

        # Add backend-specific arguments
        if backend == 'cpu' and num_threads is not None:
            init_args['cpu_max_num_threads'] = num_threads

        # Try to initialize with requested backend
        with _RUNTIME_LOCK:
            try:
                if backend == 'auto':
                    # Use project-defined priority instead of delegating implicit
                    # backend selection to Taichi, which can silently fall back to
                    # CPU on systems where CUDA is actually available.
                    self.backend = self._initialize_auto_backend(
                        init_args=init_args,
                        num_threads=num_threads,
                    )
                else:
                    arch = self.SUPPORTED_BACKENDS[backend]
                    ti.init(arch=arch, **init_args)
                    self.backend = backend

                self.is_initialized = True
                self._runtime_signature = signature
                _RUNTIME_SIGNATURE = signature
                self._detect_device_info()
                logger.info(f"Taichi initialized successfully with backend: {self.backend}")
                self._log_device_info()

            except Exception as e:
                logger.error(f"Failed to initialize backend '{backend}': {e}")

                # Fallback to CPU
                if backend != 'cpu':
                    logger.info("Falling back to CPU backend...")
                    try:
                        ti.init(arch=ti.cpu, **init_args)
                        self.backend = 'cpu'
                        self.is_initialized = True
                        self._runtime_signature = signature
                        _RUNTIME_SIGNATURE = signature
                        logger.info("CPU backend initialized successfully")
                    except Exception as e2:
                        logger.error(f"CPU fallback also failed: {e2}")
                        raise RuntimeError("Failed to initialize any Taichi backend")

    def _initialize_auto_backend(self, init_args: dict, num_threads: Optional[int]) -> str:
        """Initialize using the project priority order: cuda > vulkan > cpu."""
        available = self.get_available_backends()
        candidates = [name for name in ('cuda', 'vulkan', 'cpu') if name in available]
        if not candidates:
            candidates = ['cpu']

        errors = []
        for candidate in candidates:
            candidate_args = dict(init_args)
            if candidate == 'cpu' and num_threads is not None:
                candidate_args['cpu_max_num_threads'] = num_threads
            try:
                arch = self.SUPPORTED_BACKENDS[candidate]
                ti.init(arch=arch, **candidate_args)
                logger.info(f"Auto backend selected explicit '{candidate}'")
                return candidate
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                logger.warning(f"Auto backend candidate '{candidate}' failed: {exc}")

        raise RuntimeError(
            "Failed to initialize any automatic backend candidate "
            f"(cuda > vulkan > cpu). Errors: {'; '.join(errors)}"
        )

    def _detect_device_info(self):
        """Detect and store device information."""
        try:
            from taichi.lang import impl

            cfg = impl.current_cfg()
            runtime_arch = getattr(cfg, 'arch', None)
            default_fp = getattr(cfg, 'default_fp', None)

            self.device_info = {'backend': self.backend}

            if runtime_arch is not None:
                arch_name = getattr(runtime_arch, 'name', None) or str(runtime_arch)
                self.device_info['runtime_arch'] = arch_name

            if default_fp is not None:
                if default_fp == ti.f64:
                    self.device_info['default_fp'] = 'f64'
                elif default_fp == ti.f32:
                    self.device_info['default_fp'] = 'f32'

            # Try to get GPU info if available
            if self.backend in ['cuda', 'vulkan', 'opengl', 'metal']:
                try:
                    import torch
                    if torch.cuda.is_available():
                        self.device_info['gpu_name'] = torch.cuda.get_device_name(0)
                        self.device_info['gpu_memory_GB'] = torch.cuda.get_device_properties(0).total_memory / 1e9
                except ImportError:
                    pass

        except Exception as e:
            logger.warning(f"Could not detect device info: {e}")

    def _log_device_info(self):
        """Log device information."""
        logger.info("=" * 60)
        logger.info("Taichi Device Information:")
        for key, value in self.device_info.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 60)

    def get_backend(self) -> str:
        """Get current backend name."""
        return self.backend

    def is_gpu_backend(self) -> bool:
        """Check if current backend is GPU-based."""
        return self.backend in ['cuda', 'vulkan', 'opengl', 'metal']

    def get_device_info(self) -> dict:
        """Get device information dictionary."""
        return self.device_info.copy()

    @staticmethod
    def get_available_backends() -> list:
        """
        Get list of available backends on current system.

        Returns:
            List of available backend names
        """
        available = []
        was_initialized = False
        previous_arch = None

        # Preserve existing Taichi runtime state to avoid side effects
        # across test modules and user workflows.
        try:
            from taichi.lang import impl

            runtime = impl.get_runtime()
            was_initialized = runtime.prog is not None
            if was_initialized:
                previous_arch = impl.current_cfg().arch
        except Exception:
            pass

        # Check CUDA
        try:
            ti.init(arch=ti.cuda, offline_cache=False)
            available.append('cuda')
            ti.reset()
        except:
            pass

        # Check Vulkan
        try:
            ti.init(arch=ti.vulkan, offline_cache=False)
            available.append('vulkan')
            ti.reset()
        except:
            pass

        # Check Metal (macOS)
        try:
            ti.init(arch=ti.metal, offline_cache=False)
            available.append('metal')
            ti.reset()
        except:
            pass

        # CPU is always available
        available.append('cpu')

        # Restore previous runtime state if we interrupted an existing session.
        if was_initialized:
            try:
                if previous_arch is not None:
                    ti.init(arch=previous_arch, offline_cache=False)
                else:
                    ti.init(arch=ti.cpu, offline_cache=False)
            except Exception:
                try:
                    ti.init(arch=ti.cpu, offline_cache=False)
                except Exception:
                    pass

        return available

    @staticmethod
    def recommend_backend() -> str:
        """
        Recommend best backend for current system.

        Returns:
            Recommended backend name
        """
        available = BackendManager.get_available_backends()

        # Priority: CUDA > Vulkan > Metal > CPU
        if 'cuda' in available:
            return 'cuda'
        elif 'vulkan' in available:
            return 'vulkan'
        elif 'metal' in available:
            return 'metal'
        else:
            return 'cpu'


# Global backend manager instance
_backend_manager = None


def get_backend_manager() -> BackendManager:
    """Get global backend manager instance."""
    global _backend_manager
    if _backend_manager is None:
        _backend_manager = BackendManager()
    return _backend_manager


def initialize_taichi(backend: str = 'auto', **kwargs):
    """
    Convenience function to initialize Taichi.

    Args:
        backend: Backend name
        **kwargs: Additional arguments passed to BackendManager.initialize()
    """
    manager = get_backend_manager()
    manager.initialize(backend=backend, **kwargs)


def reset_taichi_runtime() -> None:
    """Release the process-local Taichi runtime and reset backend bookkeeping."""
    global _backend_manager, _RUNTIME_SIGNATURE
    with _RUNTIME_LOCK:
        try:
            ti.reset()
        finally:
            _RUNTIME_SIGNATURE = None
            if _backend_manager is not None:
                _backend_manager.backend = None
                _backend_manager.is_initialized = False
                _backend_manager.device_info = {}
                _backend_manager._runtime_signature = None


if __name__ == "__main__":
    # Test backend detection
    logging.basicConfig(level=logging.INFO)

    print("Available backends:")
    for backend in BackendManager.get_available_backends():
        print(f"  - {backend}")

    print(f"\nRecommended backend: {BackendManager.recommend_backend()}")

    # Test initialization
    manager = BackendManager()
    manager.initialize(backend='auto')
