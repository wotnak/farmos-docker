{
  pkgs,
  nix2container,
  profile,
  runtime,
  app,
}:

let
  inherit (pkgs) lib;
  baseTag = profile."image-tag";
  resolvedVersion = profile.resolved.version or profile."farmos-version";
  inherit (runtime)
    frankenphpProduction
    frankenphpDevelopment
    phpCliDevelopment
    composerPhar
    ;
  inherit (app) farmosProduction farmosDevelopment;

  imageName = profile."image-name";
  farmosUid = 65532;
  farmosGid = 65532;

  baseTools = pkgs.buildEnv {
    name = "farmos-base-tools";
    paths = [
      pkgs.busybox
      pkgs.cacert
      pkgs.tzdata
    ];
    pathsToLink = [
      "/bin"
      "/etc/ssl/certs"
      "/share/zoneinfo"
    ];
  };

  developmentTools = pkgs.buildEnv {
    name = "farmos-development-tools";
    paths = [
      pkgs.bashInteractive
      (pkgs.git.override {
        # Composer needs Git transport, not git-p4, Perl helpers, or manuals.
        pythonSupport = false;
        perlSupport = false;
        withManual = false;
      })
      pkgs.patch
      (pkgs.callPackage ./postgresql-client.nix { })
    ];
    pathsToLink = [
      "/bin"
      "/usr/bin"
    ];
  };

  mkRoot =
    {
      name,
      app ? null,
      frankenphp,
      development ? false,
      serverScript ? ./scripts/farmos-server,
    }:
    pkgs.runCommand name { } ''
      mkdir -p \
        $out/etc/frankenphp \
        $out/opt/farmos/private_files \
        $out/usr/bin \
        $out/usr/share/farmos \
        $out/tmp

      ${lib.optionalString (app != null) ''
        mkdir -p $out/opt/farmos/private_files/files $out/opt/farmos/private_files/keys
        cp -a ${app}/. $out/opt/farmos/
        chmod u+w $out/opt/farmos $out/opt/farmos/web/sites $out/opt/farmos/web/sites/default
        chmod u+w $out/opt/farmos/web/sites/default/default.settings.php
        cat >> $out/opt/farmos/web/sites/default/default.settings.php <<'EOF'

      // Drupal private files live outside the document root.
      $settings['file_private_path'] = '/opt/farmos/private_files/files';
      $config['simple_oauth.settings']['public_key'] = '/opt/farmos/private_files/keys/public.key';
      $config['simple_oauth.settings']['private_key'] = '/opt/farmos/private_files/keys/private.key';
      EOF
        mkdir -p $out/opt/farmos/config/sync
        # Drupal expects this marker even when sync storage is outside web/.
        printf 'Require all denied\n' > $out/opt/farmos/config/sync/.htaccess
        ${if development then ''
          cp -a $out/opt/farmos/web/sites $out/usr/share/farmos/sites
          cp ${./scripts/farmos-init-dev} $out/usr/bin/farmos-init
        '' else ''
          mkdir -p $out/opt/farmos/web/sites/default/files
          cp ${./settings.php} $out/opt/farmos/web/sites/default/settings.php
          cp $out/opt/farmos/web/sites/default/default.services.yml $out/opt/farmos/web/sites/default/services.yml
          chmod 0444 $out/opt/farmos/web/sites/default/settings.php $out/opt/farmos/web/sites/default/services.yml
          chmod 0555 $out/opt/farmos/web/sites $out/opt/farmos/web/sites/default
          cp ${./scripts/farmos-init} $out/usr/bin/farmos-init
        ''}
        chmod 0755 $out/usr/bin/farmos-init
      ''}
      cp ${runtime.caddyfile} $out/etc/frankenphp/Caddyfile
      cp ${runtime.caddyHttps} $out/etc/frankenphp/Caddyfile.https
      cp ${runtime.caddySite} $out/etc/frankenphp/site.Caddyfile
      cp ${runtime.caddyGlobal} $out/etc/frankenphp/global.Caddyfile
      cp ${runtime.environment} $out/usr/share/farmos/environment.php
      cp ${./database.php} $out/usr/share/farmos/database.php
      cp ${./hash-salt.php} $out/usr/share/farmos/hash-salt.php
      cp ${./settings.php} $out/usr/share/farmos/settings.php
      cp ${./scripts/farmos-init} $out/usr/share/farmos/farmos-init
      chmod 0755 $out/usr/share/farmos/farmos-init
      cp ${runtime.scripts.startServer} $out/usr/bin/farmos-http-server
      chmod 0755 $out/usr/bin/farmos-http-server
      cp ${./scripts/farmos-cron} $out/usr/bin/farmos-cron
      chmod 0755 $out/usr/bin/farmos-cron
      cp ${../tests/check-runtime.php} $out/usr/share/farmos/check-runtime.php
      cp ${runtime.scripts.php} $out/usr/bin/php
      cp ${serverScript} $out/usr/bin/farmos-server
      chmod 0755 $out/usr/bin/php $out/usr/bin/farmos-server
      ln -s ${lib.getExe' frankenphp "frankenphp"} $out/usr/bin/frankenphp
      ln -s /bin/env $out/usr/bin/env

      ${lib.optionalString development ''
        mkdir -p $out/usr/share/composer
        cp ${composerPhar} $out/usr/share/composer/composer.phar
        cp ${runtime.scripts.composer} $out/usr/bin/composer
        chmod 0755 $out/usr/bin/composer
      ''}

      ${lib.optionalString development ''
        rm $out/usr/bin/php
        ln -s ${lib.getExe phpCliDevelopment} $out/usr/bin/php
      ''}

      cat > $out/etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      farmos:x:${toString farmosUid}:${toString farmosGid}:farmOS:/opt/farmos:/bin/sh
      EOF
      cat > $out/etc/group <<'EOF'
      root:x:0:
      farmos:x:${toString farmosGid}:
      EOF
    '';

  productionRoot = mkRoot {
    name = "farmos-root";
    app = farmosProduction;
    frankenphp = frankenphpProduction;
  };

  runtimeRoot = mkRoot {
    name = "farmos-runtime-root";
    frankenphp = frankenphpProduction;
    serverScript = runtime.scripts.serveProject;
  };

  developmentRuntimeRoot = mkRoot {
    name = "farmos-dev-runtime-root";
    frankenphp = frankenphpDevelopment;
    development = true;
    serverScript = runtime.scripts.serveProject;
  };

  developmentRoot = mkRoot {
    name = "farmos-dev-root";
    app = farmosDevelopment;
    frankenphp = frankenphpDevelopment;
    development = true;
  };

  imageConfig = version: description: {
    Entrypoint = [ "/usr/bin/farmos-server" ];
    WorkingDir = "/opt/farmos";
    User = "${toString farmosUid}:${toString farmosGid}";
    Env = [
      "HOME=/opt/farmos"
      "DRUPAL_ROOT=${runtime.applicationRoot}"
      "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
      "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
      "XDG_CONFIG_HOME=/tmp/caddy/config"
      "XDG_DATA_HOME=/tmp/caddy/data"
    ];
    ExposedPorts = {
      "8080/tcp" = { };
      "8443/tcp" = { };
    };
    StopSignal = "SIGTERM";
    Labels = {
      "org.opencontainers.image.title" = "farmOS";
      "org.opencontainers.image.description" = description;
      "org.opencontainers.image.licenses" = "GPL-2.0-or-later";
      "org.opencontainers.image.version" = version;
    };
  };

  imagePermissions = root: [
    {
      path = root;
      regex = "/opt/farmos(/.*)?";
      uid = farmosUid;
      gid = farmosGid;
    }
    {
      path = root;
      regex = "/opt/farmos/web/sites/default/files";
      mode = "0755";
      uid = farmosUid;
      gid = farmosGid;
    }
    {
      path = root;
      regex = "/opt/farmos/private_files(/.*)?";
      mode = "0700";
      uid = farmosUid;
      gid = farmosGid;
    }
    {
      path = root;
      regex = "/tmp";
      mode = "1777";
      uid = farmosUid;
      gid = farmosGid;
    }
  ];

  baseLayer = nix2container.buildLayer {
    copyToRoot = baseTools;
    maxLayers = 4;
    metadata.created_by = "Nix base tools";
  };

  developmentToolsLayer = nix2container.buildLayer {
    copyToRoot = developmentTools;
    maxLayers = 4;
    metadata.created_by = "Nix development tools";
  };

  mkImage =
    {
      tag,
      root,
      config,
      development ? false,
    }:
    nix2container.buildImage {
      name = imageName;
      inherit tag config;
      copyToRoot = [ root ];
      layers = [ baseLayer ] ++ lib.optional development developmentToolsLayer;
      perms = imagePermissions root;
      maxLayers = 8;
    };

  productionImage = mkImage {
    tag = baseTag;
    root = productionRoot;
    config = imageConfig resolvedVersion "Minimal farmOS image served by FrankenPHP in classic mode";
  };

  runtimeImage = mkImage {
    tag = "${baseTag}-runtime";
    root = runtimeRoot;
    config = imageConfig resolvedVersion "farmOS PHP runtime for a supplied application";
  };

  developmentRuntimeImage = mkImage {
    tag = "${baseTag}-dev-runtime";
    root = developmentRuntimeRoot;
    config = imageConfig resolvedVersion "farmOS development PHP runtime and tools for a supplied application";
    development = true;
  };

  developmentImage = mkImage {
    tag = "${baseTag}-dev";
    root = developmentRoot;
    config = imageConfig resolvedVersion "farmOS development image with Composer, Xdebug, and test tools";
    development = true;
  };

in
  lib.optionalAttrs (builtins.elem "production" profile.variants) {
    default = productionImage;
    farmos = productionImage;
  }
  // lib.optionalAttrs (builtins.elem "development" profile.variants) {
    "farmos-dev" = developmentImage;
  }
  // lib.optionalAttrs (builtins.elem "runtime" profile.variants) {
    "farmos-runtime" = runtimeImage;
  }
  // lib.optionalAttrs (builtins.elem "development-runtime" profile.variants) {
    "farmos-dev-runtime" = developmentRuntimeImage;
  }
  // {
    "farmos-app" = farmosProduction;
    "farmos-dev-app" = farmosDevelopment;
    "frankenphp-farmos" = frankenphpProduction;
    "frankenphp-farmos-dev" = frankenphpDevelopment;
    inherit composerPhar;
  }
