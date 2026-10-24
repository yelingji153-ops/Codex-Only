"""Read-only training audit. Writes only a new report directory; no network/GPU."""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parent.parent
EXPERIMENT_ID='acane_38f8801be33b8849'
BACKEND_COMMIT='c817f1f83f689ef72e0dfeb1c17ae990b9248506'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def inside(root,value):
    path=(root/value).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Path outside allowed training directory')
    return path


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def overlap_summary(records):
    groups={};total=0.0
    for row in records:
        left=float(row['original_start_s']);right=float(row['original_end_s'])
        if not math.isfinite(left) or not math.isfinite(right) or left<0 or right<=left:
            raise ValueError('Invalid source interval')
        groups.setdefault(row['original_id'],[]).append((left,right));total+=right-left
    union=0.0;overlap_sources=[]
    for source,intervals in groups.items():
        merged=[]
        for left,right in sorted(intervals):
            if merged and left<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],right)
            else:merged.append([left,right])
        duration=sum(b-a for a,b in merged);union+=duration
        excess=sum(b-a for a,b in intervals)-duration
        if excess>.001:overlap_sources.append({'original_id':source,'excess_seconds':excess})
    return {'source_count':len(groups),'summed_source_seconds':total,'unique_source_seconds':union,
            'overlap_excess_seconds':max(0,total-union),'overlapping_sources':overlap_sources,
            'limitation':'Only identical original IDs; different encodes of the same recording may remain undetected.'}


def log_evidence(text):
    patterns={'pretrained_G':"Loaded pretrained (G)",'pretrained_D':"Loaded pretrained (D)",
              'pretrained_mismatch':'parameters of the pretrain model',
              'pitch_cpu_fallback':'Falling back to CPU','pitch_failure':'error extracting file',
              'feature_failure':'produced NaN','resume':'Loaded checkpoint',
              'completion':'Training has been successfully completed'}
    result={key:[] for key in patterns}
    for number,line in enumerate(text.splitlines(),1):
        for key,pattern in patterns.items():
            if pattern.lower() in line.lower():
                # Keep historical line references, not user-identifying absolute paths.
                epoch=re.search(r'epoch\s*(\d+)',line,re.I)
                result[key].append({'line':number,'epoch':int(epoch.group(1)) if epoch else None})
    result['initial_pretrained_load_status']='messages_present_not_proof_of_success' if result['pretrained_G'] and result['pretrained_D'] else 'unknown_no_complete_log_evidence'
    result['limitation']='Historical matches may belong to earlier failed attempts. Missing logs do not prove pretrained weights were absent.'
    return result


def audio_metrics(path):
    import numpy as np
    import soundfile as sf
    y,sr=sf.read(path,dtype='float32',always_2d=True)
    if not y.size or not np.isfinite(y).all():raise ValueError('Empty or nonfinite audio')
    rms=float(np.sqrt(np.mean(y.astype('float64')**2)));peak=float(np.max(np.abs(y)))
    mono=y.mean(axis=1);window=max(1,int(sr*.02));count=len(y)//window
    frame=np.sqrt(np.mean(mono[:count*window].reshape(count,window).astype('float64')**2,axis=1)) if count else np.array([])
    return {'frames':len(y),'sample_rate':sr,'channels':y.shape[1],'subtype':sf.info(path).subtype,
            'duration_s':len(y)/sr,'rms_dbfs':20*math.log10(max(rms,1e-12)),
            'peak_dbfs':20*math.log10(max(peak,1e-12)),'fullscale_fraction':float(np.mean(np.abs(y)>=.999)),
            'quiet_20ms_fraction_below_minus50dbfs':float(np.mean(frame<10**(-50/20))) if count else None}


