"""Executed by a separately configured inference Python interpreter."""

import json
import sys
from pathlib import Path


def main():
    from audio_separator.separator import Separator

    source, output_dir, model_dir, model, manifest = sys.argv[1:]
    separator = Separator(output_dir=output_dir, model_file_dir=model_dir, output_format="WAV")
    separator.load_model(model_filename=model)
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
