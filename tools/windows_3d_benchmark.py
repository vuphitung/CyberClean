"""Native Qt paint-cost check for the disk core only (no system telemetry)."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=300)
    args = parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPixmap
    from ui_widgets import Cyber3DDiskCore
    app = QApplication([])
    widget = Cyber3DDiskCore()
    widget.resize(196, 184)
    widget.set_usage_detail(65.8, '60.7 GB / 92.3 GB', '92.3 GB')
    widget.show()
    app.processEvents()
    widget._timer.stop()
    canvas = QPixmap(widget.size()*widget.devicePixelRatioF())
    canvas.setDevicePixelRatio(widget.devicePixelRatioF())
    for _ in range(10): widget.render(canvas)
    samples=[]
    cpu_start=time.process_time()
    for index in range(args.frames):
        widget._rot_y = index*1.5
        started=time.perf_counter()
        widget.render(canvas)
        samples.append((time.perf_counter()-started)*1000)
    cpu=time.process_time()-cpu_start
    ordered=sorted(samples)
    result=dict(frames=args.frames, mean_paint_ms=statistics.mean(samples),
                p95_paint_ms=ordered[int(.95*(len(ordered)-1))],
                cpu_ms_per_frame=1000*cpu/args.frames,
                estimated_one_core_percent_at_25fps=100*cpu/args.frames*25,
                device_pixel_ratio=widget.devicePixelRatioF(),
                notes='Native Qt offscreen paint microbenchmark only; estimated CPU excludes event loop/compositor/other app work.')
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    canvas.save(str(args.output.with_suffix('.png')))
    widget.close()
    print(json.dumps(result),flush=True)


if __name__ == '__main__': main()
