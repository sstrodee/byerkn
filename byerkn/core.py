"""Portable storage, safe upstream updates, profile translation and owned process control."""
from __future__ import annotations

import concurrent.futures
import ctypes
from ctypes import wintypes
import hashlib
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import __version__

REPO = 'Flowseal/zapret-discord-youtube'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
DEFAULTS = dict(profile='general.bat', game_filter=False, ip_filter=True,
                auto_check=True, auto_install=False, start_engine=False,
                close_to_tray=True, domains='', exclusions='')
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
LOG = logging.getLogger('byerkn')


class AppError(Exception):
    pass


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


class Storage:
    def __init__(self, root: Path, data: Path | None = None):
        self.root = root.resolve()
        self.data = (data or root / 'data').resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.current = self.data / 'engine'
        self.previous = self.data / 'previous-engine'
        self.config = self.data / 'settings.json'
        self.users = self.data / 'user-lists'
        self.users.mkdir(exist_ok=True)
        self.settings = dict(DEFAULTS)
        self.lock = threading.RLock()
        if self.config.exists():
            try:
                loaded = json.loads(self.config.read_text(encoding='utf-8'))
                if not isinstance(loaded, dict):
                    raise ValueError('Expected a settings object')
                for key, default in DEFAULTS.items():
                    if key in loaded and type(loaded[key]) is type(default):
                        self.settings[key] = loaded[key]
            except (ValueError, TypeError):
                shutil.copy2(self.config, self.config.with_suffix('.invalid.json'))
                LOG.warning('Повреждённые настройки сохранены в settings.invalid.json; загружены значения по умолчанию.')
        # Recover an interrupted directory swap before installing the bundle.
        swap = self.data / 'rollback-swap'
        retired = self.data / 'retired-engine'
        if swap.exists() and not self.current.exists():
            os.replace(swap, self.current)
        elif swap.exists() and not self.previous.exists():
            os.replace(swap, self.previous)
        if not self.current.exists() and self.previous.exists():
            os.replace(self.previous, self.current)
        if retired.exists() and not self.previous.exists():
            os.replace(retired, self.previous)
        if not self.current.exists():
            bundle = root / 'bundle'
            if bundle.exists():
                stage = Path(tempfile.mkdtemp(prefix='initial-', dir=self.data))
                try:
                    shutil.copytree(bundle, stage / 'engine')
                    validate_engine(stage / 'engine')
                    os.replace(stage / 'engine', self.current)
                finally:
                    shutil.rmtree(stage, ignore_errors=True)
        self.write_user_lists()

    def save(self, changes):
        with self.lock:
            candidate = {**self.settings, **changes}
            for key in ('domains', 'exclusions'):
                candidate[key] = normalize_domains(candidate[key])
            try:
                self.write_user_lists(candidate)
                atomic_json(self.config, candidate)
            except OSError:
                # JSON remains authoritative, including across process termination.
                self.write_user_lists(self.settings)
                raise
            self.settings = candidate

    def write_user_lists(self, settings=None):
        settings = self.settings if settings is None else settings
        mapping = {'list-general-user.txt': settings['domains'],
                   'list-exclude-user.txt': settings['exclusions'],
                   'ipset-exclude-user.txt': '203.0.113.113/32',
                   'ipset-disabled.txt': '203.0.113.113/32'}
        for name, value in mapping.items():
            target = self.users / name
            content = ((value.strip() or 'placeholder.invalid') + '\n').encode('utf-8')
            if not target.is_file() or target.read_bytes() != content:
                atomic_write(target, content)

    @property
    def version(self):
        try:
            version = json.loads((self.current / '_byerkn.json').read_text('utf-8'))['version']
            return version if isinstance(version, str) and version.strip() else 'неизвестна'
        except (OSError, KeyError, TypeError, ValueError):
            return 'не установлена'

    def profiles(self):
        return sorted(self.current.glob('general*.bat'), key=lambda p: (p.name != 'general.bat', natural_key(p.name)))


