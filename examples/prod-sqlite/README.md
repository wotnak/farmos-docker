# Production deployment with SQLite

A standalone farmOS deployment with SQLite and Drupal cron. It needs no database
server or database password. Copy this directory to your server and run commands
here. Docker Engine and Compose v2 are required.

```sh
cp .env.example .env
chmod 600 .env
```

The image generates its hash salt in `private_files/hash_salt`. Leave
`FARMOS_HASH_SALT` empty unless you want to supply an explicit salt. Compose derives
the project and volume names from the directory name.

```sh
docker compose config --quiet
docker compose pull
docker compose up -d --wait
```

Open `http://localhost:8080` and complete the farmOS installer. The example sets
`FARMOS_DB_DRIVER=sqlite` and stores the database at
`/opt/farmos/private_files/database/farmos.sqlite`. Startup creates its directory.
The file and its journal remain in the persistent `private_files` volume, outside
Drupal's downloadable uploads. Web and cron have outbound network access.

For automatic HTTPS, set these values in `.env`, point DNS at the server, and
allow inbound TCP ports 80 and 443:

```dotenv
FARMOS_DOMAIN=farm.example.com
FARMOS_AUTO_HTTPS=true
FARMOS_BIND_ADDRESS=0.0.0.0
FARMOS_PORT=80
FARMOS_HTTPS_PORT=443
```

To back up the database and files together, stop both writers first:

```sh
(
  set -eu
  umask 077
  mkdir -p backups
  docker compose stop farmos cron
  docker compose run --rm -T --no-deps --entrypoint /bin/tar farmos \
    -C /opt/farmos -czf - web/sites/default/files private_files > backups/files.tar.gz
  cp .env backups/environment.env
  cp compose.yaml backups/
  docker compose up -d --wait
)
```

This causes downtime and leaves the application stopped if backup fails. Preserve
the exact application image alongside the archive. Keep backups privately off the
host and test restoration into empty volumes. Never copy only an active SQLite
database file, because pending changes may be in its journal.

`docker compose down` retains the volumes. `docker compose down --volumes` deletes
the database, uploads, keys, certificates, and generated hash salt.

See [database configuration](../../docs/database.md) for variables and driver details.
