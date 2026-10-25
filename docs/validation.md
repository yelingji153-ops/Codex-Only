# 验证记录（2026-10-22）

## 当前云端环境

- Linux x86_64，Python 3.12.14，FFmpeg / ffprobe 7.1.5。
- 独立分离环境：`/workspace/acane-separation-env`。
- audio-separator 0.47.1、PyTorch 2.14.1+cpu、torchvision 0.29.1+cpu、
  ONNX Runtime 1.31.0。完整清单见根目录 CPU Linux requirements 文件。
- `pip check` 通过；`scripts/setup_cpu.sh` 在已安装环境上重跑成功。
  尚未在全新云任务上验证快照恢复。

## 自动测试

命令：`python -m unittest discover -s tests -v`。

结果：当前 32 项测试通过，0 失败、0 跳过（初版为 14 项）。

覆盖：原件字节不变、元数据、重复导入与来源关系、坏文件隔离、文件缺失、
数据库重开、归档损坏检测、资料库自身排除、WAV/FLAC/MP3/视频音轨、
无音轨视频拒绝、CSV 公式转义、命令行失败状态、任务超时与重试、
结果缓存及结果缺失后的重新处理、资料库复制后的相对路径。

其中分离缓存和超时测试使用明确的后端替身，仅测试任务控制逻辑。
测试文件由 FFmpeg 生成，不含用户正式素材。

## 真实分离后端冒烟测试

输入：本地生成的 3 秒、44.1kHz、双声道 440Hz 正弦信号。
模型：通过后端从上游下载的 `UVR_MDXNET_KARA_2.onnx`。
执行环境：CPU，`OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`。

```sh
python -m acane --library /workspace/acane-smoke-data import /tmp/acane-smoke-input
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python -m acane --library /workspace/acane-smoke-data separate --all --model UVR_MDXNET_KARA_2.onnx --python /workspace/acane-separation-env/bin/python --timeout 240
python -m acane --library /workspace/acane-smoke-data report
```

实际后端成功执行，产生 Vocals 和 Instrumental 两个可由 ffprobe 读取的 WAV，
均为 3 秒、44.1kHz、双声道；输出记录有 SHA-256。再次执行返回 `cached`，
成功导出 CSV 报告。当前实例证据保存在 `/workspace/acane-smoke-data`，不提交 Git。

这个测试证明模型下载、API 调用、音轨写入、元数据检查、任务持久化与结果复用能联通。
正弦信号不能检验歌手素材的分离质量、音色相似度、气声/高音保留或训练价值。

## 已解决的环境问题

1. Python 的默认构建配置指向不可用的 clang；显式使用现有 GCC/G++ 编译 diffq。
2. audio-separator 运行时直接引用 audioread，但当前解析的依赖不包含它；补充 3.1.0。
3. PyPI torchvision 与 CPU Torch 配套不一致，出现 `torchvision::nms` 缺失；
   改为从官方 CPU 索引安装对应 CPU torchvision，保留正常 TLS 验证。

这些问题已写入安装脚本或依赖声明；之前失败的任务记录保留用于追踪。

## 未验证

Windows 安装与图形界面、RTX 5070 CUDA/ONNX 加速、RoFormer 全批效果、
人工复核界面和训练集导出、声线训练、完整歌曲转换都尚未验收。
项目尚处第一阶段基础交付，不能把本记录理解为完整产品验收。

## 后续真实素材验证

第一批 5 个 MP3 已完成 MDX 分离，10 个音轨及试听包通过技术完整性检查，
但用户听后反馈多段伴奏残留明显。工程成功不能作为质量通过的依据。

随后对 TAIDADA 第 10–20 秒原声使用 BS-RoFormer 完成真实推理，用户明确反馈样本没问题。
参数为 segment_size=256、override_model_segment_size=True、overlap=2、batch_size=1，
云端 CPU 使用 4 线程，包含模型加载和写出共约 137 秒。
新旧试听版通过固定增益匹配 RMS，未额外降噪、EQ或动态压缩。
只验证了这段试听效果，尚未验收整批；没有声线训练或训练集导出。

参数传递、参数变化导致缓存隔离及非法参数拒绝均有单独测试。
GPU 检查脚本只检查设备、矩阵及 FFT 运算能力，不把它当作模型推理验收。

本地诊断脚本在云端 CPU 环境中正确报告 CUDA 不可用并返回非零状态。
用户已运行 Windows 检查入口：识别 RTX 5070、驱动 617.42、12227 MiB 显存，未找到 Python；尚未运行 CUDA 运算。

