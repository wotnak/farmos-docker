# Production deployment with contrib modules

This is a standalone production Compose project with a custom farmOS image.
Copy this whole directory to your server. It requires Docker Engine and Docker
Compose 2.24.4 or newer. Nix and the rest of this repository are not required.

The example installs Ledger from the module requirements in
`dependencies/composer.json`. Change that file to select other compatible
modules. Installing package code does not enable its module in Drupal; enable
Ledger after completing the farmOS installer.

## Image construction

The Dockerfile copies the production project's code and settings into a matching
development runtime, adds the module requirements, and resolves fresh compatible
Composer dependencies without development packages. It copies the result into
the production runtime with the production startup scripts. Composer, Git,
Xdebug, PHPUnit and development dependencies stay out of the final image. A
temporary Composer mount checks the installed packages against the final
production PHP extensions during the build.

Application code is read-only. Settings read secrets and deployment addresses
from environment variables. Public uploads, Drupal private files, OAuth keys,
certificates, and the generated hash salt use data volumes.

Set `FARMOS_BASE_IMAGE`, `FARMOS_BUILD_IMAGE` and `FARMOS_RUNTIME_IMAGE` to matching
production, `-dev-runtime` and `-runtime` images. Their default major tags follow
the latest stable farmOS 4 release. Use matching published image digests to select
specific base images. The Docker build context excludes `.env`, backups and
other local files.

## Configure, build and install

Run these commands from this directory:

```sh
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Put the generated value into `FARMOS_DB_PASS` and keep it stable. The image generates its hash salt in `private_files/hash_salt`.
Leave `FARMOS_HASH_SALT` empty unless you want to supply an explicit salt.
Set `FARMOS_DOMAIN` to the hostname users will visit, without a scheme or port. Both application services
use the image from the shared `x-app` block in `compose.yaml`, initially
`farmos-contrib:local`. For each deployment or release, set a unique tag there.

Choose the mode in `.env`:

| Mode | Configuration |
| --- | --- |
| Local HTTP | `COMPOSE_FILE=compose.yaml`, `FARMOS_DOMAIN=localhost`, `FARMOS_AUTO_HTTPS=false`; open `http://localhost:8080`. |
| External HTTPS proxy | Keep the base Compose file and `FARMOS_AUTO_HTTPS=false`; set the public domain and exact `FARMOS_TRUSTED_PROXIES` addresses or CIDRs. |
| Automatic public HTTPS | `COMPOSE_FILE=compose.yaml:compose.https.yaml` and a public domain; the overlay exposes ports 80 and 443 and enables certificate issuance. |

For automatic HTTPS, point DNS at the server and allow inbound TCP ports 80/443.
The web service has outbound access for certificate renewal and
stores certificate state in the private-files volume. Do not use it for localhost.
For a host reverse proxy, forward to `http://127.0.0.1:8080`, preserve `Host`, and
overwrite forwarded client IP/protocol headers. Trust only that proxy's source
addresses as seen by farmOS. A proxy container needs an explicitly shared Docker
network; its loopback address does not reach this backend.

Build before starting either application service:

```sh
(
  set -eu
  docker compose config --quiet
  docker compose build --pull --no-cache farmos
  docker compose pull db
  docker compose up -d --wait --no-build
)
```

Visit the configured URL and finish the farmOS browser installer. Database
credentials come from the environment. Then enable the selected contrib module:

```sh
docker compose exec farmos vendor/bin/drush en farm_ledger -y
docker compose exec farmos vendor/bin/drush cache:rebuild
docker compose exec farmos vendor/bin/drush status
```

Enable each module by its Drupal machine name, which may differ from its Composer
package name. Review its documentation and permissions before exposing new
functionality to users. The server health check succeeds before installation;
it is not an application installation check.

## Change modules or update farmOS

Edit the requirements in `dependencies/composer.json` to add or remove packages.
For example:

```json
{
  "require": {
    "drupal/farm_ledger": "*",
    "drupal/farm_calendar": "*"
  }
}
```

The build resolves the latest versions compatible with the selected base
project. Use `docker compose build --pull --no-cache farmos` to refresh both base
images and Composer dependencies. The generated `composer.lock` is included in
the resulting image. Retain that image for rollback and test it before deployment.
For package removal, uninstall the Drupal module before deploying code without
it. Private package credentials should use BuildKit secrets in a locally adapted
Dockerfile.

After backing up, set `image:` in the shared `x-app` block in `compose.yaml` to a
new tag, then build the image.
Keep the previous image available for recovery. Apply database updates while the
web and cron services are stopped:

