#!/usr/bin/env python3

import argparse
import os
import time

import psutil


def matching_process(pid: int, started_at: float) -> psutil.Process | None:
    try:
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        if abs(process.create_time() - started_at) > 0.01:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def run_watchdog(
    *,
    owner_pid: int,
    owner_started_at: float,
    supervisord_pid: int,
    supervisord_started_at: float,
    interval: float = 1.0,
) -> None:
    while matching_process(owner_pid, owner_started_at) is not None:
        time.sleep(max(0.2, interval))

    supervisord = matching_process(supervisord_pid, supervisord_started_at)
    if supervisord is None:
        return

    try:
        children = [child for child in supervisord.children(recursive=True) if child.pid != os.getpid()]
        supervisord.terminate()
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs([supervisord, *children], timeout=5)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=2)
    except psutil.NoSuchProcess:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--owner-started-at", type=float, required=True)
    parser.add_argument("--supervisord-pid", type=int, required=True)
    parser.add_argument("--supervisord-started-at", type=float, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    run_watchdog(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
