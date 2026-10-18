"""Opt-in private project cache of validated chunk results, never source receipts."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid

MAX_ENTRY_BYTES = 2_000_000
MAX_CACHE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 1024
FIELDS = {'segments', 'input_hash', 'timing_adjustments', 'segment_metrics'}


def _private_file(descriptor):
    info = os.fstat(descriptor)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError('unsafe_audio_result_cache_file')
    return info


class AudioResultCache:
    def __init__(self, project_root, cache_dir):
        root, path = Path(project_root).absolute(), Path(cache_dir).absolute()
        # Canonical system aliases are allowed; custom symlinks are never followed.
        for alias, canonical in (('/var', '/private/var'), ('/tmp', '/private/tmp')):
            if Path(alias).is_symlink() and Path(alias).resolve() == Path(canonical):
                root = Path(canonical) / root.relative_to(alias) if root.is_relative_to(alias) else root
                path = Path(canonical) / path.relative_to(alias) if path.is_relative_to(alias) else path
        if '..' in root.parts or '..' in path.parts or path == root or not path.is_relative_to(root):
            raise ValueError('audio_result_cache_outside_project')
        self.path = path
        # Open every ancestor without following links, including during creation.
        descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(path.parts[1:], 1):
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                except FileNotFoundError:
                    current = Path(os.path.join('/', *path.parts[1:index]))
                    # Only create descendants of the existing project, never the project itself.
                    if not current.is_relative_to(root):
                        raise ValueError('audio_result_cache_project_missing') from None
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                current = Path(os.path.join('/', *path.parts[1:index + 1]))
                if current.is_relative_to(root):
                    info = os.fstat(descriptor)
                    if info.st_uid != os.getuid() or info.st_mode & 0o022:
                        raise ValueError('unsafe_audio_result_cache_ancestor')
            info = os.fstat(descriptor)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('unsafe_audio_result_cache_directory')
            self.descriptor = descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def close(self):
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextlib.contextmanager
    def _lock(self):
        descriptor = os.open('cache.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                             0o600, dir_fd=self.descriptor)
        try:
            _private_file(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    @staticmethod
    def _name(key):
        if not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('invalid_audio_result_cache_key')
        return key + '.json'

    @staticmethod
    def _validate(key, value, validator):
        if (not isinstance(value, dict) or set(value) not in (FIELDS, FIELDS | {'native_alignment'})
                or value.get('input_hash') != key):
            raise ValueError('audio_result_cache_identity_mismatch')
        validator(value)

    def _read(self, name):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.descriptor)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, 'rb') as stream:
            if _private_file(stream.fileno()).st_size > MAX_ENTRY_BYTES:
                raise ValueError('audio_result_cache_entry_over_limit')
            encoded = stream.read(MAX_ENTRY_BYTES + 1)
            if len(encoded) > MAX_ENTRY_BYTES:
                raise ValueError('audio_result_cache_entry_over_limit')
        try:
            value = json.loads(encoded, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            raise ValueError('audio_result_cache_corrupt') from None

    def get(self, key, validator):
        name = self._name(key)
        with self._lock():
            value = self._read(name)
            if value is not None:
                self._validate(key, value, validator)
            return value

    def put(self, key, value, validator):
        name = self._name(key)
        self._validate(key, value, validator)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(',', ':')).encode('utf8')
        if len(encoded) > MAX_ENTRY_BYTES:
            raise ValueError('audio_result_cache_entry_over_limit')
        with self._lock():
            previous = self._read(name)
            if previous is not None:
                self._validate(key, previous, validator)
                if previous != value:
                    raise ValueError('audio_result_cache_conflict')
                return False
            count, total = 0, 0
            for entry in os.listdir(self.descriptor):
                if entry == 'cache.lock':
                    continue
                if not re.fullmatch('[a-f0-9]{64}\\.json', entry):
                    raise ValueError('unexpected_audio_result_cache_file')
                descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.descriptor)
                try:
                    size = _private_file(descriptor).st_size
                    if size > MAX_ENTRY_BYTES:
                        raise ValueError('audio_result_cache_entry_over_limit')
                    count += 1
                    total += size
                finally:
                    os.close(descriptor)
            if count >= MAX_ENTRIES or total + len(encoded) > MAX_CACHE_BYTES:
                return False
            temporary = uuid.uuid4().hex + '.tmp'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=self.descriptor)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Publication is atomic; lock prevents a cooperating writer replacing evidence.
                os.rename(temporary, name, src_dir_fd=self.descriptor, dst_dir_fd=self.descriptor)
                os.fsync(self.descriptor)
            finally:
                try:
                    os.unlink(temporary, dir_fd=self.descriptor)
                except FileNotFoundError:
                    pass
            return True
