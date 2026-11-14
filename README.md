# farmOS images with Nix

Container images for farmOS, built with Nix and served by FrankenPHP. Available
for AMD64 and ARM64 at `ghcr.io/wotnak/farmos`.

## Image variants

All images support AMD64 and ARM64. Use these tags with `ghcr.io/wotnak/farmos`:

| Variant | Tag | Contents |
| --- | --- | --- |
| Production | `4` | farmOS 4 with the production PHP runtime. |
| Development | `4-dev` | farmOS 4, Composer, Xdebug, Git, PostgreSQL tools, and test tools. |
| Runtime | `4-runtime` | Production PHP runtime; supply your own installed codebase. |
| Development runtime | `4-dev-runtime` | Development PHP and tools; supply your own codebase and test tools. |
| Development branch | `4.x-dev` | The upstream farmOS 4.x development branch with development tools. |

The release tags track the latest compatible farmOS 4 release. Pin an image
digest for a fixed deployment.

## Environment variables

The bundled image's settings read these variables directly:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FARMOS_DOMAIN` | `localhost` | Hostname or IPv4 address, without a scheme or port. |
| `FARMOS_DB_DRIVER` | `pgsql` | Database driver: `pgsql` or `sqlite`. |
| `FARMOS_DB_HOST` | `db` | PostgreSQL hostname. |
| `FARMOS_DB_PORT` | `5432` | PostgreSQL port; an empty value selects the default. |
| `FARMOS_DB_NAME` | See below | Database name or absolute SQLite file path. |
| `FARMOS_DB_USER` | `farm` | PostgreSQL username. |
| `FARMOS_DB_PASS` | Required for PostgreSQL | PostgreSQL password. |
| `FARMOS_HASH_SALT` | Generated and saved | Optional override of at least 32 characters; otherwise uses `private_files/hash_salt`. |
| `FARMOS_AUTO_HTTPS` | `false` | Enable automatic certificates for a public DNS hostname. |
| `FARMOS_TRUSTED_HOSTS` | Derived from `FARMOS_DOMAIN` | Comma-separated allowed hostnames or IP addresses. |
| `FARMOS_TRUSTED_PROXIES` | Empty | Comma-separated trusted proxy IP addresses or CIDRs. |

`FARMOS_DB_NAME` defaults to `farmos` for PostgreSQL, or
`/opt/farmos/private_files/database/farmos.sqlite` for SQLite. SQLite ignores
host, port, username, and password. Runtime-only images preserve your project's
settings; see [database configuration](docs/database.md) to use the built-in template.
Drupal private files live under `private_files/files`, separate from keys and other
internal data.

The standalone [PostgreSQL](examples/prod/README.md) and [SQLite](examples/prod-sqlite/README.md) Compose examples also accept:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FARMOS_BIND_ADDRESS` | `127.0.0.1` | Host address for published ports. |
| `FARMOS_PORT` | `8080` | Host HTTP port. |
| `FARMOS_HTTPS_PORT` | `8443` | Host HTTPS port. |
| `FARMOS_CRON_INTERVAL` | `900` | Seconds between Drupal cron runs. |

For public HTTPS, also configure the host bindings and ports as shown in the
chosen example. Development images accept `XDEBUG_MODE`, defaulting to
`develop,debug,coverage`; set it to `off` to disable Xdebug.

## Documentation

- [Deployment with contributed modules](examples/prod-contrib/README.md)
- [Runtime image with your own application](examples/runtime/README.md)
- [Build, test, and configure images](docs/guide.md)
