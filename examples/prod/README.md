# Production deployment

This directory is a standalone deployment using `ghcr.io/wotnak/farmos:4`,
PostgreSQL 17, and a separate Drupal cron service. Copy the whole directory to
your server. It requires Docker Engine and Docker Compose v2 or newer;
Nix, Task, and the rest of this repository are not needed.

## Configure and start

Run commands from this directory:

```sh
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

Put the generated value into `FARMOS_DB_PASS`. Keep it stable and retain `.env`
with your backups. The image generates its hash salt in `private_files/hash_salt`.
Leave `FARMOS_HASH_SALT` empty unless you want to supply an explicit salt.
Set `FARMOS_DOMAIN` to the hostname users will visit, without a scheme or port.
Compose uses the directory name as the project name. Keep it stable so updates
reuse the same volumes. Give separate deployments different directory names
and host ports.

Both application services use `ghcr.io/wotnak/farmos:4` in `compose.yaml`.
This tag follows the latest stable farmOS 4 release. To pin an exact build,
set an image digest in the shared `x-app` block.

The default `.env` serves local HTTP at `http://localhost:8080`. For an
external HTTPS proxy, keep these port settings and `FARMOS_AUTO_HTTPS=false`.
Set the public `FARMOS_DOMAIN` and explicit `FARMOS_TRUSTED_PROXIES`.

For automatic public HTTPS, change these values in `.env`:

```dotenv
FARMOS_DOMAIN=farm.example.com
FARMOS_AUTO_HTTPS=true
FARMOS_BIND_ADDRESS=0.0.0.0
FARMOS_PORT=80
FARMOS_HTTPS_PORT=443
```

Point the hostname's DNS records at this server and allow inbound TCP ports 80
and 443. The bundled Caddy server obtains and renews public certificates, with
certificate state stored in the private-files volume. Use a public hostname
for this mode. Both port mappings are defined in `compose.yaml`; the HTTPS
listener is active only when `FARMOS_AUTO_HTTPS=true`.

For an HTTPS proxy running on the host, forward to `http://127.0.0.1:8080`.
The proxy must preserve `Host` and overwrite forwarded client IP and protocol
headers. Set `FARMOS_TRUSTED_PROXIES` to its source IP addresses or CIDRs as seen
by the application. A proxy in another container needs an explicitly shared
Docker network; that container's loopback address is not the host backend.

Then start the deployment:

```sh
docker compose config --quiet
docker compose pull
docker compose up -d --wait
docker compose ps
```

Visit the configured URL and complete the farmOS browser installer, including
the administrator account. Database credentials come from the environment.
The health check confirms that the web server responds; it does not mean farmOS
has been installed. Cron runs every 900 seconds, configurable through
`FARMOS_CRON_INTERVAL`.

## Database settings

This example includes PostgreSQL. The application reads `FARMOS_DB_DRIVER`,
`FARMOS_DB_HOST`, `FARMOS_DB_PORT`, `FARMOS_DB_NAME`, `FARMOS_DB_USER`, and
`FARMOS_DB_PASS` directly. The database service receives its native `POSTGRES_*`
variables through Compose. An empty port selects the driver's default.

The image also supports SQLite. See [database configuration](../../docs/database.md)
and the standalone [SQLite example](../prod-sqlite/README.md). Selecting a driver does not replace the PostgreSQL service in this file.

## Storage and network access

The application and cron run as UID/GID 65532 with a read-only root filesystem,
dropped capabilities, bounded temporary filesystems, and resource limits.
Logs rotate at 10 MB with three files retained per service.

| Named volume | Contents |
| --- | --- |
| `database` | PostgreSQL data |
| `files` | Public uploads at `/opt/farmos/web/sites/default/files` |
| `private_files` | Drupal private files in `files/`, OAuth keys, Caddy certificates, and the generated hash salt under `/opt/farmos/private_files` |

Only the two application data directories above are persistently writable by
farmOS. PostgreSQL has no published port and uses only the internal backend
network. The application and cron also join a normal bridge network, allowing
outbound traffic for integrations, update checks, and certificate renewal.
The default port bindings accept connections only from the host.

## Operations and backups

```sh
docker compose logs --tail=100 -f farmos cron
docker compose exec farmos vendor/bin/drush status
docker compose exec farmos vendor/bin/drush cron
```

For a consistent backup, stop application writes and cron while capturing the
database and files. These commands cause downtime:

```sh
(
  set -eu
  umask 077
  backup="backups/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$backup"
  chmod 700 backups "$backup"
  docker compose stop farmos cron
  docker compose exec -T db sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup/database.dump"
  docker compose run --rm -T --no-deps --entrypoint /bin/tar farmos \
    -C /opt/farmos -czf - web/sites/default/files private_files > "$backup/files.tar.gz"
  cp .env "$backup/environment.env"
  cp compose.yaml "$backup/"
  container_id=$(docker compose ps -aq farmos)
  image_id=$(docker inspect --format '{{.Image}}' "$container_id")
  printf '%s\n' "$image_id" > "$backup/farmos-image.id"
  docker image inspect "$image_id" > "$backup/farmos-image.json"
  docker image save --output "$backup/farmos-image.tar" "$image_id"
  docker compose up -d --wait
)
```

The block stops on failure and leaves the application stopped for investigation.
The image archive preserves the exact application build, including when a tag
later changes. Keep copies off the host and test restoration. Backups contain
database credentials and private keys.

To restore into a fresh deployment with empty volumes, copy the backed-up
`environment.env` to `.env` and keep its secrets. Use a different directory
name if the original deployment still exists. Load and tag the saved application image:

```sh
(
  set -eu
  backup="backups/RESTORE"
  docker image load --input "$backup/farmos-image.tar"
  docker image tag "$(cat "$backup/farmos-image.id")" farmos-restored:recovery
)
```

Set `image: farmos-restored:recovery` in the shared `x-app` block in
`compose.yaml`. Start only `db`, and restore while farmOS and cron are stopped:

```sh
(
  set -eu
  docker compose up -d --wait db
  docker compose exec -T db sh -c 'exec pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backups/RESTORE/database.dump
  docker compose run --rm -T --no-deps --entrypoint /bin/tar farmos \
    -C /opt/farmos -xzf - < backups/RESTORE/files.tar.gz
  docker compose up -d --wait
)
```

Before an image update, back up the deployment and review farmOS release notes.
Pull the selected image, stop the application and cron, apply database updates,
then restart:

```sh
(
  set -eu
  docker compose pull
  docker compose stop farmos cron
  docker compose run --rm -T --no-deps --entrypoint /usr/bin/php farmos \
    /opt/farmos/vendor/drush/drush/drush.php updatedb -y
  docker compose run --rm -T --no-deps --entrypoint /usr/bin/php farmos \
    /opt/farmos/vendor/drush/drush/drush.php cache:rebuild
  docker compose up -d --wait
)
```

If an update fails, keep the application stopped and investigate or restore the
matching database, files, and image backup. Restarting an older image alone does
not undo database migrations. Keep the PostgreSQL major version at 17 until you
plan a database upgrade.

`docker compose down` preserves the named volumes. `docker compose down --volumes`
deletes this deployment's database and files.
