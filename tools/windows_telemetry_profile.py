"""Read-only, no-GUI Windows telemetry cost attribution. Never runs Boost/clean."""
import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=20, help='seconds per phase')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile-inventory', action='store_true', help='adds profiling overhead')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('requires Windows')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import psutil
    from utils.windows_telemetry import WindowsTelemetry
    from utils.windows_temperature import TemperatureHost

    timings = {'fast': [], 'inventory': []}
    profiles = {}
    class TimedTelemetry(WindowsTelemetry):
        def _measure(self, key, fn):
            # Python 3.12 cProfile uses one monitoring tool slot. Profile only
            # inventory; counters retain independent wall/thread CPU timing.
            profile = (profiles.setdefault(key, cProfile.Profile())
                       if key == 'inventory' and args.profile_inventory else None)
            start, cpu = time.perf_counter(), time.thread_time()
            if profile is not None:
                profile.enable()
            try:
                return fn()
            finally:
                if profile is not None:
                    profile.disable()
                timings[key].append(dict(wall_seconds=time.perf_counter()-start,
                                         thread_cpu_seconds=time.thread_time()-cpu))
        def _fast(self):
            return self._measure('fast', super()._fast)
        def _slow(self):
            return self._measure('inventory', super()._slow)

    service = TimedTelemetry()
    service.start()
    parent = psutil.Process()
    baseline = {}
    phases = {}
    def sample_phase(label):
        rows = []
        start = time.monotonic()
        while time.monotonic()-start < args.seconds:
            now = time.monotonic()
            entries = []
            for proc in [parent] + parent.children(recursive=True):
                try:
                    key = (proc.pid, proc.create_time())
                    values = proc.cpu_times()
                    total = values.user+values.system
                    old = baseline.get(key)
                    cpu = None if old is None else 100*(total-old[0])/(now-old[1])/psutil.cpu_count()
                    baseline[key] = (total, now)
                    entries.append(dict(pid=proc.pid, role='parent' if proc.pid == parent.pid else 'child',
                                        cpu_machine_percent=cpu, working_set=proc.memory_info().rss,
                                        threads=proc.num_threads(), handles=proc.num_handles()))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            rows.append(dict(elapsed=time.monotonic()-start, processes=entries))
            time.sleep(1.)
        phases[label] = rows
    try:
        sample_phase('telemetry_only')
        service._temperature = TemperatureHost()
        service._temperature.start()
        sample_phase('telemetry_and_lhm')
        temperature = service._temperature.snapshot()
    finally:
        close_start = time.monotonic()
        service.close()
        close_seconds = time.monotonic()-close_start
    summaries = {}
    for label, rows in phases.items():
        summaries[label] = {}
        for role in ('parent', 'child'):
            samples = [sum(p['cpu_machine_percent'] or 0 for p in row['processes'] if p['role'] == role)
                       for row in rows if row['elapsed'] > 5]
            summaries[label][role+'_cpu_machine_mean'] = statistics.mean(samples) if samples else None
    profile_text = {}
    for key, profile in profiles.items():
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(15)
        profile_text[key] = stream.getvalue()
    output = dict(seconds_per_phase=args.seconds, summaries=summaries, timings=timings,
                  profile=profile_text, temperature=temperature, close_seconds=close_seconds,
                  children_after_close=[p.pid for p in parent.children(recursive=True)], phases=phases)
    args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(dict(summaries=summaries, close_seconds=close_seconds,
                         temperature=temperature), indent=2))


if __name__ == '__main__':
    main()
