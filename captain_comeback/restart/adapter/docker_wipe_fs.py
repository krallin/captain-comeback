import os
import logging
import uuid
import errno

from captain_comeback.restart.adapter.docker import try_docker

logger = logging.getLogger()


AUFS_BASE_DIR = "/var/lib/docker/aufs"

AUFS_DIFF_DIR = os.path.join(AUFS_BASE_DIR, "diff")
AUFS_MNT_DIR = os.path.join(AUFS_BASE_DIR, "mnt")

AUFS_MOUNTS_DIR = "/var/lib/docker/image/aufs/layerdb/mounts"
AUFS_MOUNT_FILE = "mount-id"

BACKUP_DIR = os.path.join(AUFS_BASE_DIR, "captain-comeback-backup")


def restart(cg):
    stop_ok = try_docker(cg, "docker", "stop", "-t", "0", cg.name())

    if stop_ok:
        try:
            do_wipe_fs(cg)
        except Exception:
            logger.exception("%s: could not wipe fs", cg.name())
    else:
        logger.warning("%s: not wiping fs: stop failed", cg.name())

    ok = try_docker(cg, "docker", "restart", "-t", "0", cg.name())
    if not ok:
        raise Exception("docker restart failed")


def do_wipe_fs(cg):
    aufs_id = cg.name()
    mount_id_path = os.path.join(AUFS_MOUNTS_DIR, cg.name(), AUFS_MOUNT_FILE)
    restore_id = "cc-{0}".format(uuid.uuid4())

    logger.info("%s: wipe with restore id: %s", cg.name(), restore_id)

    try:
        with open(mount_id_path) as f:
            aufs_id = f.read()
    except (IOError, OSError):
        # Older Docker version, no mount ID
        logger.warning("%s: mount ID not found at: %s",
                       cg.name(), mount_id_path)

    # Check that the mount directory is empty. We stopped the container, so it
    # should be, but if it's not, we should bail now or risk bricking the
    # container.
    aufs_mnt = os.path.join(AUFS_MNT_DIR, aufs_id)
    if os.listdir(aufs_mnt):
        raise Exception("abort wipe: mnt is not empty: %s", aufs_mnt)

    aufs_container = os.path.join(AUFS_DIFF_DIR, aufs_id)
    aufs_outbound = os.path.join(AUFS_DIFF_DIR, "-".join([restore_id, "out"]))
    aufs_inbound = os.path.join(AUFS_DIFF_DIR, "-".join([restore_id, "in"]))
    os.mkdir(aufs_inbound, 0o755)

    # This is the "critical section". If Docker tries to access the container
    # while we're swapping these two directories (which is NOT atomic), then
    # we'll have bricked the container (we won't have lost any data, though, so
    # all in all we failed to make things better but we did not actively make
    # anything worse).
    logger.info("%s: rename: start: %s", cg.name(), restore_id)
    os.rename(aufs_container, aufs_outbound)
    try:
        os.rename(aufs_inbound, aufs_container)
    except Exception:
        os.rename(aufs_outbound, aufs_container)
        raise
    logger.info("%s: rename: done: %s", cg.name(), restore_id)

    backup = os.path.join(BACKUP_DIR, "{0}-{1}".format(cg.name(), restore_id))
    logger.info("%s: backup to: %s", cg.name(), backup)

    mkdir_p(os.path.dirname(backup))
    os.rename(aufs_outbound, backup)


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise
