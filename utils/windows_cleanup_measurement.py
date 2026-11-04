"""Measure each Windows volume once over the whole cleaning operation."""
import os
import psutil


class VolumeMeter:
    def __init__(self, paths, usage=psutil.disk_usage, splitdrive=os.path.splitdrive):
        self.usage = usage
        self.roots = {}
        self.before = {}
        self.errors = []
        self.observations = {}
        for path in paths:
            drive, _ = splitdrive(str(path))
            if drive:
                self.roots.setdefault(os.path.normcase(drive), drive + '\\')

    def begin(self):
        self.before.clear()
        self.observations.clear()
        self.errors.clear()
        for key, root in self.roots.items():
            try:
                self.before[key] = self.usage(root).free
            except OSError as exc:
                self.errors.append(f'{root}: {exc}')

    def end(self):
        self.observations.clear()
        for key, before in self.before.items():
            try:
                after = self.usage(self.roots[key])
                self.observations[key] = dict(root=self.roots[key], before=before,
                                              after=after.free, delta=after.free-before,
                                              percent=after.percent, total=after.total)
            except OSError as exc:
                self.errors.append(f'{self.roots[key]}: {exc}')
        # A partial sample must not be presented as the change for the entire clean.
        if not self.roots or set(self.observations) != set(self.roots):
            return None
        return sum(e['delta'] for e in self.observations.values())