新增 GPU 安装入口：使用独立虚拟环境、固定 torch 2.8.0+cu128 / torchvision 0.23.0+cu128，
已查询 PyTorch 官方索引确认两者存在 CPython 3.12 Windows amd64 安装包。
安装脚本与此 GPU 组合尚未在 Windows 实机执行；等待本机安装及矩阵/FFT 检查报告。

用户首次执行安装入口仅得到 “The system cannot find the path specified.”，
尚不能据此确定具体路径或证明 Python/GPU 安装成功。V2 优先检查常见安装位置，
统一 Python 路径输出为 UTF-8，校验启动器退出码及文件存在性，增加分阶段路径日志。
Windows 路径修正仍待用户实机重试；没有进行 GPU 推理。

## 本地 GPU 基础检查已通过

用户回传 Windows Python 3.12.10，torch 2.8.0+cu128、torchvision 0.23.0+cu128；
RTX 5070 驱动 617.42，显存 12227 MiB，compute capability 12.0，编译架构包含 sm_120。
CUDA 矩阵与 FFT 检查成功；此时 FFmpeg、ffprobe 和 audio-separator 尚未安装，实际模型未测试。

新增后端准备脚本，固定当前 Torch 版本；采用 audio-separator[gpu] 0.47.1、
ONNX Runtime GPU 1.23.2、audioread 3.1.0。已核对 Windows CPython 3.12 的
diffq-fixed 和 ONNX Runtime GPU wheel 存在；尚未在 Windows 上完成整个依赖解析/安装。
FFmpeg 7.1.1 ZIP 已下载并通过 CRC、成员检查及 SHA-256 记录；未在云端执行 Windows 程序。
3 项新增测试覆盖校验后缓存复用、损坏文件不替换现有文件、禁止无 CUDA 时静默回退。
准备包内的 TAIDADA 10 秒原声和模型配置哈希与云端试听一致；GPU 实际模型推理待用户运行。

## 2026-10-23：人工审核和 WAV 导出

新增 11 项审核/导出测试，使用 FFmpeg 生成的短音频和明确标记的任务记录替身。
验证未通过/伴奏排除、音轨类型确认、按任务及哈希隔离审核、完整历史和 CSV 转义、
缺失/修改文件阻断、多个版本选择、失败转码清理、并发撤销阻止发布、旧库备份升级、
CLI 流程及非法路径拒绝。实际执行 WAV 转码，核对采样率、声道、时长与导出哈希。
这些测试证明流程约束，不证明真实歌声质量或训练效果。

用户素材没有被自动批准，也没有导出实际训练集。新功能为核心接口/命令行，
未实现图形试听界面，尚未在 Windows 本机验证导出。
本机分离后端安装在 samplerate 下载时发生 SSL EOF，不能将此前 CUDA 基础检查
视为实际模型验证。离线依赖包准备遇到上游 503，暂未形成可交付包。


## 2026-10-23：本地工作台与离线包（最新）

`python -m unittest discover -s tests -v`：45 项通过。新增上传接口、来源/原件保护、
环境阻断、活动任务去重、失败后重试、CUDA 参数传递、损坏模型阻断，
以及离线依赖哈希检查与禁止缺件时联网回退。队列推理使用替身，不代表真实 GPU 执行。

`python scripts/test_review_ui.py`：Chromium 浏览器通过多文件入口上传及重复导入、
真实合成 WAV 解码、原声偏移切换、审核保存/重开、备注文本转义、过期页冲突、
筛选及两页移动端宽度检查。HTTP 测试覆盖会话/来源校验、音频范围请求和哈希校验。
此前另外检查真实 MP3/PCM32 WAV 在 Chromium 中可解码；Windows 浏览器仍待验收。

离线包包含 61 个按 Windows CPython 3.12 条件解析的 wheel，
完整依赖版本条件经元数据核对，各 wheel SHA-256 和内部 CRC 已验证；
FFmpeg 7.1.1、BS-RoFormer 权重/配置及最终 ZIP 校验通过。
这证明归档完整性，不证明 Windows 安装或 RTX 5070 模型推理成功。
实际用户素材没有新增审核通过，也没有开始训练。


## 发布输入下载验证

新增下载器用本地文件源验证精确字节、已校验缓存复用和损坏内容阻断。
公开输入固定在 offline-wheels.json 与 download-manifest.json；实际构建结果以 GitHub Actions 记录为准。
此流程只打包发布，不增加 Windows/GPU 实机验证结论。


## 2026-10-23：切分与基础分析