def setup_logging(data: Path):
    LOG.setLevel(logging.INFO)
    if not LOG.handlers:
        handler = RotatingFileHandler(data / 'byerkn.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s  %(levelname)s  %(message)s', '%d.%m %H:%M:%S'))
        LOG.addHandler(handler)


def natural_key(value):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', value)]


def normalize_domains(text):
    result = {}
    for line in text.splitlines():
        host = line.strip().lower().rstrip('.')
        if not host or host.startswith('#'):
            continue
        try:
            host = host.encode('idna').decode('ascii')
        except UnicodeError:
            raise AppError(f'Некорректный домен: {line}')
        if len(host) > 253 or '.' not in host or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in host.split('.')):
            raise AppError(f'Введите домен без https://, пути и пробелов: {line}')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise AppError(f'Нужен домен, а не IP-адрес: {host}')
        result[host] = None
    return '\n'.join(result)


def profile_title(name):
    return 'Основной' if name == 'general.bat' else name.removeprefix('general ').removesuffix('.bat').strip('()')


def profile_description(name):
    if name == 'general.bat':
        return 'Начните с этого профиля. Подходит для первой проверки YouTube и Discord.'
    if 'FAKE TLS AUTO' in name:
        return 'Подменяет начальное TLS-рукопожатие. Попробуйте, если основной профиль не открывает сайты.'
    if 'SIMPLE FAKE' in name:
        return 'Упрощённая стратегия с подставными пакетами. Ещё один вариант для вашего провайдера.'
    if 'EXP' in name:
        return 'Экспериментальная стратегия автора zapret. Используйте для проверки альтернатив.'
    return 'Альтернативный набор параметров zapret. Результат зависит от провайдера; после выбора проверьте соединение.'


def windows_split(command: str):
    if os.name != 'nt':
        raise AppError('byerkn поддерживает Windows.')
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    argc = ctypes.c_int()
    ptr = shell.CommandLineToArgvW('winws.exe ' + command, ctypes.byref(argc))
    if not ptr:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [ptr[i] for i in range(1, argc.value)]
    finally:
        kernel.LocalFree(ptr)


def profile_args(path: Path, engine: Path, users: Path, settings: dict):
    text = path.read_text('utf-8-sig')
    match = re.search(r'(?im)^start\s+[^\r\n]*?"%BIN%winws\.exe"\s+', text)
    if not match:
        raise AppError(f'Неизвестный формат профиля {path.name}. Обновление не применено.')
    lines = text[match.end():].splitlines()
    pieces = []
    for line in lines:
        continued = line.rstrip().endswith('^')
        pieces.append(line.rstrip()[:-1] if continued else line)
        if not continued:
            break
    command = ' '.join(pieces).replace('^!', '!')
    replacements = {'BIN': str(engine / 'bin') + '\\', 'LISTS': str(engine / 'lists') + '\\',
                    'GameFilterTCP': '1024-65535' if settings['game_filter'] else '12',
                    'GameFilterUDP': '1024-65535' if settings['game_filter'] else '12'}
    tokens = re.compile('%(' + '|'.join(replacements) + ')%', re.I)
    template = tokens.sub('', command)
    if '%' in template or any(c in template for c in ('\r', '\n', '&', '|', '<', '>')):
        raise AppError('Профиль содержит неподдерживаемые команды. Он не будет запущен.')
    values = {k.lower(): v for k, v in replacements.items()}
    command = tokens.sub(lambda m: values[m[1].lower()], command)
    args = windows_split(command)
    if not args or any(not arg.startswith('--') for arg in args):
        raise AppError('Неподдерживаемые аргументы профиля.')
    result = []
    file_options = ('--hostlist=', '--hostlist-exclude=', '--ipset=', '--ipset-exclude=')
    for arg in args:
        key, sep, val = arg.partition('=')
        if sep and (arg.startswith(file_options) or ('fake' in key or 'pattern' in key) and ('\\' in val or '/' in val)):
            file = Path(val)
            if file.name in ('list-general-user.txt', 'list-exclude-user.txt', 'ipset-exclude-user.txt'):
                file = users / file.name
            elif file.name == 'ipset-all.txt' and not settings['ip_filter']:
                file = users / 'ipset-disabled.txt'
            if not (file.resolve().is_relative_to(engine.resolve()) or file.resolve().is_relative_to(users.resolve())):
                raise AppError('Профиль ссылается на файл за пределами папки приложения.')
            if not file.is_file():
                raise AppError(f'Не найден файл {file.name}. Проверьте карантин антивируса или обновите файлы.')
            arg = key + '=' + str(file)
        result.append(arg)
    return result


