"""Minimal frozen entry point for the protected, read-only Windows sensor host."""
import sys

from utils.windows_sensor_access import attach_sensor_stdio


def main():
    if '--windows-temp-host' not in sys.argv[1:] or not attach_sensor_stdio():
        return 2
    # Import hardware/.NET code only after the parent has authenticated IPC.
    from utils.windows_temperature_host import run
    return run()


if __name__ == '__main__':
    sys.exit(main())