完整自动测试 55 项通过。9 项切分测试覆盖已确认人声门槛、已知信号 RMS/峰值/低音量、
反相立体声不抵消、全静音、接近满幅、连续发声切点警告、精确采样值与来源时间、
非法/重叠边界、审核撤销、篡改阻断及并发撤销后清理；新增 HTTP 流程测试。
Chromium 用合成 WAV 实际检验分析、编辑起止时间、限定范围试听及保存 WAV，
核对片段时长/来源偏移和 pending 状态，含移动宽度检查。
没有对用户素材自动批准、切分或训练；未进行真实歌声切点听感及 Windows 验收。


## 2026-10-23：本机训练补充包

61 项 stdlib/FFmpeg 自动测试通过。新增全部批次选择、哈希去重、来源保留、原审核不改写、撤销阻断、篡改/越界阻断、复制时状态变化及短尾段保留测试。
另在云端 CPU 环境用合成 19.5 秒信号实际执行 FFmpeg 44.1→40 kHz 转换、均衡分段，核对输出 780000 帧、尾段未丢失；缺少特征及模型时校验器拒绝成功。
这是数据处理/适配验证，不是实际 RVC 特征提取、训练或听感验证。Windows 依赖安装、Hugging Face 下载、RTX 5070 模型前后向和 100 轮训练均未执行。
官方 PyTorch 索引确认 CPython 3.12 Windows torch/torchaudio 2.11.0+cu128 安装包存在；不等于全套依赖安装已通过。


下载进度修正：63 项测试通过，新增子进程终端继承/失败码保留及模型输出仍落日志的回归验证。实际 Windows 控制台渲染、PowerShell 临时文件观察器未执行，不把 mock 测试视为本机验收。


v0.1.2：63 项核心测试通过。另在 CPU 音频环境用 0.1 秒及 19.5 秒合成信号实际验证 FFmpeg 转换、短片排除记录、保留 780000 个训练采样、两次执行输出一致、源文件哈希不变，以及全短数据仍停止。没有进行真实 GPU 训练验证。


## 2026-10-24：用户本机证据与音频测量更新

用户截图显示 RTX 5070 本地环境完成第 30 轮/6270 步并导出模型、生成索引，实际转换成功。训练后期完整轮耗时约 47～71 秒。用户反馈相似度较第 10 轮改善，但机械感与清晰度不达标；技术完成不等于质量验收。

上传三份音频的 FFmpeg/soundfile/SciPy/librosa 测量见质量优化方案，分析脚本/JSON 留于云端 acane-results，不把音频提交 Git。原声 97.40 秒、输出 97.38 秒；输出 RMS 高约 9.27 dB。仅 16.34 秒双方高置信度音高帧可可靠对比，中位绝对差约 0.1 半音，不能据此排除全曲音高问题。上传的 88.65 秒训练人声没有满幅削波，单声道合并 RMS 损失约 0.014 dB；高频存在不能证明细节未损伤。未进行人工听感诊断或客观声纹相似度验证。

本轮为文档与代码查阅，无运行时代码变更，不重复跑整套应用测试；CREPE 对照、干净子集、条件续训和 BF16/批次加速均为待验证计划。


## 2026-10-24：对照测试入口

67 项自动测试通过，新增确切候选选择、下载源/路径限制、坏下载不覆盖缓存与缓存复用。CPU 音频环境用 FFmpeg 和合成信号实际验证统一声道/采样率、同范围静态 RMS 匹配、峰值余量、原输入不变、时长异常及全静音输出阻断。未在云端下载 HF 候选模型，未运行新神经推理或 Windows GPU 对照。项目默认示例的出处不等同于独立质量验证。


## 2026-10-24：训练只读检查

72 项测试通过，新增原录音区间并集/重叠、非法区间拒绝、日志证据缺失标未知、加载消息不等于成功、目录越界拒绝。另在现有 CPU 音频环境以合成 WAV、有限/NaN 特征及明确标记的模拟模型权重跑完整 audit：确认时长/分桶/重叠统计、坏特征报告，以及被检查目录所有文件 SHA-256 和文件集合均不变。该验证不是用户训练集的检查结论，也不是实际 GPU 模型验证。

## 2026-10-25：100 轮独立配方

新增音频环境 5 项检查通过：原件不变、组内统一衰减、续跑完整性、路径拒绝、配方保存与修改拒绝、已有未知检查点拒绝。实际解压的交付包完成模块导入及 30/50/70/100 轮选择/歧义拒绝检查。未运行 Windows GPU 新配方训练，不代表音质已改善。
