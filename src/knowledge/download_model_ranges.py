"""Resume only the pinned Qwen GGUF; do not run alongside any other model downloader."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import time

import requests


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.cache/knowledge-downloads'
TARGET = ROOT / 'models/knowledge/qwen3-4b-instruct-2507-q4km/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
PREFIX = Path(str(TARGET) + '.partial')
STATE = CACHE / 'qwen-ranges.json'
SIZE = 2497281120
SHA256 = '3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
URL = 'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/Qwen3-4B-Instruct-2507-Q4_K_M.gguf'


def size(path):
    if not path.exists():
        return 0
    with path.open('rb') as handle:
        return handle.seek(0, 2)


def verify(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            digest.update(block)
    if size(path) != SIZE or digest.hexdigest() != SHA256:
        raise RuntimeError(f'Official size/SHA256 mismatch: {path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true', help='Read progress only; no download or hash validation.')
    args = parser.parse_args()
    parts = [CACHE / f'qwen-part-{i:02d}.bin' for i in range(8)]
    state = json.loads(STATE.read_text(encoding='utf-8-sig')) if STATE.exists() else None
    if state and (state['url'] != URL or state['sha256'] != SHA256 or state['size'] != SIZE):
        raise RuntimeError('Range state describes a different file; refusing to reuse it.')
    if args.status:
        downloaded = size(TARGET) if TARGET.exists() else (state['prefix_bytes'] if state else size(PREFIX)) + sum(size(p) for p in parts)
        print(json.dumps({'downloaded_bytes': downloaded, 'expected_bytes': SIZE,
                          'percent': 100 * downloaded / SIZE, 'final_file_present': TARGET.exists(),
                          'hash_checked': False, 'state': str(STATE)}, indent=2))
        return
    if TARGET.exists():
        verify(TARGET)
        print('Existing model matches the official SHA256; no download needed.')
        return
    if size(PREFIX) == SIZE:
        verify(PREFIX)
        PREFIX.rename(TARGET)
        print('Complete partial file verified and finalized; no service was started.')
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if state is None:
        if any(p.exists() for p in parts):
            raise RuntimeError('Existing chunks have no range state; inspect them instead of guessing offsets.')
        state = {'url': URL, 'sha256': SHA256, 'size': SIZE, 'prefix_bytes': size(PREFIX), 'parts': 8}
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    offset = state['prefix_bytes']
    if state['parts'] != 8 or size(PREFIX) != offset or not 0 <= offset < SIZE:
        raise RuntimeError('Prefix changed or assembly was interrupted; keep files and inspect before resuming.')
    width = (SIZE - offset + 7) // 8

    def fetch(i):
        start, end = offset + i * width, min(SIZE - 1, offset + (i + 1) * width - 1)
        part = parts[i]
        for attempt in range(4):
            current = size(part)
            if current == end - start + 1:
                return
            if current > end - start + 1:
                raise RuntimeError(f'Unexpected range size: {part}')
            try:
                with requests.get(URL, headers={'Range': f'bytes={start+current}-{end}'}, stream=True, timeout=(30, 60)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {start+current}-{end}/{SIZE}':
                        raise RuntimeError('Server did not honor the exact requested byte range.')
                    with part.open('ab') as handle:
                        for block in response.iter_content(1024 * 1024):
                            handle.write(block)
                if size(part) != end - start + 1:
                    raise RuntimeError(f'Incomplete range: {part}')
                print(f'Range {i} complete', flush=True)
                return
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, range(8)))
    if size(PREFIX) != offset:
        raise RuntimeError('Another downloader modified the prefix; refusing to assemble.')
    with PREFIX.open('ab') as output:
        for part in parts:
            with part.open('rb') as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    verify(PREFIX)
    PREFIX.rename(TARGET)
    print('Complete model verified against the official SHA256. No inference service was started.')


if __name__ == '__main__':
    main()
