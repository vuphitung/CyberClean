#!/usr/bin/env python3
"""Print every Linux temperature sensor and which one CyberClean uses.
Run:  python3 tools/linux_temp_check.py   (compare with `sensors`)"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import utils.sysinfo as si

sensors = si._linux_collect_sensors()
for chip, label, v, kind in sorted(sensors):
    print(f'{kind:8} {chip:18} {label:20} {v:6.1f} °C')
cpu, desc, conf = si._linux_pick_cpu(sensors)
print('\nUsed for dashboard:', f'{cpu:.1f} °C  ← {desc} ({conf})' if cpu is not None else 'N/A (no CPU sensor)')
