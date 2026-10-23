"""Fetch the exact verified public inputs used by the Windows release bundle."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request

CONFIG = Path(__file__).resolve().parent/'windows_backend'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(item):
    url, target, expected = item
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256(target) == expected:
        return
    temporary = target.with_suffix(target.suffix+'.partial')
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if sha256(temporary) != expected:
                raise ValueError('Checksum mismatch: '+target.name)
            temporary.replace(target)
            print('Verified '+target.name, flush=True)
            return
        except ValueError:
            raise
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def main(destination):
    destination = Path(destination)
    payload, models = destination/'payload', destination/'models'
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CONFIG/'model-config', models, dirs_exist_ok=True)
    for name in ('offline-wheels.json', 'offline-requirements.txt'):
        shutil.copy2(CONFIG/name, payload/name)
    lock = json.loads((payload/'offline-wheels.json').read_text())
    manifest = json.loads((CONFIG/'download-manifest.json').read_text())
    tasks = [(item['url'], payload/'wheelhouse'/item['filename'], item['sha256']) for item in lock['wheels']]
    tasks.extend([
        (manifest['model_url'], models/'model_bs_roformer_ep_317_sdr_12.9755.ckpt', manifest['model_sha256']),
        (manifest['ffmpeg_url'], destination/'ffmpeg.zip', manifest['ffmpeg_sha256']),
    ])
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(fetch, tasks))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    main(parser.parse_args().destination)