def validate_engine(path):
    for name in ('bin/winws.exe', 'bin/WinDivert.dll', 'bin/WinDivert64.sys', 'bin/cygwin1.dll', 'lists/list-general.txt', 'lists/ipset-all.txt', 'general.bat'):
        p = path / name
        if not p.is_file() or p.stat().st_size == 0:
            raise AppError(f'Архив неполный: отсутствует {name}. Текущая версия сохранена.')
        if p.suffix in ('.exe', '.dll', '.sys'):
            with p.open('rb') as f:
                if f.read(2) != b'MZ':
                    raise AppError(f'Повреждён исполняемый файл {name}.')


def request(url):
    return urllib.request.Request(url, headers={'User-Agent': f'byerkn/{__version__}', 'Accept': 'application/vnd.github+json'})


def limited_chunks(response, max_bytes, seconds):
    deadline = time.monotonic() + seconds
    total = 0
    read = getattr(response, 'read1', response.read)
    while time.monotonic() < deadline:
        chunk = read(min(max_bytes - total + 1, 256 * 1024))
        if time.monotonic() >= deadline:
            break
        if not chunk:
            return
        total += len(chunk)
        if total > max_bytes:
            raise AppError('Ответ сервера превышает допустимый размер.')
        yield chunk
    raise AppError('Истекло время загрузки. Попробуйте ещё раз.')


def latest_release():
    try:
        with urllib.request.urlopen(request(API), timeout=20) as response:
            raw = b''.join(limited_chunks(response, 2_000_000, 30))
            release = json.loads(raw)
    except Exception as exc:
        raise AppError(f'Не удалось проверить обновления на GitHub: {exc}') from exc
    if not isinstance(release, dict) or not isinstance(release.get('assets'), list):
        raise AppError('Некорректное описание релиза GitHub.')
    assets = [a for a in release['assets'] if isinstance(a, dict)
              and isinstance(a.get('name'), str) and a['name'].endswith('.zip')]
    if not assets:
        raise AppError('В релизе нет ZIP-архива. Текущая версия сохранена.')
    asset = assets[0]
    url = asset.get('browser_download_url', '')
    if not isinstance(url, str) or not url.startswith(f'https://github.com/{REPO}/releases/download/'):
        raise AppError('Ссылка обновления не принадлежит официальному репозиторию.')
    if not isinstance(asset.get('digest'), str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', asset['digest']):
        raise AppError('GitHub не предоставил SHA-256. Автоустановка недоступна для этого релиза.')
    version, size, notes = release.get('tag_name'), asset.get('size'), release.get('body') or ''
    if not (isinstance(version, str) and version.strip() and type(size) is int
            and 0 < size <= 30_000_000 and isinstance(notes, str)):
        raise AppError('Некорректная версия, размер или описание релиза GitHub.')
    return dict(version=version, url=url, digest=asset['digest'], size=size,
                notes=notes[:20000], published=release.get('published_at', ''))


def safe_extract(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 5000 or sum(x.file_size for x in entries) > 200_000_000:
            raise AppError('Архив превышает допустимый размер.')
        for entry in entries:
            name = entry.filename.replace('\\', '/')
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise AppError('Небезопасный путь в архиве. Установка отменена.')
            # NTFS trailing dots/spaces and device aliases must not escape the staging tree.
            if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(10)], *[f'LPT{i}' for i in range(10)]} for part in p.parts):
                raise AppError('Неподдерживаемое имя файла в архиве.')
            target = destination.joinpath(*p.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise AppError('Путь архива выходит за папку установки.')
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)