def feature_metrics(paths,duration):
    import numpy as np
    f=np.load(paths[0],allow_pickle=False);coarse=np.load(paths[1],allow_pickle=False);pitch=np.load(paths[2],allow_pickle=False)
    if f.ndim!=2 or f.shape[1]!=768 or not f.size or not np.isfinite(f).all():raise ValueError('Invalid v2 ContentVec features')
    if coarse.ndim!=1 or pitch.ndim!=1 or not coarse.size or len(coarse)!=len(pitch):raise ValueError('Pitch shape/length mismatch')
    if not np.isfinite(coarse).all() or not np.isfinite(pitch).all() or np.any(pitch<0):raise ValueError('Invalid pitch values')
    if np.any(coarse<1) or np.any(coarse>255) or np.any(coarse!=np.round(coarse)):raise ValueError('Invalid coarse pitch bins')
    positive=pitch[pitch>0];pair=(pitch[1:]>0)&(pitch[:-1]>0)
    jumps=np.abs(12*np.log2(pitch[1:][pair]/pitch[:-1][pair])) if pair.any() else np.array([])
    return {'feature_frames':len(f),'feature_dim':f.shape[1],'feature_max_abs':float(np.max(np.abs(f))),
            'pitch_frames':len(pitch),'voiced_fraction':float(np.mean(pitch>0)),
            'pitch_hz_percentiles':np.percentile(positive,[5,50,95]).tolist() if positive.size else [],
            'voiced_outside_50_1100_fraction':float(np.mean((positive<50)|(positive>1100))) if positive.size else None,
            'adjacent_voiced_jumps_over_3_semitones':int(np.sum(jumps>3)),
            'feature_length_error_frames_at_50hz':len(f)-duration*50,
            'pitch_length_error_frames_at_100hz':len(pitch)-duration*100,
            'feature_pitch_frame_difference':len(f)*2-len(pitch)}


