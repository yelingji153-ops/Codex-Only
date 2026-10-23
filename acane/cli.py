import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from .library import KINDS, Library
from .review import DECISIONS, ROLES, SAMPLE_RATES


def main(argv=None):
    parser = argparse.ArgumentParser(description="ACAね 素材预处理工具（第一阶段）")
    parser.add_argument("--library", type=Path, default=Path("workspace-data"), help="独立素材资料库目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="检查基础音频工具")
    commands.add_parser("list", help="列出素材元数据")
    commands.add_parser("report", help="导出 CSV 报告")
    interface = commands.add_parser("serve", help="启动本机浏览器试听与复核界面")
    interface.add_argument("--port", type=int, default=8765, help="本机端口；0 表示自动分配")
    interface.add_argument("--no-browser", action="store_true", help="只显示链接，不自动打开浏览器")
    interface.add_argument("--backend-python", help="分离环境的 Python；默认使用程序旁的 .venv-separation")
    commands.add_parser("review-list", help="列出每份处理结果及其人工审核状态")
    history = commands.add_parser("review-history", help="查看不可覆盖的审核历史")
    history.add_argument("--job", help="只查看该任务")
    review = commands.add_parser("review", help="人工记录具体输出的审核决定")
    review.add_argument("--job", required=True, help="任务 ID")
    review.add_argument("--output", required=True, help="review-list 中的完整相对输出路径")
    review.add_argument("--decision", choices=DECISIONS, required=True)
    review.add_argument("--role", choices=ROLES, default="unknown", help="通过前必须明确音轨类型")
    review.add_argument("--note", default="", help="试听评价和修改原因")
    exporter = commands.add_parser("export", help="只导出明确通过的人声，创建独立版本的 WAV 数据集")
    exporter.add_argument("--job", action="append", help="选择任务；可重复指定，默认所有通过的人声")
    exporter.add_argument("--sample-rate", type=int, choices=SAMPLE_RATES, help="不指定则保持各音轨采样率")
    exporter.add_argument("--channels", type=int, choices=(1, 2), help="不指定则保持各音轨声道数")
    importer = commands.add_parser("import", help="导入文件或目录，保存原件副本")
    importer.add_argument("paths", nargs="+", type=Path)
    importer.add_argument("--kind", choices=KINDS, default="unknown")
    importer.add_argument("--source-note", default="", help="来源、录制信息等备注")
    separation = commands.add_parser("separate", help="调用独立环境中的人声分离后端")
    selection = separation.add_mutually_exclusive_group(required=True)
    selection.add_argument("--asset", help="完整素材 SHA-256 ID")
    selection.add_argument("--all", action="store_true", help="处理全部已导入素材")
    separation.add_argument("--model", required=True, help="audio-separator 支持的完整模型文件名")
    separation.add_argument("--python", default=sys.executable, help="分离环境中的 Python 路径")
    separation.add_argument("--timeout", type=int, default=3600)
    separation.add_argument("--segment-size", type=int, help="RoFormer/MDXC 分块帧数；指定后覆盖模型默认值")
    separation.add_argument("--overlap", type=int, help="RoFormer/MDXC 重叠窗口数")
    separation.add_argument("--force", action="store_true", help="保留旧结果并生成新的处理版本")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .webapp import serve
            serve(args.library, args.port, not args.no_browser, args.backend_python)
            return 0
        if args.command == "doctor":
            data = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
            data["python"] = sys.version.split()[0]
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0 if data["ffmpeg"] and data["ffprobe"] else 1
        with Library(args.library) as library:
            if args.command == "import":
                data = library.import_batch(args.paths, args.kind, args.source_note)
                failed = not data or any(item["status"] == "failed" for item in data)
            elif args.command == "list":
                data, failed = library.assets(), False
            elif args.command == "report":
                data, failed = {"report_dir": str(library.report())}, False
            elif args.command == "review-list":
                data, failed = library.review_queue(), False
            elif args.command == "review-history":
                data, failed = library.review_history(args.job), False
            elif args.command == "review":
                data = library.review_output(args.job, args.output, args.decision, args.role, args.note)
                failed = False
            elif args.command == "export":
                data = library.export_dataset(args.job, args.sample_rate, args.channels)
                failed = False
            else:
                mdxc_params = None
                if args.segment_size is not None or args.overlap is not None:
                    mdxc_params = {"batch_size": 1}
                    if args.segment_size is not None:
                        mdxc_params.update(segment_size=args.segment_size, override_model_segment_size=True)
                    if args.overlap is not None:
                        mdxc_params["overlap"] = args.overlap
                ids = [asset["id"] for asset in library.assets()] if args.all else [args.asset]
                data = []
                for asset_id in ids:
                    try:
                        data.append(library.separate(asset_id, args.model, args.python, args.timeout, args.force,
                                                     mdxc_params=mdxc_params))
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        data.append({"asset": asset_id, "status": "failed", "error": str(exc)})
                failed = not data or any(item["status"] == "failed" for item in data)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 1 if failed else 0
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
