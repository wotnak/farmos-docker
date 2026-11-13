{ lib, postgresql_17 }:

let
  # Keep TLS, SCRAM and GSSAPI authentication. The disabled features belong to
  # the database server, which runs in a separate container.
  postgresql = postgresql_17.override {
    icuSupport = false;
    pamSupport = false;
    systemdSupport = false;
    jitSupport = false;
    perlSupport = false;
    pythonSupport = false;
    tclSupport = false;
  };
  clients = [
    "psql"
    "pg_dump"
    "pg_dumpall"
    "pg_restore"
    "pg_isready"
    "createdb"
    "dropdb"
    "createuser"
    "dropuser"
    "pgbench"
    "clusterdb"
    "reindexdb"
    "vacuumdb"
  ];
in
postgresql.overrideAttrs (old: {
  # Prune inside the derivation so embedded bin paths reference this reduced
  # output. A symlink or copy from the full package would retain its closure.
  postInstall = old.postInstall + ''
    clientBin=$(mktemp -d)
    for command in ${lib.escapeShellArgs clients}; do
      mv "$out/bin/$command" "$clientBin/"
    done
    rm -rf "$out"
    mkdir -p "$out/bin"
    mv "$clientBin/"* "$out/bin/"
    rmdir "$clientBin"

    # Client programs need libpq, not the server's extension libraries or the
    # embedded-SQL development libraries installed by the upstream build.
    find "$lib/lib" -mindepth 1 -maxdepth 1 ! -name 'libpq.*' -exec rm -rf {} +
    find "$lib" -mindepth 1 -maxdepth 1 ! -name lib -exec rm -rf {} +
  '';

  # The original hook wraps initdb, which is deliberately absent here.
  postFixup = "";

  # Upstream's check-world needs the server removed above. Image integration
  # checks cover connections and a database dump/restore with these clients.
  doInstallCheck = false;

  meta = old.meta // {
    description = "PostgreSQL client tools and libpq without the database server";
    mainProgram = "psql";
  };
})
