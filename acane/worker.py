"""Executed by a separately configured inference Python interpreter."""

import json
import os
import sys
from pathlib import Path


def main():
    from audio_separator.separator import Separator

    require_cuda = os.environ.get('ACANE_REQUIRE_CUDA') == '1'
    if require_cuda:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA is unavailable; this local GPU task will not fall back to CPU.')

    source, output_dir, model_dir, model, manifest = sys.argv[1:6]
    options = {"mdxc_params": json.loads(sys.argv[6])} if len(sys.argv) > 6 else {}
    separator = Separator(output_dir=output_dir, model_file_dir=model_dir, output_format="WAV", **options)
    separator.load_model(model_filename=model)
    if require_cuda:
        instance = separator.model_instance
        if instance.torch_device.type != 'cuda' or next(instance.model_run.parameters()).device.type != 'cuda':
            raise RuntimeError('The separation model is not on CUDA.')
    files = separator.separate(source)
    paths = []
    for name in files:
        path = Path(name)
        if not path.is_absolute():
            path = Path(output_dir) / path
        paths.append(str(path.resolve()))
    Path(manifest).write_text(json.dumps(paths), encoding="utf-8")


if __name__ == "__main__":
    main()
