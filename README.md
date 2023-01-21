# farmos-docker

Custom [farmOS](https://farmos.org) docker image.

Compared to the [official farmOS docker image](https://hub.docker.com/r/farmos/farmos) this one:

- is configurable with environment variables
- runs as non root user
- is half the size (around ~480MB compared to ~960MB)
- automatically installs pg_trgm[^pg_trgm] db extension when using [PostgreSQL](https://www.postgresql.org)

## Configuration

A container using this image is configurable through environment variables:

- `FARMOS_DOMAIN` - domain (or hostname/ip) used to access farmOS instance
- `FARMOS_DB_HOST` - database host
- `FARMOS_DB_PORT` - database port
- `FARMOS_DB_NAME` - database name
- `FARMOS_DB_USER` - database user
- `FARMOS_DB_PASS` - database password
- `FARMOS_DB_DRIVER` - database driver (`pgsql`|`mysql`)

[^pg_trgm]: pg_trgm postgres extension is recommended for Drupal 9 and [required](https://www.drupal.org/project/farm/issues/3270558) for Drupal 10