```sh
(
  set -eu
  docker compose build --pull --no-cache farmos
  docker compose stop farmos cron
  docker compose run --rm -T --no-deps --entrypoint /usr/bin/php farmos \
    /opt/farmos/vendor/drush/drush/drush.php updatedb -y
  docker compose run --rm -T --no-deps --entrypoint /usr/bin/php farmos \
    /opt/farmos/vendor/drush/drush/drush.php cache:rebuild
  docker compose up -d --wait --no-build
)
```

A failed update leaves the application stopped. Investigate or restore the
matching database, files and image. Reverting the image alone does not undo
schema changes. Newly added modules still need `drush en MODULE -y`.

## Database settings

This example includes PostgreSQL. The application reads `FARMOS_DB_DRIVER`,
`FARMOS_DB_HOST`, `FARMOS_DB_PORT`, `FARMOS_DB_NAME`, `FARMOS_DB_USER`, and
`FARMOS_DB_PASS` directly. The database service receives its native `POSTGRES_*`
variables through Compose. An empty port selects the driver's default.

The image also supports SQLite. See [database configuration](../../docs/database.md)
and the standalone [SQLite example](../prod-sqlite/README.md). Selecting a driver does not replace the PostgreSQL service in this file.

## Storage, network and backups

The application and cron run as UID/GID 65532, with read-only root filesystems,
dropped capabilities, bounded temporary storage, resource limits and rotating
logs. PostgreSQL has no published port. Cron runs every 900 seconds by default.

The `database` volume holds PostgreSQL data. `files` holds public uploads under
`/opt/farmos/web/sites/default/files`. `private_files` holds private attachments,
OAuth keys, Caddy certificates, and the generated hash salt under `/opt/farmos/private_files`. Never mount
a writable volume over the application code or the whole `sites` directory.

The database network is internal. The web service also joins a normal frontend
bridge so Docker can publish its ports; this allows web requests to make outbound
connections. Cron uses only the internal network by default. Append
`:compose.egress.yaml` to `COMPOSE_FILE` and recreate the services when scheduled
integrations need outbound access. PostgreSQL remains internal.

For a consistent backup, stop web and cron writes first. The following block
causes downtime and stops on failure; it does not restart after a failed backup:

```sh
(
  set -eu
  umask 077
  backup="backups/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$backup"
  image_id=$(docker inspect --format '{{.Image}}' "$(docker compose ps -aq farmos)")
  docker compose stop farmos cron
  docker image save --output "$backup/image.tar" "$image_id"
  printf '%s\n' "$image_id" > "$backup/image-id.txt"
  docker compose exec -T db sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup/database.dump"
  docker compose run --rm -T --no-deps --entrypoint /bin/tar farmos \
    -C /opt/farmos -czf - web/sites/default/files private_files > "$backup/files.tar.gz"
  cp .env "$backup/environment.env"
  cp compose.yaml "$backup/"
  cp Dockerfile "$backup/"
  cp -R dependencies "$backup/"
  docker compose images > "$backup/images.txt"
  docker compose up -d --wait --no-build
)
```

The backup includes the exact deployed application image. Record the base image
digests too. Keep backups off the host and test restoration; they contain
credentials and private keys. Restore into a fresh deployment with empty volumes.
Copy the backed-up `environment.env` to `.env` and preserve its secrets. Use a new
`COMPOSE_PROJECT_NAME` if the original deployment still exists. Load the image:

```sh
(
  set -eu
  docker image load --input backups/RESTORE/image.tar
  docker image tag "$(cat backups/RESTORE/image-id.txt)" farmos-contrib:restored
)
```

Set `image: farmos-contrib:restored` in the shared `x-app` block in
`compose.yaml`. Keep them stopped while restoring the database and files:

```sh
(
  set -eu
  docker compose up -d --wait db
  docker compose exec -T db sh -c 'exec pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/RESTORE/database.dump
  docker compose run --rm -T --no-deps --entrypoint /bin/tar farmos \
    -C /opt/farmos -xzf - < backups/RESTORE/files.tar.gz
  docker compose up -d --wait --no-build
)
```

Keep PostgreSQL on major version 17 until planning a database upgrade.
`docker compose down` preserves data; `docker compose down --volumes` deletes
this deployment's database, uploads, keys, certificates, and the generated hash salt.

The build follows Docker's [multi-stage build documentation](https://docs.docker.com/build/building/multi-stage/)
and Composer's [dependency update workflow](https://getcomposer.org/doc/01-basic-usage.md#updating-dependencies-to-their-latest-versions).
