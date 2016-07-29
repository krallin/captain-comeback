# coding:utf-8
# Imported from https://github.com/giampaolo/psutil/blob/master/scripts/ps.py
import psutil

PROC_STATUSES_RAW = {
    psutil.STATUS_RUNNING: "R",
    psutil.STATUS_SLEEPING: "S",
    psutil.STATUS_DISK_SLEEP: "D",
    psutil.STATUS_STOPPED: "T",
    psutil.STATUS_TRACING_STOP: "t",
    psutil.STATUS_ZOMBIE: "Z",
    psutil.STATUS_DEAD: "X",
    psutil.STATUS_WAKING: "WA",
    psutil.STATUS_IDLE: "I",
    psutil.STATUS_LOCKED: "L",
    psutil.STATUS_WAITING: "W",
}

if hasattr(psutil, 'STATUS_WAKE_KILL'):
    PROC_STATUSES_RAW[psutil.STATUS_WAKE_KILL] = "WK"

if hasattr(psutil, 'STATUS_SUSPENDED'):
    PROC_STATUSES_RAW[psutil.STATUS_SUSPENDED] = "V"
