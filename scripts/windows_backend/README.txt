ACAね：安装人声分离后端并验证本地 GPU 实际推理

已确认：Windows Python 3.12.10、PyTorch 2.8.0+cu128、RTX 5070 的矩阵和 FFT 检查通过。
此包继续使用已经安装好的 .venv-separation，不重新创建环境或升级 PyTorch。

1. 将本包完整解压到原来的 GPU 工具目录：
   D:\11bf\ACAne-GPU-Setup-v2\
   确认 Install_Separation.cmd 与原来的 Install_GPU.cmd、.venv-separation 在同一级。
2. 双击 Install_Separation.cmd，不需要管理员权限。
   下载和安装进度直接显示在窗口里，不要同时运行之前的安装工具。
3. 工具自动安装 audio-separator、ONNX Runtime GPU 及相关依赖，下载本地 FFmpeg（约 92 MB）
   和 RoFormer 权重（约 640 MB），随后运行 TAIDADA 的 10 秒原声样本。
   已有的 3.5 GB PyTorch 不会被主动重新安装；如果其版本与已验证版本不符，工具会先停止。
4. 完成后上传 backend-check-report.json，并试听 preview-results 中本次目录的 Vocals.mp3。
   如果安装失败，同时提供 backend-pip-log.txt。保留现有文件，无需重装显卡驱动。

样本是此前通过云端试听的同一段原声，模型、配置文件和分块参数保持一致。
GPU 计算的结果可能与 CPU 有细微差别，仍需本地试听。
工具核对模型和 FFmpeg 压缩包 SHA-256；不修改系统 PATH，不处理或覆盖原始素材。
此步骤仅完成一次 10 秒实际推理，不自动开展训练或整批分离。
Windows 后端安装和实际推理仍待本机验收，云端测试不能替代本机结果。

依赖来源：PyPI；FFmpeg：github.com/GyanD/codexffmpeg；模型：github.com/TRvlvr/model_repo。
