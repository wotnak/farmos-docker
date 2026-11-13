# Deployment issues

## Published ports on an internal-only Docker network

Observed on 2026-09-28 with Docker Engine 29.4.0 on OrbStack. A web container
attached only to an `internal: true` network passed its in-container health check,
but its published localhost port refused connections. Docker recorded
`HostConfig.PortBindings`, while `NetworkSettings.Ports` showed `8080/tcp: null`.
Adding a normal bridge network made the same host port reachable.

PostgreSQL deployment examples under `examples/` attach the web service to a normal
`frontend` bridge as well as the internal database network. PostgreSQL remains
internal. In the simple production example, cron also joins the frontend by
default. In the contrib example, cron joins it through the optional egress
overlay. The web service has outbound access in both examples.

The web-only Docker setup test fixture under `tests/` deliberately uses an
internal-only network. Its checks send HTTP requests inside the container and
do not depend on host port publishing. Use the examples for deployment.

Related upstream reports:

- [Moby #36174: port publishing on internal networks](https://github.com/moby/moby/issues/36174)
- [Moby #44986: published ports with internal networks](https://github.com/moby/moby/issues/44986)
