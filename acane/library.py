"""Content-addressed original copies, provenance and persistent job history."""

import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .media import MediaError, digest, extract_audio, probe

EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus",
              ".wma", ".mp4", ".mkv", ".mov", ".avi", ".webm"}
KINDS = ("unknown", "singing", "speaking", "accompanied")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Library:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in ("originals", "preprocessing", "reports", "models"):
            (self.root / directory).mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError(f"不支持数据库版本 {version}，请使用匹配的软件版本。")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, original_path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL, bytes INTEGER NOT NULL,
                duration REAL NOT NULL, sample_rate INTEGER NOT NULL,
                channels INTEGER NOT NULL, codec TEXT NOT NULL,
                audio_stream INTEGER NOT NULL, kind TEXT NOT NULL,
                review TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                asset_id TEXT NOT NULL REFERENCES assets(id), path TEXT NOT NULL,
                source_note TEXT NOT NULL, imported_at TEXT NOT NULL,
                PRIMARY KEY(asset_id, path, source_note)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
                operation TEXT NOT NULL, parameters TEXT NOT NULL, status TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT, outputs TEXT, error TEXT
            );
            PRAGMA user_version=1;
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def assets(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM assets ORDER BY created_at, id")]

    def asset(self, asset_id):
        row = self.db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            raise ValueError(f"素材不存在：{asset_id}")
        return dict(row)

    def discover(self, inputs):
        seen = set()
        for raw in inputs:
            path = Path(raw).expanduser().resolve()
            if path.is_relative_to(self.root):
                raise ValueError("请导入素材来源目录，不能导入资料库自身。")
            if not path.exists():
                yield path
                continue
            if path.is_dir():
                def walk_error(error):
                    raise error
                for directory, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
                    dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).resolve().is_relative_to(self.root))
                    for name in sorted(files):
                        candidate = (Path(directory) / name).resolve()
                        if (candidate.suffix.lower() in EXTENSIONS and candidate not in seen
                                and not candidate.is_relative_to(self.root)):
                            seen.add(candidate)
                            yield candidate
            elif path not in seen:
                seen.add(path)
                yield path

    def import_one(self, source: Path, kind="unknown", source_note=""):
        if kind not in KINDS:
            raise ValueError("未知素材分类。")
        source = source.resolve()
        if source.is_relative_to(self.root):
            raise ValueError("不能导入资料库自身。")
        # Copy once to a unique staging file. Identity and metadata describe the
        # same bytes even if the external source changes during the operation.
        fd, temporary = tempfile.mkstemp(prefix=".import-", suffix=source.suffix.lower(),
                                         dir=self.root / "originals")
        os.close(fd)
        temporary = Path(temporary)
        try:
            shutil.copyfile(source, temporary)
            asset_id = digest(temporary)
            metadata = probe(temporary)
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                existing = self.db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
                if existing:
                    original = self.root / existing["original_path"]
                    if not original.is_file() or digest(original) != asset_id:
                        raise MediaError("已归档原件缺失或被修改；请先恢复备份，未覆盖文件。")
                    status = "duplicate"
                else:
                    relative = Path("originals") / f"{asset_id}{source.suffix.lower()}"
                    target = self.root / relative
                    if target.exists():
                        if digest(target) != asset_id:
                            raise MediaError("归档路径有不同内容，未覆盖文件。")
                    else:
                        os.replace(temporary, target)
                    values = (asset_id, relative.as_posix(), source.name, target.stat().st_size,
                              metadata["duration"], metadata["sample_rate"], metadata["channels"],
                              metadata["codec"], metadata["audio_stream"], kind, now())
                    self.db.execute("""INSERT INTO assets
                        (id,original_path,filename,bytes,duration,sample_rate,channels,codec,audio_stream,kind,created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", values)
                    status = "imported"
                self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?)",
                                (asset_id, str(source), source_note, now()))
            return {"path": str(source), "id": asset_id, "status": status}
        finally:
            temporary.unlink(missing_ok=True)

    def import_batch(self, inputs, kind="unknown", source_note=""):
        results = []
        for path in self.discover(inputs):
            try:
                results.append(self.import_one(path, kind, source_note))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                results.append({"path": str(path), "status": "failed", "error": str(exc)})
        self.write_json(self.root / "reports" / f"import-{uuid.uuid4().hex}.json", results)
        return results

    @staticmethod
    def write_json(path, data):
        # Paths are unique per operation; never overwrite historical reports.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)

    def report(self):
        directory = self.root / "reports" / uuid.uuid4().hex
        directory.mkdir()
        queries = {
            "assets": "SELECT * FROM assets ORDER BY created_at, id",
            "sources": "SELECT * FROM sources ORDER BY asset_id, path",
            "duplicates": """SELECT * FROM sources WHERE asset_id IN
                (SELECT asset_id FROM sources GROUP BY asset_id HAVING COUNT(DISTINCT path)>1)
                ORDER BY asset_id, path""",
            "jobs": "SELECT * FROM jobs ORDER BY started_at",
        }
        for name, query in queries.items():
            cursor = self.db.execute(query)
            with (directory / f"{name}.csv").open("x", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([column[0] for column in cursor.description])
                for row in cursor:
                    # Guard spreadsheet formula interpretation of filenames/notes.
                    writer.writerow(["'" + value if isinstance(value, str) and
                                     value.lstrip().startswith(("=", "+", "-", "@")) else value for value in row])
        return directory

    def separate(self, asset_id, model, python=sys.executable, timeout=3600, force=False, mdxc_params=None):
        if not model or Path(model).name != model or any(c in model for c in ("/", "\\", ":")):
            raise ValueError("模型必须是后端模型目录中的文件名，不能包含路径。")
        if timeout <= 0:
            raise ValueError("超时必须大于零。")
        if mdxc_params is not None:
            allowed = {"segment_size", "override_model_segment_size", "overlap", "batch_size"}
            if not isinstance(mdxc_params, dict) or set(mdxc_params) - allowed:
                raise ValueError("不支持的 MDXC 参数。")
            mdxc_params = dict(mdxc_params)
            for key, value in mdxc_params.items():
                if key == "override_model_segment_size":
                    valid = isinstance(value, bool)
                else:
                    valid = type(value) is int and value >= (2 if key == "segment_size" else 1)
                if not valid:
                    raise ValueError(f"MDXC 参数无效：{key}")
        asset = self.asset(asset_id)
        original = self.root / asset["original_path"]
        if digest(original) != asset_id:
            raise MediaError("原件校验失败，未启动处理。")
        # Include installed backend version in the cache key. Dependency changes
        # must not silently reuse a result from an older backend.
        version = subprocess.run([str(python), "-c", "from importlib.metadata import version; print(version('audio-separator'))"],
                                 capture_output=True, text=True, timeout=30)
        if version.returncode:
            raise ValueError("指定的 Python 未安装 audio-separator。请按 README 配置独立分离环境。")
        settings = {"model": model, "backend": "audio-separator",
                    "version": version.stdout.strip(), "format": "WAV",
                    "input": "first-audio-stream-float32"}
        if mdxc_params:
            settings["mdxc_params"] = mdxc_params
        parameters = json.dumps(settings, sort_keys=True)
        if not force:
            rows = self.db.execute("""SELECT * FROM jobs WHERE asset_id=? AND parameters=?
                AND status='succeeded' ORDER BY started_at DESC""", (asset_id, parameters))
            for row in rows:
                outputs = json.loads(row["outputs"])
                if outputs and all((self.root / item["path"]).is_file() and
                                   digest(self.root / item["path"]) == item["sha256"] for item in outputs):
                    return {"id": row["id"], "status": "cached", "outputs": outputs}
        job_id = uuid.uuid4().hex
        directory = self.root / "preprocessing" / job_id
        directory.mkdir()
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,NULL,NULL,NULL)",
                            (job_id, asset_id, "separate", parameters, "running", now()))
        try:
            inference_input = directory / "input.wav"
            extract_audio(original, inference_input)
            manifest = directory / "outputs.json"
            worker = Path(__file__).with_name("worker.py")
            command = [str(python), str(worker), str(inference_input),
                       str(directory), str(self.root / "models"), model, str(manifest)]
            if mdxc_params:
                command.append(json.dumps(mdxc_params, sort_keys=True))
            with (directory / "backend.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            if result.returncode:
                raise MediaError(f"分离失败，退出码 {result.returncode}；查看 {directory / 'backend.log'}")
            paths = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(paths, list) or not paths:
                raise MediaError("分离后端没有输出音频。")
            outputs = []
            for filename in paths:
                path = Path(filename).resolve()
                if not path.is_relative_to(directory) or path == inference_input:
                    raise MediaError("分离后端返回了不合法的输出路径。")
                metadata = probe(path)
                if abs(metadata["duration"] - asset["duration"]) > max(0.5, asset["duration"] * 0.01):
                    raise MediaError("分离结果时长与输入不符，未标记为成功。")
                outputs.append({"path": path.relative_to(self.root).as_posix(),
                                "sha256": digest(path), **metadata})
            with self.db:
                self.db.execute("UPDATE jobs SET status='succeeded',finished_at=?,outputs=? WHERE id=?",
                                (now(), json.dumps(outputs), job_id))
            return {"id": job_id, "status": "succeeded", "outputs": outputs}
        except (Exception, KeyboardInterrupt) as exc:
            with self.db:
                self.db.execute("UPDATE jobs SET status='failed',finished_at=?,error=? WHERE id=?",
                                (now(), str(exc) or type(exc).__name__, job_id))
            raise
