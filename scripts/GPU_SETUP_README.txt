V2 路径检测修正版：已安装 Python 的用户无需重装。
将本包解压到上次使用的同一文件夹，替换工具文件后重新运行 Install_GPU.cmd。
保留原有 .venv-separation 文件夹；新版会尝试复用。失败时上传新版 gpu-setup-log.txt。

ACAね Windows GPU 环境准备

首次报告已识别 RTX 5070 及驱动，但没有找到可用的 Python。

1. 从 Python 官网安装 Python 3.12.10 的 Windows installer (64-bit)：
   https://www.python.org/downloads/release/python-31210/
   直达安装程序：https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
   使用默认的当前用户安装；保留 pip 与 Python Launcher 选项。
   可以勾选 Add python.exe to PATH，然后点击 Install Now。
2. 把本包完整解压到长期保留的文件夹，例如 D:\ACAne-GPU。
3. 双击 Install_GPU.cmd，等待完成。无需以管理员身份运行。
4. 将 gpu-check-report.txt 上传回聊天。如果失败，同时上传 gpu-setup-log.txt。

本工具会联网下载并安装软件，不是上一版的只读检查工具。
它在解压目录的 .venv-separation 中安装 torch 2.8.0+cu128 和 torchvision 0.23.0+cu128，
使用 PyTorch 官方 CUDA 12.8 索引，不修改显卡驱动，不需要单独安装 CUDA Toolkit。
下载量较大，建议预留约 10 GB 磁盘空间；安装详情持续写入 gpu-setup-log.txt。
失败后可以在同一文件夹重新运行；日志保留本次结果，发回前请勿反复运行。
安装后保留文件夹原位置，虚拟环境不能直接移动到另一目录或另一台电脑。

此次只验证 PyTorch 的 GPU 矩阵与 FFT 运算。
FFmpeg 和 audio-separator 尚未安装，报告中显示缺少它们是正常的。
收到报告后再配置人声分离后端，并验证已通过试听的 RoFormer 模型。
云端已核对官方 Windows 安装包索引；此安装入口尚未在 Windows 实机验收。
