# Runtime image with your own application

This standalone example runs an installed farmOS Composer project with the
`-runtime` image, PostgreSQL, and Drupal cron. The image supplies PHP and
FrankenPHP. You supply the application code, Composer dependencies, and Drupal
settings. Use the [production example](../prod/README.md) to run the bundled
farmOS application instead.

Run these commands from this directory:

```sh
cp .env.example .env
chmod 600 .env
```

Set `FARMOS_PROJECT_PATH` to your project's absolute path and set
`FARMOS_DB_PASS`. The project needs `web/index.php`, `vendor/autoload.php`, and
Drush installed through Composer. Its `web/sites/default/settings.php` must
configure the database, trusted hosts/proxies, hash salt, and file paths.
The [built-in settings template](../../docs/database.md#development-and-supplied-projects)
can provide these settings from the environment.

Prepare writable storage, substituting your project path:

```sh
project=/absolute/path/to/your/project
mkdir -p "$project/web/sites/default/files" "$project/private_files/files" "$project/private_files/keys"
sudo chown -R 65532:65532 "$project/web/sites/default/files" "$project/private_files"
docker compose config --quiet
docker compose pull
docker compose up -d --wait
```

The project is mounted read-only at `/opt/farmos`. Only public files and
`private_files` are writable; all project files must be readable by UID 65532.
Set Drupal's private file path to `/opt/farmos/private_files/files` and keep
OAuth keys in `/opt/farmos/private_files/keys`.

HTTP defaults to `http://localhost:8080`. Automatic HTTPS uses the same
environment settings as the [production example](../prod/README.md).
The application and cron have outbound network access; PostgreSQL stays on the
internal network. `FARMOS_CRON_INTERVAL` defaults to 900 seconds.

Back up your application code, PostgreSQL database, and both writable file
directories together. The PostgreSQL backup commands in the production example
also apply here. Stop web and cron writes before taking a consistent backup.
