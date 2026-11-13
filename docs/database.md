# Database configuration

The bundled farmOS image reads database settings directly from `FARMOS_DB_*`.
Its built-in `settings.php` selects the Drupal driver before installation, so the
browser installer only asks for site and administrator details.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FARMOS_DB_DRIVER` | `pgsql` | `pgsql` or `sqlite`. |
| `FARMOS_DB_HOST` | `db` | PostgreSQL server hostname. |
| `FARMOS_DB_PORT` | `5432` | PostgreSQL server port; an empty value selects the default. |
| `FARMOS_DB_NAME` | `farmos` | Server database name. For SQLite, an absolute file path, defaulting to `/opt/farmos/private_files/database/farmos.sqlite`. |
| `FARMOS_DB_USER` | `farm` | PostgreSQL username. |
| `FARMOS_DB_PASS` | none | Required for PostgreSQL; ignored for SQLite. |

`FARMOS_HASH_SALT` is optional. When unset or empty, the built-in settings generate
a random salt and save it to `/opt/farmos/private_files/hash_salt` with mode `0600`.
Web and cron share that file, and the salt survives container replacement through
the private-files volume. Keep the volume with your backups.

A supplied `FARMOS_HASH_SALT` takes precedence and must contain at least 32
characters. It does not overwrite the saved file. Removing the override selects
the saved salt, or generates one if no file exists. A corrupt or unreadable saved salt stops startup instead of silently
replacing it.

`FARMOS_DOMAIN` controls the hostname and trusted-host configuration independently
of the database.

The image supports only `pgsql` and `sqlite`. It rejects unsupported drivers,
invalid server ports, and relative SQLite paths. It never writes database credentials into `settings.php`.

## Deployment examples

Each example is a standalone directory with one Compose file and an `.env.example`:

- [PostgreSQL](../examples/prod/README.md)
- [SQLite](../examples/prod-sqlite/README.md)

`FARMOS_DB_DRIVER` selects the application's connection settings. Use the matching
deployment example, or supply your own server and container configuration.

The PostgreSQL service receives `POSTGRES_*`, as required by the upstream image.
Compose maps the `FARMOS_DB_*` settings to these service variables. The farmOS
container uses only `FARMOS_DB_*`.

Drupal 11 requires PostgreSQL 16 or newer with `pg_trgm`, or SQLite 3.45 or newer.
The bundled SQLite library meets that requirement.
See [Drupal database requirements](https://www.drupal.org/docs/getting-started/system-requirements/database-server-requirements)
and [farmOS installation](https://farmos.org/hosting/install/).

## Libraries in the image

All runtime variants include `pdo_pgsql` and `pdo_sqlite`.
PostgreSQL uses libpq with TLS and password authentication; its PHP connection
library excludes optional Kerberos, OAuth/Curl, and message translations.
SQLite includes its library without the SQLite command-line program.

Production images contain no database server or database CLI tools. Development
images retain their existing PostgreSQL tools for development and backups.

## SQLite storage and backups

SQLite ignores the host, port, username, and password variables. Startup creates
the database's parent directory as UID/GID 65532. Keep the file under the mounted
`private_files/database` directory, outside both the document root and Drupal's
private file tree at `private_files/files`. The containing directory must be writable too,
because SQLite creates journal files beside the database.

The SQLite example needs no database container or database password. Its
`private_files` volume holds the database, Drupal private files, OAuth keys, certificates,
and generated hash salt. Stop both application and cron before copying this
volume for a consistent backup. Restore the matching public-files volume and application
image as well. Do not copy an active SQLite database file alone.

## Development and supplied projects

Bundled development images use the same environment-driven settings when any
`FARMOS_DB_*` setting is supplied. This replaces `sites/default/settings.php` with
the bundled template and generates a persistent salt unless an override is
supplied. Without database variables, development images keep their interactive
installation and writable settings.

Runtime-only images preserve a supplied project's settings. To opt into this
configuration, copy `/usr/share/farmos/settings.php` from the image into your
project's `web/sites/default/settings.php`. The image also supplies the shared
`/usr/share/farmos/database.php`, `/usr/share/farmos/hash-salt.php`, and
`/usr/share/farmos/environment.php` helpers.
Review this template before replacing a project's custom settings.

## Verification

`task database-test` builds the production image and tests settings validation,
real PostgreSQL connections through Drupal's database API, farmOS
installation with both drivers, and SQLite writes that survive container
replacement. CI runs the same checks on both image
architectures before publication.

To test a loaded image directly:

```sh
DB_TEST_IMAGE=ghcr.io/wotnak/farmos:4 python3 tests/test-database-settings.py
```
