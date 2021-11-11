PostgreSQL
==========

An [Ansible][ansible] role for installing and managing [PostgreSQL][postgresql] servers. This role works with both
Debian and RedHat based systems, and provides backup scripts for [PostgreSQL Continuous Archiving and Point-in-Time
Recovery][postgresql_pitr].

On RedHat-based platforms, the [PostgreSQL Global Development Group (PGDG) packages][pgdg_yum] packages will be
installed. On Debian-based platforms, you can choose from the distribution's packages (from APT) or the [PGDG
packages][pgdg_apt].

[ansible]: http://www.ansible.com/
[postgresql]: http://www.postgresql.org/
[postgresql_pitr]: http://www.postgresql.org/docs/9.4/static/continuous-archiving.html
[pgdg_yum]: http://yum.postgresql.org/
[pgdg_apt]: http://apt.postgresql.org/

**Changes that require a restart will not be applied unless you manually restart PostgreSQL.** This role will reload the
server for those configuration changes that can be updated with only a reload because reloading is a non-intrusive
operation, but options that require a full restart will not cause the server to restart.

Requirements
------------

This role requires Ansible 2.4+

Role Variables
--------------

### All variables are optional ###

- `postgresql_user_name`: System username to be used for PostgreSQL (default: `postgres`).

- `postgresql_version`: PostgreSQL version to install. On Debian-based platforms, the default is whatever version is
  pointed to by the `postgresql` metapackage). On RedHat-based platforms, the default is `10`.

- `postgresql_flavor`: On Debian-based platforms, this specifies whether you want to use PostgreSQL packages from pgdg
  or the distribution's apt repositories. Possible values: `apt`, `pgdg` (default: `apt`).

- `postgresql_conf`: A list of hashes (dictionaries) of `postgresql.conf` options (keys) and values. These options are
  not added to `postgresql.conf` directly - the role adds a `conf.d` subdirectory in the configuration directory and an
  include statement for that directory to `postgresql.conf`. Options set in `postgresql_conf` are then set in
  `conf.d/25ansible_postgresql.conf`. For legacy reasons, this can also be a single hash, but the list syntax is
  preferred because it preserves order.

  Due to YAML parsing, you must take care when defining values in
  `postgresql_conf` to ensure they are properly written to the config file. For
  example:

  ```yaml
  postgresql_conf:
    - max_connections: 250
    - archive_mode: "off"
    - work_mem: "'8MB'"
  ```

  Becomes the following in `25ansible_postgresql.conf`:

  ```
  max_connections = 250
  archive_mode = off
  work_mem: '8MB'
  ```

- `postgresql_pg_hba_conf`: A list of lines to add to `pg_hba.conf`

- `postgresql_pg_hba_local_postgres_user`: If set to `false`, this will remove the `postgres` user's entry from
  `pg_hba.conf` that is preconfigured on Debian-based PostgreSQL installations. You probably do not want to do this
  unless you know what you're doing.

- `postgresql_pg_hba_local_socket`: If set to `false`, this will remove the `local` entry from `pg_hba.conf` that is
  preconfigured by the PostgreSQL package.

- `postgresql_pg_hba_local_ipv4`: If set to `false`, this will remove the `host ... 127.0.0.1/32` entry from
  `pg_hba.conf` that is preconfigured by the PostgreSQL package.

- `postgresql_pg_hba_local_ipv6`: If set to `false`, this will remove the `host ... ::1/128` entry from `pg_hba.conf`
  that is preconfigured by the PostgreSQL package.

- `postgresql_pgdata`: Only set this if you have changed the `$PGDATA` directory from the package default. Note this
  does not configure PostgreSQL to actually use a different directory, you will need to do that yourself, it just allows
  the role to properly locate the directory.

- `postgresql_conf_dir`: As with `postgresql_pgdata` except for the configuration directory.

### Backups ###

- `postgresql_backup_dir`: If set, enables [PITR][postgresql_pitr] backups. Set this to a directory where your database
  will be backed up (this can be any format supported by rsync, e.g. `user@host:/path`). The most recent backup will be
  in a subdirectory named `current`.

- `postgresql_backup_local_dir`: Filesystem path on the PostgreSQL server where backup scripts will be placed.

- `postgresql_backup_[hour|minute]`: Controls what time the cron job will run to perform a full backup. Defaults to 1:00
  AM.

- `postgresql_backup_[day|month|weekday]`: Additional cron controls for when the full backup is performed (default:
  `*`).

- `postgresql_backup_post_command`: Arbitrary command to run after successful completion of a scheduled backup.

Additional options pertaining to backups can be found in the [defaults file](defaults/main.yml).

Dependencies
------------

Backup functionality requires Python 2.7 or 3.5+, psycopg2, and rsync. Note that if installing PGDG versions of
PostgreSQL on Enterprise Linux, corresponding psycopg2 packages are available from the PGDG yum repositories.

Example Playbook
----------------

Standard install: Default `postgresql.conf`, `pg_hba.conf` and default version for the OS:

```yaml
---

- hosts: dbservers
  remote_user: root
  roles:
    - postgresql
```

Use the pgdg packages on a Debian-based host:

```yaml
---

- hosts: dbservers
  remote_user: root
  vars:
    postgresql_flavor: pgdg
  roles:
    - postgresql
```

Use the PostgreSQL 9.5 packages and set some `postgresql.conf` options and `pg_hba.conf` entries:

```yaml
---

- hosts: dbservers
  remote_user: root
  vars:
    postgresql_version: 9.5
    postgresql_conf:
      - listen_addresses: "''"    # disable network listening (listen on unix socket only)
      - max_connections: 50       # decrease connection limit
    postgresql_pg_hba_conf:
      - host all all 10.0.0.0/8 md5
  roles:
    - postgresql
```

Enable backups to /archive

```yaml
- hosts: all
  remote_user: root
  vars:
    postgresql_backup_dir: /archive
  roles:
    - postgresql
```

License
-------

[Academic Free License ("AFL") v. 3.0][afl]

[afl]: http://opensource.org/licenses/AFL-3.0

Author Information
------------------

[Nate Coraor](https://github.com/natefoo)  
