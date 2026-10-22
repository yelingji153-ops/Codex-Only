# 技术调研记录（2026-10-22）

这是一轮基于上游文档与包元数据的初查，兼容性结论以本地测试为准。

| 项目 | 已核实的信息 | 当前决策 |
|---|---|---|
| [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) | PyPI 当前版本 0.47.1，Python >=3.10（排除 3.14.1），MIT；公开 Separator/load_model/separate API；包含 MDX、VR、Demucs、MDXC 路线 | 首个可替换分离后端，独立环境运行 |
| [UVR](https://github.com/Anjok07/ultimatevocalremovergui) | 当前 README 标明 GUI 代码 MIT；Windows 手工安装说明仍提及较老 Python | 作为模型和试听对照来源；不直接采用旧整合包作为 5070 环境 |
| [MSST](https://github.com/ZFTurbo/Music-Source-Separation-Training) | README 提供训练、推理和 Python API 文档；LICENSE 为 MIT | 后续比较 RoFormer 模型和参数的候选 |
| [Applio](https://github.com/IAHispano/Applio) | README 标明代码及仓库内模型 MIT，同时指向其使用条款 | 阶段二的 RVC 路线候选，不在当前阶段启动训练 |
| [Seed-VC](https://github.com/Plachtaa/seed-vc) | 仓库 LICENSE 为 GPL-3.0 | 对照路线；集成和分发前需评估 GPL 要求以及具体权重许可 |

上述来源通过 HTTPS 正常读取；audio-separator 版本来自
[PyPI 元数据](https://pypi.org/pypi/audio-separator/json)。
PyPI 记录 0.47.1 于 2026-10-19 发布，这是近期发布活动的证据。
仓库 README/代码可访问，但 GitHub API 请求被当前网络策略以 403 拒绝，
未核实最后提交日期、近期 issue 响应或维护活跃程度，不将“可下载”写成“维护良好”。

## RTX 5070 / Windows

已知目标是 Blackwell、12GB 显存。仅满足包声明的 `torch>=2.3` 不足以证明该显卡兼容。
这次无法读取 PyTorch 网站的 2.7 公告（代理 403），也未获得用户 Windows 环境信息。
后续应在目标电脑记录：

1. NVIDIA 驱动版本、实际 CUDA 可见性、设备名称与 compute capability。
2. `torch.__version__`、`torch.version.cuda`、`torch.cuda.get_arch_list()`。
3. 实际 CUDA 张量运算、模型前向、显存峰值和完整短音频推理。
4. 对 ONNX 模型，单独验证 ONNX Runtime CUDA provider 的可用性与实际执行。

PyTorch、ONNX Runtime 和不同模型后端的 GPU 支持应分别实测。
先顺序执行单任务，再按实测调节批次/分块，不把 12GB 直接换算成固定安全 batch size。
当前云端 CPU 工程验证不建立 GPU 兼容性结论。

## 音频质量分析路线

第一批可解释指标可由 FFmpeg 和数值分析实现：时长、声道、峰值、均方根音量、
接近满幅采样比例和基于阈值的静音区间。必须记录阈值、分析版本与局限，
接近满幅不能单独证明削波，低音量也不能单独证明素材不可用。

乐器残留、混响、分离伪影、多人声、歌唱/讲话区分需要额外方法与真实标注样本验证。
音高可比较 librosa/成熟 F0 提取器，对气声、假声和伴奏残留设置不确定状态。
目前尚未选择和验收这些算法，不生成虚假的综合质量分数。

## 许可证与模型

代码许可证、预训练权重许可和素材使用条件分别记录。每个候选模型应保存来源 URL、
文件指纹、版本、许可依据、参数和听感对照。当前后端自动下载的模型缓存不提交到 Git。
用于工程测试的合成信号不等于正式训练素材，也不代表任何歌手的分离或声线效果。
