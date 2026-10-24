# 对照模型测试（诊断预览版）

解压到 `D:\11bf\ACAne-GPU-Setup-v2`（Start_ACAne.cmd 所在目录），双击 `Start_Control_Test.cmd`。原目录应保留 `test.wav`、现有 `.venv-training` 和第 30 轮模型。先停止其他 GPU 任务。

本工具不训练、不安装 Python 包、不上传音频。首次从 VCClient 作者发布的 Hugging Face 示例清单取得 `Tsukuyomi-chan_t` 的 PyTorch 声线模型；仅下载这一模型，不下载整个 VCClient。响应提供总大小时会在下载前显示 MiB，下载期间显示已下载量/速度。单文件设置 600 MiB 上限，不将它当作实际下载量。下载需本机能访问 Hugging Face；失败就停止，不绕过 TLS、不切不明镜像、不重装环境。

默认选 `test.wav` 的第 10～30 秒。需要换位置时编辑 `control-addon/settings.json` 的 start_s 和 duration_s（5～30 秒）。自动生成相同输入、同样 RMVPE/pitch=0、无索引的两版：ACAね 30e 和候选女声。两者都不使用各自索引，避免只给一方增加索引这一变量。固定随机种子；模型本身版本/采样率可能不同，会记录到 JSON，不声称架构完全一致。

结果自动打开在 `workspace-data/diagnostics/control_时间_编号`：

- `01_original_listen.wav`：测试原声片段。
- `02_acane30_listen.wav`：已有第 30 轮模型结果。
- `03_candidate_listen.wav`：候选女声模型结果。
- `report.json`：来源、输入/模型哈希、起止时间、参数、版本、静态增益与结果状态。

试听文件统一单声道 48 kHz，使用同一有效原声帧范围匹配 RMS，必要时所有文件一起降低增益以留峰值余量。不加 EQ/混响/压缩；这是电平匹配，不是完整感知响度匹配，听感仍可微调播放器音量。原始转换文件和原音频保留，输出每次独立目录。原文件超过测试范围不会被覆盖。

先比较自然度/清晰度，不要求候选声音像 ACAね。候选正常而 30e 明显较差，只提高“自训模型/数据”这一方向的优先级，不单凭一个异音色模型证明原因；两者都不好则核查推理路径，也需考虑候选模型本身是否适合歌唱。禁止把项目提供示例等同于“已验证优秀的歌唱基准”。

## 模型出处与限制

- 示例来源：[w-okada/voice-changer 固定提交的清单入口](https://github.com/w-okada/voice-changer/blob/d8ef15799470193f7c8176ef471245753a656626/server/const.py)。该项目采用 `wok000/vcclient_model` 清单并提供 Tsukuyomi-chan 样例。
- [作者项目说明、演示与素材署名](https://github.com/w-okada/voice-changer/blob/d8ef15799470193f7c8176ef471245753a656626/README_en.md)。说明中可见 Tsukuyomi-chan / CV. Yumesaki Rei 的素材来源及使用条件；具体所选模型的 credit/termsOfUseUrl 会在下载时显示并保存。
- 这是有出处的候选模型，不是独立试听验证过的歌唱基准。该项目的综合演示也不能等同于该权重在本测试歌声上的效果证明。云端未读取 HF 模型文件或验证它的歌唱表现；现有云端网络白名单不包含 Hugging Face，资源解析/下载留在用户本机完成。
- 首次通过正常 HTTPS 固定清单/模型提交，优先按 HF 文件元数据的 SHA-256 检查；若未提供则记录首次下载后的 SHA-256，后续复用时核对。不会将首次本地哈希称为第三方预审。
- 只接受可安全 weights_only 加载、带音高、标准 RVC v1/v2、HiFi-GAN、32/40/48 kHz、标准特征维度的模型。检查结构及有限权重，不把兼容检查当作音质验收。

当前只完成代码/合成音频测试；模型下载、Windows CUDA 转换和用户试听尚待本机执行。失败请发送 `control-test-log.txt` 及窗口最后几行，不要再次安装训练依赖。
