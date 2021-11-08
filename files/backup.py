#!/usr/bin/env python
"""
Perform PostgreSQL PITR backups

See the documentation for details:
  https://www.postgresql.org/docs/current/continuous-archiving.html

This is intended to be run locally on the PostgreSQL server as the postgres
user, with an appropriate environment to connect to the desired PostgreSQL
instance. See the environment variables that control this if necessary.

This script is compatible with Python 2.7 and Python 3.5+
"""
from __future__ import print_function

import argparse
import bisect
import datetime
import errno
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import tempfile
try:
    from shlex import quote as shlex_quote
except ImportError:
    from pipes import quote as shlex_quote

import psycopg2


START_BACKUP_SQL = "SELECT pg_start_backup(%(label)s, false, false)"
STOP_BACKUP_SQL = "SELECT * FROM pg_stop_backup(false, true)"
RSYNC_EXCLUDES = (
    'pg_wal/*',  # >= 10
    'pg_xlog/*', # < 10
    'postmaster.pid',
    'postmaster.opts',
    'pg_replslot/*',
    'pg_dynshmem/*',
    'pg_notify/*',
    'pg_serial/*',
    'pg_snapshots/*',
    'pg_stat_tmp/*',
    'pg_subtrans/*',
    'pg_tmp*',
    'pg_internal.init',
)
BACKUP_LABEL_RE = re.compile(r"\d{8}T\d{6}Z")
LAST_SEGMENT_RE = re.compile(r"START WAL LOCATION:.*\(file ([^)]+)\)")

log = None


class Label(object):
    # for sorting
    def __init__(self, label):
        self.label = label
        self.date, self.time = [int(x) for x in label.rstrip('Z').split('T')]

    def __str__(self):
        return self.label

    def __eq__(self, other):
        return self.date == other.date and self.time == other.time

    def __lt__(self, other):
        return self.date <= other.date and self.time < other.time

    def __le__(self, other):
        return self.date <= other.date and self.time <= other.time

    def __gt__(self, other):
        return self.date >= other.date and self.time > other.time

    def __ge__(self, other):
        return self.date >= other.date and self.time >= other.time


class State(object):
    def __init__(self):
        self._conn = None
        self._cursor = None
        self._label = None
        self._rsync_opts = None

    def set_rsync_opts(self, opts):
        self._rsync_opts = opts

    @property
    def rsync_cmd(self):
        cmd = ['rsync']
        if self._rsync_opts:
            cmd.extend(shlex.split(rsync_opts))
        return cmd

    @property
    def conn(self):
        if not self._conn:
            log.info('Connecting to database')
            self._conn = psycopg2.connect('dbname=postgres')
        return self._conn

    @property
    def cursor(self):
        if not self._cursor:
            self._cursor = self.conn.cursor()
        return self._cursor

    @property
    def label(self):
        if not self._label:
            self._label = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            log.info('Backup label is: %s', self._label)
        return self._label


state = State()


def parse_args(argv):
    parser = argparse.ArgumentParser(description='Utility for performing PostgreSQL PITR backups')
    parser.add_argument('--backup', action='store_true', default=False, help='Perform backup')
    parser.add_argument('--keep', type=int, default=-1, help='Keep this many backups (default: all)')
    parser.add_argument('--clean-archive', action='store_true', default=False, help='Clean WAL archive')
    parser.add_argument('--rsync-connect-opts', default=None, help='Options to always pass to rsync (e.g. for connection parameters)')
    parser.add_argument('--rsync-backup-opts', default='-rptg', help='Options to pass to rsync for backup (default: -rptg)')
    parser.add_argument('--pg-bin-dir', default=None, help='Directory containing PostgreSQL auxiliary binaries if not on $PATH')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='Verbose output')
    parser.add_argument('backup_path', help='Backup to location (rsync-compatible string)')
    args = parser.parse_args(argv)
    if args.clean_archive and ':' in args.backup_path:
        parser.error('--clean-archive cannot be used with remote backup directories')
    return args


def configure_logging(verbose):
    logging_config = {}
    logging_config['level'] = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(**logging_config)
    global log
    log = logging.getLogger()


def log_command(cmd):
    log.debug('command is: %s', ' '.join([shlex_quote(x) for x in cmd]))


def initiate_backup():
    log.info("Initiating backup with pg_start_backup()")
    state.cursor.execute(START_BACKUP_SQL, {'label': state.label})


def perform_backup(backup_path, rsync_backup_opts):
    state.cursor.execute("SHOW data_directory")
    data_dir = state.cursor.fetchone()[0]
    rsync_data_dir = data_dir.rstrip('/') + os.sep
    rsync_backup_path = os.path.join(backup_path, state.label)

    # assemble rsync command line
    cmd = state.rsync_cmd
    cmd.extend(shlex.split(rsync_backup_opts))
    cmd.extend(['--delete', '--delete-delay'])
    [cmd.extend(['--exclude', exclude]) for exclude in RSYNC_EXCLUDES]
    cmd.extend([rsync_data_dir, rsync_backup_path])

    log.info('Performing rsync backup from %s to %s', *cmd[-2:])
    log_command(cmd)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 24:
            raise


