"""Console helper entry point; packaged separately from the windowed Qt app."""
import _thread
import json
import os
import signal
import sys
import threading


def contain_process_tree():
    """Keep FFmpeg descendants owned by this helper on both supported platforms."""
    if os.name != "nt":
        os.setsid()
        return None
    import ctypes
    from ctypes import wintypes

    class Limits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Limits), ("IoInfo", Counters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    return handle  # Non-inheritable; the OS closes it when this process exits.


def main():
    job = contain_process_tree()
    print(json.dumps({"event": "helper_ready", "pid": os.getpid()}), flush=True)
    import spotify_dl as backend

    def control():
        for line in sys.stdin:
            if line.strip() == "cancel":
                break
        # EOF means the owning GUI disappeared; do not leave downloads running.
        backend.STOP_EVENT.set()
        backend.terminate_children()
        _thread.interrupt_main()
        def force_exit():
            if os.name == "nt":
                os._exit(130)  # OS closes the job handle and its descendants.
            else:
                os.killpg(os.getpid(), signal.SIGKILL)
        watchdog = threading.Timer(5, force_exit)
        watchdog.daemon = True
        watchdog.start()

    try:
        threading.Thread(target=control, daemon=True).start()
        return backend.main()
    except KeyboardInterrupt:
        return 130
    finally:
        backend.STOP_EVENT.set()
        backend.terminate_children()
        if os.name != "nt":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(os.getpid(), signal.SIGTERM)
        # Keep the Windows job handle alive until process teardown.
        _ = job


if __name__ == "__main__":
    raise SystemExit(main())
