# Project guidance

- Product display name: ACAね. Use ASCII names for code and paths.
- Read docs/requirements-v1.md, docs/progress.md and docs/validation.md before extending the project.
- Current scope is stage-one dataset preparation. Do not silently expand into training or the complete cover application.
- Never overwrite or delete original media. Keep source provenance, processing parameters and human review status.
- Audio, datasets and model weights stay outside Git. Default local data is workspace-data/ (ignored).
- Keep heavy model dependencies in an independent environment/process. Core metadata workflows should remain usable without them.
- Run `python -m unittest discover -s tests -v` with FFmpeg and ffprobe available.
- Distinguish adapter tests, actual model execution, subjective listening tests and Windows/GPU validation.
- Each cloud task already has an isolated checkout. Use the existing checkout; do not create a Git worktree unless explicitly requested.
- Keep progress, reproducible commands and outstanding validation updated for cross-computer handoff.
