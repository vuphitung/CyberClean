"""Early Windows diagnostics. No Qt, CLR or administrator rights required."""
import atexit
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile
import threading

_log = logging.getLogger('cyberclean')
_fault_stream = None
_started = False
_exit_reason = 'no normal exit recorded (inspect traceback/native log)'


def stage(message):
    _log.info('stage=%s', message)


def normal_exit(code=0, reason='event loop ended'):
    global _exit_reason
    _exit_reason = f'{reason}; code={code}'
    _log.info('exit=%s', _exit_reason)


def install():
    global _started, _fault_stream
    if _started:
        return
    _started = True
    directory = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'CyberClean' / 'logs'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / f'runtime-{os.getpid()}.log', maxBytes=2_000_000,
                                      backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
        _log.addHandler(handler)
        _log.setLevel(logging.INFO)
        # Keep open for the entire process lifetime, including Qt teardown.
        _fault_stream = open(directory / f'native-crash-{os.getpid()}.log', 'a', encoding='utf-8')
        faulthandler.enable(_fault_stream, all_threads=True)
    except OSError:
        logging.basicConfig(level=logging.INFO)
        _log.exception('Cannot open diagnostic logs')
    old_hook = sys.excepthook
    def exception_hook(kind, value, tb):
        _log.critical('Uncaught main/Qt callback exception', exc_info=(kind, value, tb))
        old_hook(kind, value, tb)
    sys.excepthook = exception_hook
    old_thread_hook = threading.excepthook
    def thread_hook(args):
        _log.critical('Uncaught worker exception: %s', args.thread.name,
                      exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        old_thread_hook(args)
    threading.excepthook = thread_hook
    atexit.register(lambda: _log.info('process teardown: %s', _exit_reason))
    stage(f'bootstrap pid={os.getpid()} python={sys.version} frozen={getattr(sys, "frozen", False)}')
