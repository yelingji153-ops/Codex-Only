# 公开案例检索：机械感与清晰度（2026-10-24）

检索渠道：GitHub 在线 issue 搜索与完整正文/评论，RVC-Project/Retrieval-based-Voice-Conversion-WebUI、IAHispano/Applio，并查询 w-okada/voice-changer。关键词 robotic、metallic、muffled、quality、pretrained。Applio 当前关闭 issue/discussion，能读取 PR；不能将没有命中解释为没有此类问题。以下为相关样例而非全网系统综述。

证据等级：维护者建议、用户自述改善、未解决报告、已合并代码变更分别记录。Issue closed 不等于修复成功，有些只是自动关闭。未下载/试听第三方案例音频，没有把其陈述当作独立复现结论。

| 来源 | 报告和处理结果 | 对本项目的意义 |
| --- | --- | --- |
| [RVC #2689](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/2689) | 高音女声；90 分钟分离素材不佳，换成 15 分钟自录干声仍机械；尝试 80～220 轮、索引开关、RMVPE/CREPE 仍不佳。用户称同环境使用第三方模型正常。尚无确认修复。 | 高度相似的症状；不能归咎于弹唱、轮数或单一 F0 算法。新增“已知表现良好的兼容模型”诊断对照，先区分转换环境与自训模型。这个对照本身不等于修复。 |
| [RVC #119](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/119) | 9 分钟干净歌声，S/呼吸有金属声。成员 fumiama 提醒小集合覆盖不足时更长训练会损失底模细节；另一用户自述由 48 kHz 改 40 kHz 并限制轮数后某些模型改善；另有用户称 de-esser 有效。没有统一受控实验。 | 我们已经 40 kHz，无需照抄重训；全段模糊与局部齿音不同，强 de-esser 可能进一步损伤清晰度。不能保证减少轮数或后期处理有效。 |
| [RVC #198，成员回复](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/198#issuecomment-1531359082) | 成员 RVC-Boss：好数据可受益于更多轮数，脏数据不应填很大轮数。讨论还有训练至 1000 轮仍有噪声的报告。 | 轮数要随数据与试听选，不能将 30 轮一律判为欠拟合。2023 年旧实现的具体数字不照搬 Applio。 |
| [RVC #2841，反馈修复的评论](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/2841#issuecomment-5268996353) | Windows DirectML/CPU，同参数旧版正常、新版差；用户称重新下载替换 modules.py 后恢复，附 DirectML 不支持混合正负 padding 的异常。 | 确有环境/实现导致差音质并被修复的用户报告。但我们是 NVIDIA CUDA + Applio，没有该异常，不能复制其文件替换办法。 |
| [RVC #2848](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/2848) | GTX 1060 3 GB、旧 Pascal、FP16/长音频蜂鸣；报告者自述强制 FP32 和改缓存后改善，无独立复现。 | 硬件/精度特定案例；我们 RTX 5070 12 GB、已用 FP32 路线，不应套用旧卡补丁或未知环境变量。 |
| [RVC #1630](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/issues/1630) | 用户描述像低码率音频，数千轮无改善；回复只是外部训练教程，issue 因不活跃自动关闭。 | 是问题报告，不是有效解法证据。 |
| [Applio PR #1315](https://github.com/IAHispano/Applio/pull/1315) | 已合并的 inference/formant/可选清理修改；PR 正文无具体测试结果（模板未填）。我们的固定源码已包含相应 cleanup CLI/模块。 | 不能凭标题声称升级或开启清理能修复问题，更不能将语音清理默认用于歌唱。 |

## 调整后的诊断顺序

1. 保存当前 30e 基线、现有输入和索引；保证模型/嵌入器/声码器/采样率匹配，确认原始训练确实成功加载预训练 G/D。若日志缺失，标为未知，不伪称未加载。
2. 对一个固定干净女声片段，在同一推理环境用具有可靠试听参考、来源可信、与当前 ContentVec/RVC v2/HiFi-GAN 兼容的另一模型做对照。比较是否仍发闷/机械，不评价它像不像 ACAね。模型尚未选定/下载，不能将随机第三方模型叫作“已知正常”。
3. 控制模型正常而自训模型差：优先审查训练集/原始预训练/特征缓存和实际分桶清单，必要时干净子集新实验。控制模型同样差：核查通用推理路径、输入/精度/版本；必要时同一模型在隔离的兼容引擎短段复现。两种结果都只改变嫌疑优先级，不构成因果证明。
4. 已安排的 RMVPE→CREPE 可以作为一次低成本单变量检查，不能承诺修复；相似案例中已经有人试过而无效。若无改善停止遍历。
5. 针对明确的 S/呼吸局部伪影才试温和去齿音并比较清晰度；用户报告是全段模糊，不先做这种后期处理。
6. 不凭论坛数字直接训练到数百轮、不因弹唱身份弃掉全库、不照搬其他 GPU 的参数/补丁、不重新安装一整套环境作为第一步。

具体可复现的实验记录、响度控制和数据审核沿用 quality-optimization-plan.md。没有查到可以保证同时修复当前机械感和清晰度的通用参数；检索带来的最重要新增项是控制模型/实现对照，而不是另一组随意参数。