def write_backup_file(backup_path, file_contents, file_name):
    file_path = os.path.join(backup_path, state.label, file_name)
    cmd = state.rsync_cmd
    # use a tempfile with rsync since the path might be remote
    mode = 'w' if isinstance(file_contents, str) else 'wb'
    with tempfile.NamedTemporaryFile(mode=mode, prefix='postgresql_backup_') as fh:
        fh.write(file_contents)
        fh.flush()
        cmd.extend([fh.name, file_path])
        log.info('Writing backup file at path: %s', file_path)
        log_command(cmd)
        subprocess.check_call(cmd)


def finalize_backup(backup_path):
    log.info("Finalizing backup with pg_stop_backup()")
    state.cursor.execute(STOP_BACKUP_SQL)
    row = state.cursor.fetchone()
    last_segment = row[0]
    backup_label = row[1]
    tablespace_map = row[2]
    log.info('Last WAL segment for this backup is: %s', last_segment)
    write_backup_file(backup_path, backup_label, 'backup_label')
    if tablespace_map:
        write_backup_file(backup_path, tablespace_map, 'tablespace_map')


def get_current_labels(backup_path):
    cmd = state.rsync_cmd
    cmd.extend(['--list-only', backup_path.rstrip('/') + '/'])
    out = subprocess.check_output(cmd)
    if sys.version_info > (3,):
        out = out.decode('utf-8')
    labels = []
    # there doesn't appear to be a way to format rsync --list-only output
    for line in out.splitlines():
        entry = line.split()[-1]
        if BACKUP_LABEL_RE.match(entry):
            label = Label(entry)
            bisect.insort(labels, label)
    return list(map(str, labels))


def rsync_delete_dirs(backup_path, labels):
    # can't use ssh here since I don't want to write a translator from rsync connect params to ssh
    temp_name = tempfile.mkdtemp(prefix="postgresql_backup_empty_")
    try:
        # empty the dirs first, unfortunately this has to be done one-by-one
        for label in labels:
            cmd = state.rsync_cmd
            cmd.extend(['-r', '--delete', temp_name + '/', os.path.join(backup_path, label)])
            log_command(cmd)
            subprocess.check_call(cmd)
        # then all the empty dirs can be deleted at once
        cmd = state.rsync_cmd
        [cmd.extend(['--include', label]) for label in labels]
        cmd.extend(['--exclude', '*', '-d', '--delete'])
        cmd.extend([temp_name + '/', backup_path])
        log_command(cmd)
        subprocess.check_call(cmd)
    finally:
        os.rmdir(temp_name)


def cleanup_old_backups(backup_path, keep):
    labels = get_current_labels(backup_path)
    if len(labels) > keep:
        delete_labels = labels[:(len(labels) - keep)]
        log.debug('The following backups will be removed due to --keep=%s: %s', keep, ', '.join(delete_labels))
        rsync_delete_dirs(backup_path, delete_labels)


def extract_last_segment_from_backup_label(backup_label):
    for line in backup_label.splitlines():
        match = LAST_SEGMENT_RE.match(line)
        if match:
            return match.group(1)
    return None


def cleanup_wal_archive(backup_path, pg_bin_dir):
    assert ':' not in backup_path  # this should be handled by the parser
    labels = get_current_labels(backup_path)
    if not labels:
        log.warning("No backups found, cannot clean WAL archive")
        return
    oldest_label = labels[0]
    backup_label_path = os.path.join(backup_path, oldest_label, 'backup_label')
    try:
        backup_label = open(backup_label_path).read()
    except:
        log.exception("Cannot read backup_label from oldest backup, WAL archive will not be cleaned")
        return
    last_segment = extract_last_segment_from_backup_label(backup_label)
    if not last_segment:
        log.warning("Could not determine last segment from oldest backup, WAL archive will not be cleaned")
        return
    log.info("Last segment in oldest backup (%s): %s", oldest_label, last_segment)
    log.info("Running pg_archivecleanup")
    wal_archive_path = os.path.join(backup_path, 'wal_archive')
    if pg_bin_dir:
        cmd = [os.path.join(pg_bin_dir, 'pg_archivecleanup')]
    else:
        cmd = ['pg_archivecleanup']
    cmd.extend(['-d', wal_archive_path, last_segment])
    log_command(cmd)
    try:
        subprocess.check_call(cmd)
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            log.error("Cannot find pg_archivecleanup (see --pg-bin-dir option)")
        raise


def main(argv):
    args = parse_args(argv)
    configure_logging(args.verbose)
    state.set_rsync_opts(args.rsync_connect_opts)
    start = time.time()
    if args.backup:
        initiate_backup()
        perform_backup(args.backup_path, args.rsync_backup_opts)
        finalize_backup(args.backup_path)
        log.info("Backup complete")
    if args.keep > 0:
        cleanup_old_backups(args.backup_path, args.keep)
    if args.clean_archive:
        cleanup_wal_archive(args.backup_path, args.pg_bin_dir)
    elapsed = time.time() - start
    log.info("Completed in %d seconds", elapsed)


if __name__ == '__main__':
    main(sys.argv[1:])
