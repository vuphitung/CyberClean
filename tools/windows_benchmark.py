"""External read-only Windows observer. Never changes process settings.

Run outside the measured GUI. Thread counts are deliberately omitted because
psutil obtains them using an expensive full system-process query on Windows.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import time
import psutil


def observe_process(pid, seconds=60, interval=1., *, clock=time.monotonic,
                    sleeper=time.sleep, api=psutil):
    if int(pid) == os.getpid():
        raise ValueError('Observer must run outside the measured process')
    process = api.Process(pid)
    identity = process.create_time()
    observer = api.Process(os.getpid())
    logical_cpus = api.cpu_count() or 1
    rows, previous = [], {}
    previous_observer = None
    last = None
    started = clock()
    deadline = started+seconds
    exit_reason = 'observation deadline reached'
    while clock() < deadline:
        try:
            if not process.is_running():
                exit_reason = 'target exited or PID identity changed'
                break
            members = [member for member in [process]+process.children(recursive=True)
                       if member.pid != os.getpid()]
        except api.NoSuchProcess:
            exit_reason = 'target exited'
            break
        now = clock()
        elapsed = None if last is None else now-last
        cpu_seconds = 0.
        rss = handles = valid = 0
        next_previous, errors, details = {}, [], []
        for member in members:
            try:
                key = (member.pid, member.create_time())
                times = member.cpu_times()
                total = times.user+times.system
                cpu = None
                if key in previous and total >= previous[key] and elapsed and elapsed > 0:
                    delta = total-previous[key]
                    cpu_seconds += delta
                    cpu = 100*delta/elapsed/logical_cpus
                    valid += 1
                next_previous[key] = total
                working_set = member.memory_info().rss
                rss += working_set
                handles += member.num_handles()
                details.append(dict(pid=member.pid, create_time=key[1], name=member.name(),
                                    cpu_machine_percent=cpu, cpu_seconds=total,
                                    working_set=working_set))
            except (api.NoSuchProcess, api.AccessDenied) as exc:
                errors.append(f'{member.pid}: {exc}')
        observer_times = observer.cpu_times()
        observer_total = observer_times.user+observer_times.system
        observer_cpu = (100*max(0, observer_total-previous_observer)/elapsed/logical_cpus
                        if previous_observer is not None and elapsed and elapsed > 0 else None)
        previous_observer = observer_total
        rows.append(dict(monotonic=now, elapsed_seconds=now-started,
                         cpu_machine_percent=(100*cpu_seconds/elapsed/logical_cpus
                                              if previous and elapsed and elapsed > 0 and valid else None),
                         observer_cpu_machine_percent=observer_cpu,
                         working_set_sum=rss, threads=None, handles=handles,
                         processes=len(next_previous), process_details=details, errors=errors,
                         priming_processes=sum(key not in previous for key in next_previous)))
        previous, last = next_previous, now
        sleeper(min(interval, max(0., deadline-clock())))
    cpu = [row['cpu_machine_percent'] for row in rows if row['cpu_machine_percent'] is not None]
    observer_cpu = [row['observer_cpu_machine_percent'] for row in rows
                    if row['observer_cpu_machine_percent'] is not None]
    return dict(platform=platform.platform(), pid=pid, create_time=identity,
                observer_pid=os.getpid(), logical_cpus=logical_cpus,
                duration_seconds=clock()-started, requested_seconds=seconds,
                exit_reason=exit_reason, cpu_mean=statistics.mean(cpu) if cpu else None,
                cpu_max=max(cpu) if cpu else None,
                observer_cpu_mean=statistics.mean(observer_cpu) if observer_cpu else None,
                samples=rows,
                measurement=dict(observer_location='separate_process',
                                 observer_cpu_excluded=True, thread_counts_collected=False,
                                 measured_tree='target PID and descendants; observer is their parent or unrelated'),
                notes='CPU is a fraction of entire machine. Observer CPU is reported separately and excluded. '
                      'Working sets are summed; shared pages may count twice. Exited children between samples '
                      'and newly priming children can reduce CPU completeness. Thread counts omitted. '
                      'Observer still adds some system load; no startup/UI lag/FPS claim.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--interval', type=float, default=1.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('Windows-native measurement only')
    if args.seconds <= 0 or args.interval <= 0:
        parser.error('seconds and interval must be positive')
    result = observe_process(args.pid, args.seconds, args.interval)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(args.output.resolve())


if __name__=='__main__':main()
