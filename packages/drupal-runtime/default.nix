{ pkgs }:

let
  inherit (pkgs) lib;

  # GD needs the AVIF codec, not the thumbnailer and its desktop dependencies.
  # Keep codec tools available in a separate output so upstream tests can still
  # exercise them without putting them in the image's runtime closure.
  libavif = pkgs.libavif.overrideAttrs (previous: {
    outputs = previous.outputs ++ [ "tools" ];
    cmakeFlags = map (
      flag: if flag == "-DAVIF_BUILD_GDK_PIXBUF=ON"
      then "-DAVIF_BUILD_GDK_PIXBUF=OFF" else flag
    ) previous.cmakeFlags;
    nativeBuildInputs = builtins.filter (
      input: input != pkgs.gdk-pixbuf && input != pkgs.makeWrapper
    ) previous.nativeBuildInputs;
    buildInputs = builtins.filter (input: input != pkgs.gdk-pixbuf) previous.buildInputs;
    env = builtins.removeAttrs previous.env [ "PKG_CONFIG_GDK_PIXBUF_2_0_GDK_PIXBUF_MODULEDIR" ];
    postInstall = ''
      mkdir -p $tools
      mv $out/bin $tools/bin
    '';
  });
  gd = pkgs.gd.override { inherit libavif; };

  # PHP needs the connection library, not PostgreSQL server tools, OAuth/Curl,
  # Kerberos, or translated messages. Retain TLS and password authentication.
  libpq = pkgs.libpq.override {
    curlSupport = false;
    gssSupport = false;
    nlsSupport = false;
  };

  phpBase = pkgs.php84.override {
    cgiSupport = false;
    cliSupport = false;
    fpmSupport = false;
    pearSupport = false;
    phpdbgSupport = false;
    systemdSupport = false;
    valgrindSupport = false;
    phpAttrsOverrides = final: previous: {
      buildInputs = previous.buildInputs ++ [ pkgs.libxml2.dev ];
      configureFlags = previous.configureFlags ++ [
        "--with-libxml=${pkgs.libxml2.dev}"
        "--enable-xml"
      ];
    };
  };

  # Development needs a conventional CLI, but none of PHP's other SAPIs or
  # package managers. Keep its build options aligned with embedded PHP.
  phpCli = phpBase.override { cliSupport = true; };

  frankenphpRaw = (pkgs.frankenphp.override { php = phpBase; }).overrideAttrs (_: {
    # Select the production or development environment in the wrappers below.
    preFixup = "";
  });

  # Use nixpkgs' Composer bootstrap PHAR without its PHP/tool wrapper closure.
  composer = pkgs.php84.packages.composer;
  composerPhar = pkgs.fetchurl {
    passthru.version = composer.version;
    url = "https://github.com/composer/composer/releases/download/${composer.version}/composer.phar";
    hash = composer.pharHash;
  };

  runtimeExtensionNames = [
    "ctype"
    "curl"
    "dom"
    "fileinfo"
    "filter"
    "gd"
    "iconv"
    "intl"
    "mbstring"
    "opcache"
    "openssl"
    "pdo"
    "pdo_pgsql"
    "pdo_sqlite"
    "session"
    "simplexml"
    "sodium"
    "tokenizer"
    "xmlreader"
    "xmlwriter"
    "zip"
    "zlib"
  ];

  developmentExtensionNames = [
    "pcntl"
    "posix"
    "soap"
  ];

  mkFrankenphp = name: phpEnvironment:
    pkgs.runCommand name { nativeBuildInputs = [ pkgs.makeBinaryWrapper ]; } ''
      mkdir -p $out/bin
      makeWrapper ${lib.getExe frankenphpRaw} $out/bin/frankenphp \
        --set PHP_INI_SCAN_DIR ${phpEnvironment}/lib
    '';

  # Custom extensions receive the actual PHP build, so their ABI matches both
  # FrankenPHP's embedded PHP and the conventional CLI used by Composer.
  mkRuntime =
    {
      name ? "drupal",
      applicationRoot ? "/opt/drupal",
      extraExtensionNames ? [ ],
      extraExtensions ? php: [ ],
      extraConfig ? "",
    }:
    let
      mkPhpEnvironment = php: development:
        php.buildEnv {
          extensions = { all, ... }:
            map (extension:
              if extension == "gd" then all.gd.overrideAttrs (old: {
                buildInputs = map (input: if input == pkgs.gd then gd else input) old.buildInputs;
                configureFlags = map (
                  flag: lib.replaceStrings [ "${pkgs.gd.dev}" ] [ "${gd.dev}" ] flag
                ) old.configureFlags;
              }) else if extension == "pdo_pgsql" then all.pdo_pgsql.overrideAttrs (old: {
                configureFlags = map (
                  flag: lib.replaceStrings [ "${pkgs.libpq.pg_config}" ] [ "${libpq.pg_config}" ] flag
                ) old.configureFlags;
              }) else all.${extension}
            ) (
              runtimeExtensionNames
              ++ extraExtensionNames
              ++ lib.optionals development developmentExtensionNames
            )
            ++ extraExtensions php
            ++ lib.optional development (php.extensions.xdebug.overrideAttrs (_: {
              # The extension test suite needs a standalone CLI, unavailable in
              # FrankenPHP's PHP build. Image tests exercise Xdebug instead.
              doCheck = false;
            }));
          extraConfig = builtins.readFile ./config/php.ini
            + "\n" + extraConfig
            + lib.optionalString development ("\n" + builtins.readFile ./config/dev.ini);
        };

      phpProduction = mkPhpEnvironment frankenphpRaw.php false;
      phpDevelopment = mkPhpEnvironment frankenphpRaw.php true;
    in
    {
      inherit applicationRoot composerPhar;
      frankenphpProduction = mkFrankenphp "frankenphp-${name}" phpProduction;
      frankenphpDevelopment = mkFrankenphp "frankenphp-${name}-dev" phpDevelopment;

      # Composer @php scripts and PHPUnit child processes require PHP_BINARY
      # and the CLI flag interface provided by a conventional PHP executable.
      phpCliProduction = mkPhpEnvironment phpCli false;
      phpCliDevelopment = mkPhpEnvironment phpCli true;

      caddyfile = ./config/Caddyfile;
      caddyHttps = ./config/Caddyfile.https;
      caddySite = ./config/site.Caddyfile;
      caddyGlobal = ./config/global.Caddyfile;
      environment = ./scripts/environment.php;
      scripts = {
        php = ./scripts/php;
        composer = ./scripts/composer;
        serveProject = ./scripts/serve-project;
        startServer = ./scripts/start-server;
      };
    };
in
(mkRuntime { }) // { inherit mkRuntime; }
