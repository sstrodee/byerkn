"""Bounded local workload. Runs only on a new temporary copy of the engine."""
from concurrent.futures import ThreadPoolExecutor
import cProfile
import ctypes
from ctypes import wintypes
import json
import math
from pathlib import Path
import pstats
import statistics
import sys
import tempfile
import time

from byerkn.core import Storage, normalize_domains


def process_metrics():
    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in
                      ('peak_rss', 'rss', 'peak_paged', 'paged', 'peak_nonpaged',
                       'nonpaged', 'pagefile', 'peak_pagefile')]]
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    handle = wintypes.HANDLE(-1)
    count = wintypes.DWORD()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError()
    if not ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(count)):
        raise ctypes.WinError()
    return dict(rss_mib=round(memory.rss / 2**20, 2),
                peak_mib=round(memory.peak_rss / 2**20, 2), handles=count.value)


def batch(count, operation, workers=1):
    errors = []
    def timed(i):
        start = time.perf_counter()
        try:
            operation(i)
        except Exception as exc:
            errors.append(type(exc).__name__)
        return (time.perf_counter() - start) * 1000
    start, cpu = time.perf_counter(), time.process_time()
    if workers == 1:
        times = list(map(timed, range(count)))
    else:
        with ThreadPoolExecutor(workers) as executor:
            times = list(executor.map(timed, range(count)))
    elapsed = time.perf_counter() - start
    times.sort()
    return dict(n=count, errors=len(errors), first_error=next(iter(errors), None),
                ops_s=round(count / elapsed, 2), seconds=round(elapsed, 3),
                cpu_s=round(time.process_time() - cpu, 3), p50_ms=round(statistics.median(times), 3),
                p95_ms=round(times[math.ceil(.95*count)-1], 3),
                p99_ms=round(times[math.ceil(.99*count)-1], 3), **process_metrics())


def main():
    root = Path(__file__).resolve().parents[1]
    report = {}
    loads = [(32, 100), (1000, 35), (10000, 15), (25000, 3)]
    if '--peak' in sys.argv:
        loads += [(100000, 3), (250000, 3)]
    for size, repeats in loads:
        value = '\n'.join(f'host{i}.example' for i in range(size))
        report[f'domains_{size}'] = batch(repeats, lambda _: normalize_domains(value))
    with tempfile.TemporaryDirectory() as tmp:
        s = Storage(root, Path(tmp) / 'data')
        def save(i):
            s.save({'domains': f'saved{i}.example'})
        report['initial'] = process_metrics()
        report['saves'] = batch(1000, save)
        report['concurrent_8'] = batch(256, save, 8)
        config = json.loads(s.config.read_text('utf-8'))
        report['consistent'] = (config == s.settings and
            (s.users / 'list-general-user.txt').read_text().strip() == config['domains'])
    profile = cProfile.Profile()
    profile.runcall(normalize_domains, value)
    stats = pstats.Stats(profile)
    report['profile_top_self_ms'] = [(k[2], round(v[2]*1000, 2)) for k,v in
        sorted(stats.stats.items(), key=lambda e: -e[1][2])[:6]]
    print(json.dumps(report, indent=2))
    return int(not report['consistent'] or any(v.get('errors') for v in report.values() if isinstance(v, dict)))


if __name__ == '__main__':
    raise SystemExit(main())
