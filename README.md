# ACAね AI 翻唱工作台

Windows 本地 AI 翻唱项目。当前版本 **0.1：第一阶段素材预处理基础流程**。
完整需求见 [需求书](docs/requirements-v1.md)，功能边界与后续计划见 [开发进度](docs/progress.md)。

当前支持批量导入、只读探测音频、原件副本归档、SHA-256 完全去重、SQLite 来源记录、
CSV 报告，以及独立进程中的可选人声分离后端。所有素材初始状态都是 `pending`。
目前是供开发和验证的命令行版本；图形界面、人工复核与训练集导出尚未实现。

## 基础运行

需要 Python 3.11 或以上（当前在 3.12 测试），以及在 PATH 中可用的 FFmpeg / ffprobe。
核心功能仅用 Python 标准库。在仓库目录直接运行，无需安装 Python 第三方包：

```sh
python -m acane doctor
python -m acane --library workspace-data import "你的素材目录" --kind singing --source-note "来源备注"
python -m acane --library workspace-data list
python -m acane --library workspace-data report
python -m unittest discover -s tests -v
```

Windows PowerShell 同样使用这些命令；如果 Python 命令为 `py -3.12`，替换命令开头即可。
资料库可以放到外部磁盘，例如 `--library "D:\ACAne_Data"`。
路径含空格时加引号。文件夹递归导入支持 WAV、FLAC、MP3、M4A、AAC、OGG、OPUS、WMA
以及 MP4、MKV、MOV、AVI、WebM；读取首条音轨。其他格式可通过显式文件路径尝试导入。

`--kind` 可选 `unknown`、`singing`、`speaking`、`accompanied`，当前由用户指定，不是自动识别。
重跑相同导入会复用原件并保留来源关系。损坏文件单独记录失败，其他文件继续处理。
同一录音的不同编码目前会作为不同素材保留；音频指纹去重列入后续开发。

## 可选人声分离

在独立虚拟环境安装后端，避免 AI 依赖影响基础素材管理：

```sh
python -m venv .venv-separation
# Linux CPU 环境；Windows 将 bin/python 替换为 Scripts/python.exe
.venv-separation/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv-separation/bin/python -m pip install "audio-separator[cpu]==0.47.1" "audioread==3.1.0"
.venv-separation/bin/audio-separator --list_models
python -m acane --library workspace-data separate --all --model UVR_MDXNET_KARA_2.onnx --python .venv-separation/bin/python
```

当前云端 Linux/Python 3.12 的完整版本清单在 `requirements-separation-cpu-linux.txt`。
可在仓库目录运行 `bash scripts/setup_cpu.sh` 重建或刷新已测试的 CPU 环境；
默认位置 `/workspace/acane-separation-env`，可用 `ACANE_SEPARATION_ENV` 指定其他位置。
该脚本需要 FFmpeg、GCC/G++，通过显式设置编译器解决 `diffq` 的源码扩展构建问题。
CPU 版 Torch 和 torchvision 必须匹配，避免 `torchvision::nms` 算子加载失败。
此版本清单仅对应云端 Linux CPU 环境，不是 Windows GPU 锁文件。

`UVR_MDXNET_KARA_2.onnx` 是工程联通测试候选，不代表对 ACAね 素材的最佳选择。
实际批量试听已表明该模型对这批弹唱的伴奏残留过多，不应继续作为默认训练素材处理方案。
模型名必须来自后端支持列表，首次使用需要下载模型。切换模型名会建立独立处理版本。
只处理单条素材时，用 `--asset <list 输出中的完整 id>` 替代 `--all`。
成功结果文件校验通过时再次调用会返回 `cached`；`--force` 可生成新版本，保留旧结果。
默认每条素材分离超时 3600 秒，可用 `--timeout` 调整。失败后重跑同一命令即可重试。
进程被强制终止可能留下 `running` 的历史记录和部分文件；重跑会创建新任务，
不会把这类记录当作成功，也不会复用部分结果。

RTX 5070 的 GPU 环境需要另行验证驱动、PyTorch CUDA 架构支持及 ONNX Runtime provider。
CPU 安装命令不能用作 GPU 配置。当前不提供未经本地验证的“一键 GPU 安装”承诺。
模型权重使用条件需逐个核实；代码许可证不能自动代表所有权重的许可。

## 已通过短片试听的 BS-RoFormer 配置

当前通过用户试听的是同一素材的 10 秒 BS-RoFormer 样本。下面的分块设置与该样本一致：

```sh
python -m acane --library workspace-data separate --all --model model_bs_roformer_ep_317_sdr_12.9755.ckpt --segment-size 256 --overlap 2 --python .venv-separation/bin/python --timeout 14400
```

Windows 使用分离环境的 `.venv-separation\Scripts\python.exe` 作为 `--python` 值。
命令必须指向已经配置好的分离环境；本仓库目前尚未验证 Windows GPU 安装组合。
指定分块帧数时自动开启模型分块覆盖，批次为 1。参数进入任务记录和结果缓存键，
改变分块或重叠设置会创建独立结果，不会误用旧参数结果。

在目标 Windows 电脑先执行 `py -3.12 scripts/check_gpu.py`，或用已有 AI 环境的 Python
执行该脚本。它报告驱动、CUDA 可见性及依赖版本，并尝试小规模 CUDA 矩阵和 FFT 运算。
不安装或改动系统软件；不读取密钥。它通过也不代表整个分离模型已验证，仍需做真实短片推理。

这套配置在云端 CPU 上处理 10 秒样本约需 137 秒（含加载和写入），
11 分钟整批粗估约 2–3 小时，实际随素材和负载变化。RTX 5070 实测速度尚未知。
短片试听通过不等于整批训练素材已通过；完整结果仍需逐条复核。

## 文件与跨电脑交接

```text
资料库/
  library.sqlite3       # 元数据、来源、待复核状态、处理记录
  originals/            # 按 SHA-256 命名的原始字节副本
  preprocessing/<任务ID>/ # 工作副本、分离结果、输出清单、日志
  reports/              # 每次导入结果及独立版本的 CSV 报告
  models/               # 分离模型缓存
```

原始输入文件不修改、不删除；资料库原件也不会被处理结果覆盖。
如归档副本损坏，程序会报错并要求恢复备份，不会静默覆盖。
同一文件不同来源会记录在 sources；导出 CSV 对公式前缀做转义。

代码、需求和开发记录进 Git；音频、模型、数据集放在仓库外，或默认被忽略的
`workspace-data/` 内。**不要把真实素材目录放进其他未忽略的仓库子目录。**
结束开发时提交并推送代码。资料库需要单独备份，先停止处理，再复制整个资料库目录
（包括 SQLite 文件），换电脑后用新的 `--library` 路径打开。记录中的历史来源绝对路径
仅用于追溯；已归档原件和结果使用相对路径，可随资料库移动。
虚拟环境不跨操作系统复制，应按说明重建。

云端环境发布保存开发环境；GitHub 保存已推送代码；个人素材备份需要单独管理。
当前云端测试不能证明 Windows 桌面和 RTX 5070 已通过验收。

Windows 首次准备：先安装官方 Python 3.12 64 位，再运行 `scripts/setup_gpu_windows.cmd`。
它会在脚本旁创建独立环境并安装 GPU PyTorch；具体步骤及安装范围见
[scripts/GPU_SETUP_README.txt](scripts/GPU_SETUP_README.txt)。该安装入口尚待 Windows 实机验证。
