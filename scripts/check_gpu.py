"""Read-only environment report plus small CUDA matrix/FFT checks; no installs."""

import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys


def main():
    report = {
        "os": platform.system(),
        "python": platform.python_version(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "packages": {},
        "cuda_tensor_checks_passed": False,
        "model_inference_tested": False,
    }
    for package in ("torch", "torchvision", "audio-separator", "onnxruntime-gpu"):
        try:
            report["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][package] = None
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=20,
            )
            report["nvidia_smi"] = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            report["nvidia_smi_error"] = str(exc)
    try:
        import torch

        report["torch_cuda_version"] = torch.version.cuda
        report["cuda_available"] = torch.cuda.is_available()
        if report["cuda_available"]:
            report["device"] = torch.cuda.get_device_name(0)
            report["compute_capability"] = list(torch.cuda.get_device_capability(0))
            report["compiled_architectures"] = torch.cuda.get_arch_list()
            with torch.inference_mode():
                matrix = torch.ones((256, 256), device="cuda")
                product = matrix @ matrix
                matrix_ok = bool(torch.allclose(product, torch.full_like(product, 256)))
                signal = torch.randn((2, 4096), device="cuda")
                spectrum = torch.stft(signal, n_fft=2048, hop_length=512,
                                      window=torch.hann_window(2048, device="cuda"), return_complex=True)
                fft_ok = bool(torch.isfinite(spectrum).all())
                torch.cuda.synchronize()
                report["cuda_tensor_checks_passed"] = matrix_ok and fft_ok
    except Exception as exc:
        report["torch_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["cuda_tensor_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
