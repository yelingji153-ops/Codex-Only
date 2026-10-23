"""Executed only by the isolated ML environment; never fabricates validation."""
import json
from pathlib import Path
import sys


def verify(kind, root):
    import numpy as np
    if kind == 'gpu':
        import torch
        import torchaudio
        if torch.__version__ != '2.11.0+cu128' or torchaudio.__version__ != '2.11.0+cu128':
            raise RuntimeError('训练环境的 Torch/CUDA 版本不符。')
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA 不可用；已停止，不回退到 CPU 训练。')
        layer = torch.nn.Conv1d(8, 16, 3).cuda()
        x = torch.randn(2, 8, 1024, device='cuda', requires_grad=True)
        layer(x).square().mean().backward()
        torch.cuda.synchronize()
        if not torch.isfinite(x.grad).all():
            raise RuntimeError('CUDA 反向运算产生非有限值。')
        report = {'device': torch.cuda.get_device_name(0), 'torch': torch.__version__,
                  'cuda': torch.version.cuda, 'tensor_backward_passed': True, 'model_training_tested': False}
        (root/'gpu-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(report)
    elif kind in ('audio', 'features'):
        import soundfile as sf
        waves = sorted((root/'sliced_audios').glob('*.wav'))
        if not waves:
            raise RuntimeError('预处理未生成音频。')
        for wav in waves:
            data, rate = sf.read(wav)
            if rate != 40000 or data.ndim != 1 or len(data) < 16000 or not np.isfinite(data).all():
                raise RuntimeError(f'训练音频无效或短于 0.4 秒：{wav}')
            if kind == 'features':
                for path in (root/'extracted'/(wav.stem+'.npy'), root/'f0'/(wav.name+'.npy'), root/'f0_voiced'/(wav.name+'.npy')):
                    a = np.load(path, allow_pickle=False)
                    if not a.size or not np.isfinite(a).all():
                        raise RuntimeError(f'特征缺失或存在非有限值：{path}')
                    if path.parent.name == 'extracted' and (a.ndim != 2 or a.shape[1] != 768):
                        raise RuntimeError(f'ContentVec 特征维度错误：{path}')
        if kind == 'features':
            lines = (root/'filelist.txt').read_text(encoding='utf-8').splitlines()
            if len(lines) != len(waves) or len(set(lines)) != len(waves):
                raise RuntimeError('特征清单丢失或重复了训练片段。')
            expected = {p.resolve() for p in waves}
            if {Path(line.split('|')[0]).resolve() for line in lines} != expected:
                raise RuntimeError('特征清单与训练音频不符。')
        print(f'{kind}: {len(waves)} segments verified')
    elif kind.startswith('model'):
        import torch
        epoch = int(kind[5:])
        candidates = sorted(root.glob(f'{root.name}_*e_*s.pth'))
        valid = []
        for path in candidates:
            model = torch.load(path, map_location='cpu', weights_only=True)
            if int(model.get('epoch', 0)) < epoch:
                continue
            if int(model.get('step', 0)) <= 0 or model.get('sr') != 40000 or not model.get('f0'):
                raise RuntimeError(f'模型元数据无效：{path}')
            weights = model.get('weight', {})
            if not weights or any(not torch.isfinite(value).all() for value in weights.values()):
                raise RuntimeError(f'模型权重无效：{path}')
            valid.append(str(path))
        if not valid:
            raise RuntimeError(f'未找到完成至少 {epoch} 轮的有效声线模型。')
        if not list(root.glob('G_*.pth')) or not list(root.glob('D_*.pth')):
            raise RuntimeError('缺少续训检查点。')
        print('Validated models:', valid)
    elif kind == 'index':
        import faiss
        index = faiss.read_index(str(root/(root.name+'.index')))
        if index.d != 768 or index.ntotal <= 0:
            raise RuntimeError('索引无效或为空。')
        print('Index vectors:', index.ntotal)
    else:
        raise ValueError(kind)


if __name__ == '__main__':
    verify(sys.argv[1], Path(sys.argv[2]))