class Updater:
    def __init__(self, storage):
        self.s = storage

    def install(self, release):
        stage = Path(tempfile.mkdtemp(prefix='update-', dir=self.s.data))
        try:
            archive = stage / 'release.zip'
            digest = hashlib.sha256()
            total = 0
            with urllib.request.urlopen(request(release['url']), timeout=30) as response, archive.open('wb') as out:
                for chunk in limited_chunks(response, 30_000_000, 120):
                    total += len(chunk)
                    digest.update(chunk)
                    out.write(chunk)
            if total != release['size'] or 'sha256:' + digest.hexdigest() != release['digest']:
                raise AppError('Контрольная сумма архива не совпала. Текущая версия сохранена.')
            unpacked = stage / 'unpacked'
            safe_extract(archive, unpacked)
            candidates = [p.parent for p in unpacked.rglob('general.bat')]
            if len(candidates) != 1:
                raise AppError('Не удалось однозначно найти zapret в архиве.')
            incoming = candidates[0]
            validate_engine(incoming)
            for p in incoming.glob('general*.bat'):
                profile_args(p, incoming, self.s.users, self.s.settings)
            if not (incoming / self.s.settings['profile']).is_file():
                raise AppError('В новой версии отсутствует выбранный профиль. Сначала выберите основной.')
            atomic_json(incoming / '_byerkn.json', {'version': release['version'], 'digest': release['digest']})
            self.commit(incoming)
            LOG.info('Установлен zapret %s', release['version'])
            return release['version']
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def commit(self, incoming):
        # Staging and destination are on the same volume. Preserve current on a failed rename.
        retired = self.s.data / 'retired-engine'
        if retired.exists():
            shutil.rmtree(retired)
        if self.s.previous.exists():
            os.replace(self.s.previous, retired)
        moved = False
        try:
            if self.s.current.exists():
                os.replace(self.s.current, self.s.previous)
                moved = True
            os.replace(incoming, self.s.current)
        except Exception:
            if moved and not self.s.current.exists():
                os.replace(self.s.previous, self.s.current)
            if retired.exists() and not self.s.previous.exists():
                os.replace(retired, self.s.previous)
            raise
        if retired.exists():
            shutil.rmtree(retired, ignore_errors=True)

    def rollback(self):
        if not self.s.previous.exists():
            raise AppError('Предыдущей версии пока нет.')
        validate_engine(self.s.previous)
        selected = self.s.previous / self.s.settings['profile']
        if not selected.is_file():
            raise AppError('В предыдущей версии нет выбранного профиля. Сначала выберите основной.')
        profile_args(selected, self.s.previous, self.s.users, self.s.settings)
        temp = self.s.data / 'rollback-swap'
        if temp.exists():
            raise AppError('Обнаружен незавершённый откат. Проверьте папку data/rollback-swap.')
        os.replace(self.s.current, temp)
        try:
            os.replace(self.s.previous, self.s.current)
        except Exception:
            os.replace(temp, self.s.current)
            raise
        try:
            os.replace(temp, self.s.previous)
        except OSError:
            os.replace(self.s.current, self.s.previous)
            os.replace(temp, self.s.current)
            raise
        LOG.info('Выполнен откат на zapret %s', self.s.version)
        return self.s.version


def is_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == 'nt' else False


def external_engines():
    folder = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(folder, len(folder))
    if not 0 < length < len(folder):
        raise AppError('Не удалось определить системную папку Windows.')
    p = subprocess.run([str(Path(folder.value) / 'tasklist.exe'), '/FI', 'IMAGENAME eq winws.exe', '/FO', 'CSV', '/NH'],
                       capture_output=True, creationflags=NO_WINDOW, timeout=8)
    if p.returncode:
        raise AppError('Не удалось проверить запущенные экземпляры zapret.')
    return b'winws.exe' in p.stdout.lower()