def audit(root,experiment_id=EXPERIMENT_ID):
    import numpy as np
    library=root/'workspace-data';run=library/'training'/experiment_id;exp=run/'models'/experiment_id
    report={'schema_version':1,'experiment_id':experiment_id,'status':'completed','issues':[],
            'limitations':['Technical audit only; no listening diagnosis or automatic quality rejection.',
                          'Feature validity does not establish correct F0 labels or cache provenance.',
                          'Only observed local log evidence can support pretrained loading history.']}
    def issue(kind,item,detail):report['issues'].append({'type':kind,'item':item,'detail':str(detail)[:500]})
    def optional(path):
        try:return read_json(path)
        except Exception as exc:issue('missing_or_invalid_metadata',path.name,exc);return None
    selection=optional(run/'selection.json')
    if selection:
        rows=selection.get('files',[])
        report['selection']={'selected_files':len(rows),'exact_duplicates_previously_skipped':len(selection.get('duplicates',[])),
                             'recorded_duration_s':selection.get('duration'),'manifest_count':len(selection.get('manifests',[])),
                             'sha256':sha(run/'selection.json')}
        try:report['source_coverage']=overlap_summary(rows)
        except Exception as exc:issue('invalid_source_intervals','selection.json',exc)
        verified=0
        for i,row in enumerate(rows):
            path=run/'dataset'/f'{i:05d}.wav'
            try:
                if sha(path)!=row['sha256']:raise ValueError('Snapshot SHA-256 mismatch')
                verified+=1
            except Exception as exc:issue('snapshot_integrity',path.name,exc)
        report['selection']['verified_snapshot_files']=verified
    prepared=optional(exp/'prepared-audio.json');skipped=optional(exp/'skipped-audio.json')
    report['prepared_count']=len(prepared) if isinstance(prepared,list) else None
    report['skipped_count']=len(skipped) if isinstance(skipped,list) else None
    config=optional(exp/'config.json') or {};hop=config.get('data',{}).get('hop_length',400)
    if not isinstance(hop,int) or hop<=0:raise ValueError('Invalid hop length')
    report['config_summary']={'sample_rate':config.get('data',{}).get('sample_rate'),
        'hop_length':hop,'train':config.get('train',{}),'model_info':optional(exp/'model_info.json')}
    preference=optional(run/'config.json') or {};report['precision_setting']=preference.get('precision','unknown')
    if isinstance(prepared,list):
        expected={row['path'] for row in prepared};actual={p.name for p in (exp/'sliced_audios').glob('*.wav')}
        if expected!=actual:issue('prepared_audio_set_mismatch','sliced_audios',{'missing':sorted(expected-actual),'extra':sorted(actual-expected)})
    seen=set();listed=set();duration=0;retained_duration=0;voiced=[];bucket=[0]*9;report['clips']=[]
    filelist=exp/'filelist.txt'
    lines=filelist.read_text(encoding='utf-8').splitlines()
    report['filelist_sha256']=sha(filelist)
    for index,line in enumerate(lines):
        print(f'检查训练切片 {index+1}/{len(lines)}',flush=True) if index%25==0 else None
        name=f'line_{index+1}';row={'line':index+1}
        try:
            parts=line.split('|')
            if len(parts)!=5:raise ValueError('Expected five filelist fields')
            paths=[inside(exp,p) for p in parts[:4]];name=paths[0].name;row['file']=name
            if paths[0] in listed:issue('duplicate_filelist_entry',name,'Same WAV listed more than once')
            listed.add(paths[0]);info=audio_metrics(paths[0]);row['audio']=info;duration+=info['duration_s']
            if info['sample_rate']!=40000 or info['channels']!=1:issue('audio_format',name,'Expected 40 kHz mono')
            content=sha(paths[0]);row['sha256']=content
            if content in seen:issue('duplicate_prepared_audio',name,'Exact duplicate WAV bytes')
            seen.add(content)
            feature=feature_metrics(paths[1:],info['duration_s']);row['features']=feature
            if abs(feature['feature_length_error_frames_at_50hz'])>5 or abs(feature['pitch_length_error_frames_at_100hz'])>5:
                issue('feature_audio_length_mismatch',name,'Greater than five feature/pitch frames from expected duration')
            if feature['feature_max_abs']==0:issue('zero_features',name,'All ContentVec values are zero')
            if feature['voiced_fraction']==0:issue('review_unvoiced_clip',name,'All F0 zero; may be unvoiced/silence, not automatically invalid')
            if info['fullscale_fraction']>0:issue('review_near_fullscale',name,'Near full scale; not automatically audible clipping')
            # Mirror the pinned sampler's file-byte length estimate; do not modify it.
            estimate=paths[0].stat().st_size//(3*hop)
            row['sampler_estimated_frames']=estimate;row['actual_audio_frames_at_hop']=info['frames']/hop
            keep=50<estimate<=900;row['within_sampler_bounds']=keep
            if keep:
                retained_duration+=info['duration_s']
                bounds=[50,100,200,300,400,500,600,700,800,900]
                for j in range(9):
                    if bounds[j]<estimate<=bounds[j+1]:bucket[j]+=1;break
            else:issue('sampler_excluded',name,'Outside pinned sampler bounds (50,900]')
            if parts[4]!='0':issue('speaker_id',name,'Expected single speaker ID 0')
            pitch=np.load(paths[3],allow_pickle=False);voiced.extend(pitch[pitch>0].tolist())
        except Exception as exc:issue('clip_check_failed',name,exc)
        report['clips'].append(row)
    actual_wavs={p.resolve() for p in (exp/'sliced_audios').glob('*.wav')}
    if actual_wavs!=listed:issue('filelist_audio_set_mismatch','filelist.txt',{'missing_count':len(actual_wavs-listed),'extra_count':len(listed-actual_wavs)})
    report['training_totals']={'filelist_entries':len(lines),'readable_audio_seconds':duration,
        'checked_sampler_retained_seconds':retained_duration,'bucket_counts':bucket,
        'expected_batches_at_batch2_single_gpu':sum(math.ceil(n/2) for n in bucket),
        'aggregate_voiced_pitch_hz_percentiles':np.percentile(voiced,[1,5,50,95,99]).tolist() if voiced else [],
        'note':'Pitch percentiles describe extracted labels, not verified singer range.'}
    resources=optional(run/'pretrained-resources.json');report['pretrained_files']=[]
    backend=root/'training-backend'/('Applio-'+BACKEND_COMMIT)
    if resources:
        for remote,entry in resources.get('files',{}).items():
            rel='pretraineds/hifi-gan/'+remote.split('/')[-1] if remote.startswith('pretrained_v2/') else remote
            path=inside(backend/'rvc/models',rel)
            record={'resource':remote,'expected_sha256':entry.get('sha256')}
            try:
                record['actual_sha256']=sha(path);record['matches_record']=record['actual_sha256']==record['expected_sha256']
                if not record['matches_record']:issue('resource_hash_mismatch',remote,'Current bytes differ from recorded download')
            except Exception as exc:issue('resource_missing',remote,exc)
            report['pretrained_files'].append(record)
    logpath=root/'training-log.txt'
    report['log_evidence']=log_evidence(logpath.read_text(encoding='utf-8',errors='replace')) if logpath.exists() else {'initial_pretrained_load_status':'unknown_log_missing'}
    report['models']=[]
    import torch
    for path in sorted(exp.glob('*.pth')):
        item={'file':path.name,'size_bytes':path.stat().st_size}
        if path.name.startswith(('G_','D_')):
            item['kind']='resume_checkpoint_not_loaded';report['models'].append(item);continue
        print('检查声线导出：'+path.name,flush=True)
        try:
            model=torch.load(path,map_location='cpu',weights_only=True)
            item.update({k:model.get(k) for k in ('epoch','step','sr','f0','version','embedder_model','vocoder')})
            weights=model.get('weight',{})
            item['finite_weights']=bool(weights) and all(torch.is_tensor(v) and bool(torch.isfinite(v).all()) for v in weights.values())
            item['sha256']=sha(path)
            if not item['finite_weights']:issue('invalid_model_weights',path.name,'Missing or nonfinite weights')
            if item.get('sr')!=40000 or item.get('version')!='v2' or not item.get('f0'):
                issue('model_config_mismatch',path.name,'Expected v2, pitch guidance and 40k output')
            del model,weights
        except Exception as exc:issue('model_load_failed',path.name,exc)
        report['models'].append(item)
    report['packages']={}
    for package in ('torch','torchaudio','numpy','soundfile','transformers','faiss-cpu'):
        try:report['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:report['packages'][package]='missing'
    report['backend_source']={}
    for name in ('rvc/train/train.py','rvc/train/data_utils.py','rvc/train/extract/extract.py','rvc/lib/utils.py'):
        path=backend/name
        report['backend_source'][name]=sha(path) if path.exists() else None
    expected_path=Path(__file__).with_name('expected-source.json')
    if expected_path.exists():
        expected=read_json(expected_path)
        for name,value in report['backend_source'].items():
            if expected.get(name)!=value:issue('backend_source_changed',name,'Source differs from original pinned commit; assess modifications before attributing errors')
    return report


def main():
    run=ROOT/'workspace-data/training'/EXPERIMENT_ID
    if not run.exists():raise FileNotFoundError('请把检查包解压到原工作台目录，未找到已有训练实验。')
    folder=ROOT/'workspace-data/diagnostics'/('audit_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    try:
        report=audit(ROOT)
    except Exception:
        report={'status':'failed','error':traceback.format_exc()}
    target=folder/'training_audit_report.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if report['status']=='completed':
        totals=report['training_totals']
        summary=f"检查完成。训练清单 {totals['filelist_entries']} 段；可读音频 {totals['readable_audio_seconds']/60:.2f} 分钟。\n技术检查/人工复核提示 {len(report['issues'])} 条，不等于听感不合格。\n请发送 training_audit_report.json。\n"
    else:summary='检查未完成，请发送 training_audit_report.json。\n'
    (folder/'检查说明.txt').write_text(summary,encoding='utf-8')
    print(summary+str(folder),flush=True)
    if os.name=='nt':os.startfile(folder)
    return 0 if report['status']=='completed' else 1


if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        print(traceback.format_exc(),flush=True);sys.exit(1)
