"""Set up a project-local CPU Ollama runtime and the default Phase 3 model.

Downloads stay under ignored backend/.cache. No system-wide installation, paid
API key, or visible app window is needed. Existing Ollama servers are reused.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx


MODEL = 'qwen2.5:3b'
VERSION = 'v0.40.11'
ASSET_SIZE = 1586356606
ASSET_SHA256 = 'bda4a493ba8a7c24d57263cd843cd68cee84f44aed4299eeed532acad7eda12a'
ASSET_URL = f'https://github.com/ollama/ollama/releases/download/{VERSION}/ollama-windows-amd64.zip'
BACKEND = Path(__file__).resolve().parents[1]
CACHE = BACKEND / '.cache'
BASE_URL = 'http://127.0.0.1:11434'


def models_available(client) -> list[dict] | None:
    try:
        response = client.get(BASE_URL + '/api/tags', timeout=3)
        response.raise_for_status()
        return response.json()['models']
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def runtime_binary() -> Path:
    """Verify the official archive before extracting only CPU runtime files."""
    installed = shutil.which('ollama')
    if installed:
        return Path(installed)
    if sys.platform != 'win32':
        raise SystemExit('Install Ollama using its official instructions, then run this script again.')
    runtime = CACHE / 'ollama-runtime' / VERSION
    executable = runtime / 'ollama.exe'
    if executable.is_file():
        return executable
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / f'ollama-{VERSION}.zip.part'
    existing = archive.stat().st_size if archive.exists() else 0
    required_space = max(0, ASSET_SIZE - existing) + 2_500_000_000
    if shutil.disk_usage(CACHE).free < required_space:
        raise SystemExit('Local model setup needs roughly 4 GB of free disk space during download. Use a hosted model or free space first.')
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as client:
        for attempt in range(3):
            existing = archive.stat().st_size if archive.exists() else 0
            if existing == ASSET_SIZE:
                break
            headers = {'Range': f'bytes={existing}-'} if existing else {}
            try:
                with client.stream('GET', ASSET_URL, headers=headers) as response:
                    response.raise_for_status()
                    if existing and response.status_code != 206:
                        existing = 0
                    mode = 'ab' if existing else 'wb'
                    last_report = time.monotonic()
                    with archive.open(mode) as output:
                        for block in response.iter_bytes(1024 * 1024):
                            output.write(block)
                            existing += len(block)
                            if time.monotonic() - last_report > 15:
                                print(f'Ollama runtime download: {existing // (1024 * 1024)} / {ASSET_SIZE // (1024 * 1024)} MiB', flush=True)
                                last_report = time.monotonic()
                break
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                print('Resuming interrupted runtime download.', flush=True)
    digest = hashlib.sha256()
    with archive.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != ASSET_SHA256:
        raise RuntimeError('Official Ollama archive checksum did not match. The archive was not executed.')
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            name = member.filename.replace('\\', '/')
            if member.is_dir() or not (name == 'ollama.exe' or name.startswith('lib/ollama/')):
                continue
            if any(part in name.lower() for part in ('cuda', 'cublas', 'cudart', 'nvrtc', 'nvidia', 'rocm', 'vulkan', 'mlx')):
                continue
            target = (runtime / name).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise RuntimeError('Unsafe archive path')
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    # This is a single known temporary file inside the project cache.
    archive.unlink()
    if not executable.is_file():
        raise RuntimeError('The verified archive did not contain the runtime executable')
    print('Verified and extracted the local CPU runtime.', flush=True)
    return executable


def run() -> None:
    with httpx.Client(timeout=30) as client:
        models = models_available(client)
        if models is None:
            executable = runtime_binary()
            environment = os.environ.copy()
            environment.update({'OLLAMA_HOST': '127.0.0.1:11434', 'OLLAMA_MODELS': str(CACHE / 'ollama-models'),
                'OLLAMA_NO_CLOUD': '1', 'OLLAMA_NUM_PARALLEL': '1', 'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_MAX_QUEUE': '4'})
            CACHE.mkdir(parents=True, exist_ok=True)
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
            with (CACHE / 'ollama.stdout.log').open('ab') as out, (CACHE / 'ollama.stderr.log').open('ab') as err:
                process = subprocess.Popen([str(executable), 'serve'], cwd=BACKEND, env=environment,
                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, creationflags=flags)
            (CACHE / 'ollama.pid').write_text(str(process.pid))
            for _ in range(30):
                models = models_available(client)
                if models is not None:
                    break
                time.sleep(1)
            if models is None:
                raise RuntimeError('The local model server did not start. See backend/.cache/ollama.stderr.log.')
        if not any(model['name'] == MODEL for model in models):
            print('Downloading the local answer model (about 1.9 GB).', flush=True)
            with client.stream('POST', BASE_URL + '/api/pull', json={'model': MODEL}, timeout=None) as response:
                response.raise_for_status()
                last_report = 0
                for line in response.iter_lines():
                    if not line:
                        continue
                    status = json.loads(line)
                    if status.get('error'):
                        raise RuntimeError(status['error'])
                    if time.monotonic() - last_report > 15 or status.get('status') == 'success':
                        completed = status.get('completed', 0) // (1024 * 1024)
                        total = status.get('total', 0) // (1024 * 1024)
                        print(f"Local model: {status.get('status')} {completed}/{total} MiB", flush=True)
                        last_report = time.monotonic()
        print('Local Phase 3 model is ready: ' + MODEL, flush=True)


if __name__ == '__main__':
    run()
