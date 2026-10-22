#!/usr/bin/env bash
# Tested target: Linux x86_64, Python 3.12. FFmpeg, GCC/G++ are prerequisites.
set -euo pipefail
cd "$(dirname "$0")/.."
python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Use Python 3.12 for the tested CPU environment"'
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v gcc >/dev/null
command -v g++ >/dev/null
SEP_ENV="${ACANE_SEPARATION_ENV:-/workspace/acane-separation-env}"
python -m venv "$SEP_ENV"
export CC=gcc
export CXX=g++
"$SEP_ENV/bin/python" -m pip install 'torch==2.14.1+cpu' 'torchvision==0.29.1+cpu' --index-url https://download.pytorch.org/whl/cpu
"$SEP_ENV/bin/python" -m pip install -r requirements-separation-cpu-linux.txt
"$SEP_ENV/bin/python" -m pip check
"$SEP_ENV/bin/python" -c 'from audio_separator.separator import Separator; import torch, torchvision; print("Separation backend imports OK; torch", torch.__version__)'
python -m acane doctor
python -m unittest discover -s tests -v