class KillJob:
    """Only the process spawned by this application belongs to this Windows job."""
    def __init__(self, process):
        class BASIC(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                        ('Flags', wintypes.DWORD), ('Min', ctypes.c_size_t), ('Max', ctypes.c_size_t),
                        ('Active', wintypes.DWORD), ('Affinity', ctypes.c_size_t),
                        ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes')]
        class EXT(ctypes.Structure):
            _fields_ = [('Basic', BASIC), ('Io', IO), ('ProcessMemory', ctypes.c_size_t),
                        ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = EXT()
        info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            self.close()
            raise AppError('Windows не позволила привязать zapret к приложению. Запуск отменён.')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class Engine:
    def __init__(self, storage):
        self.s = storage
        self.process = None
        self.job = None
        self.output = None
        self.started_at = None
        self.lock = threading.RLock()

    @property
    def running(self):
        process = self.process
        return process is not None and process.poll() is None

    def start(self):
        with self.lock:
            if self.running:
                return
            self.stop()
            if not is_admin():
                raise AppError('Для WinDivert нужны права администратора. Закройте byerkn и запустите byerkn.exe: Windows запросит разрешение.')
            if external_engines():
                raise AppError('Уже работает другой zapret. Остановите его в прежнем окне или службе и попробуйте снова. byerkn не отключает чужие процессы.')
            validate_engine(self.s.current)
            self.s.write_user_lists()
            selected = self.s.settings['profile']
            if Path(selected).name != selected:
                raise AppError('Недопустимое имя профиля.')
            args = profile_args(self.s.current / selected, self.s.current, self.s.users, self.s.settings)
            self.output = (self.s.data / 'engine.log').open('wb')
            try:
                self.process = subprocess.Popen([str(self.s.current / 'bin' / 'winws.exe'), *args],
                    cwd=self.s.current / 'bin', stdout=self.output, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
                self.job = KillJob(self.process)
                time.sleep(0.8)
                if not self.running:
                    self.output.flush()
                    with (self.s.data / 'engine.log').open('rb') as log:
                        log.seek(max(0, os.fstat(log.fileno()).st_size - 4800))
                        tail = log.read(4800).decode('utf-8', errors='replace')[-1200:]
                    raise AppError('zapret не запустился. Проверьте драйвер WinDivert и журнал.\n' + tail)
                self.started_at = time.monotonic()
                LOG.info('Запущен профиль %s; PID %s', selected, self.process.pid)
            except Exception:
                self.stop()
                raise

    def stop(self):
        with self.lock:
            if self.running:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                LOG.info('Собственный процесс zapret остановлен')
            if self.job:
                self.job.close()
                self.job = None
            if self.output:
                self.output.close()
                self.output = None
            self.process = None
            self.started_at = None


ENDPOINTS = [('YouTube', 'https://www.youtube.com/generate_204'),
             ('Discord', 'https://discord.com/api/v10/gateway'),
             ('Google', 'https://www.google.com/generate_204'),
             ('GitHub', 'https://api.github.com/zen')]


def probe_endpoint(item):
    name, url = item
    start = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={'User-Agent': f'byerkn/{__version__}'})
        # Direct requests: do not count a configured HTTP proxy as zapret success.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=8) as response:
            code = response.status
            final = urllib.parse.urlsplit(response.geturl())
            payload = response.read(512)
            expected = final.scheme == 'https' and final.hostname == urllib.parse.urlsplit(url).hostname
            if name in ('Google', 'YouTube'):
                expected = expected and code == 204
            elif name == 'Discord':
                gateway = json.loads(payload) if expected and code == 200 else None
                expected = isinstance(gateway, dict) and str(gateway.get('url', '')).startswith('wss://')
            else:
                expected = expected and code == 200 and response.headers.get_content_type() == 'text/plain'
        ms = round((time.monotonic() - start) * 1000)
        detail = f'HTTPS {code} · {ms} мс' if expected else f'HTTPS {code}: неожиданный ответ сервиса'
        return dict(name=name, ok=expected, detail=detail, ms=ms)
    except urllib.error.HTTPError as exc:
        exc.close()
        return dict(name=name, ok=False, detail=f'HTTP {exc.code}: сервер ответил, доступ не подтверждён', ms=None)
    except Exception as exc:
        return dict(name=name, ok=False, detail=str(exc.reason if isinstance(exc, urllib.error.URLError) else exc), ms=None)


def diagnostics():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(probe_endpoint, ENDPOINTS))
