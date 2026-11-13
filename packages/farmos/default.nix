{
  pkgs,
  release ? null,
  branch ? null,
  releaseMajor ? pkgs.lib.versions.major release.version,
  releaseComposerSnapshot ? null,
  branchComposerSnapshot ? null,
}:

let
  inherit (pkgs) lib;

  farmosBranchTar = pkgs.fetchurl {
    url = "https://github.com/farmOS/farmOS/archive/${branch.farmosRev}.tar.gz";
    hash = branch.farmosSourceHash;
  };

  farmosBranchSource = pkgs.stdenvNoCC.mkDerivation {
    pname = "farmos-4x-source";
    version = "4.x";
    src = farmosBranchTar;
    dontPatchShebangs = true;
    dontFixup = true;
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -a ./. $out/
      runHook postInstall
    '';
  };

  composerProjectTar = pkgs.fetchurl {
    url = "https://github.com/farmOS/composer-project/archive/${branch.composerProjectRev}.tar.gz";
    hash = branch.composerProjectHash;
  };

  composerPhp = pkgs.php84.withExtensions (
    { all, enabled }:
    enabled
    ++ (with all; [
      bcmath
      exif
      pdo_pgsql
      simplexml
    ])
  );

  allowComposerPlugins = ''
    for plugin in \
      composer/installers \
      cweagans/composer-patches \
      dealerdirect/phpcodesniffer-composer-installer \
      drupal/core-composer-scaffold \
      oomphinc/composer-installers-extender \
      phpstan/extension-installer \
      wikimedia/composer-merge-plugin; do
      composer config --no-plugins "allow-plugins.$plugin" true
    done
  '';

  developmentConfiguration = ''
    cp web/core/phpunit.xml.dist phpunit.xml
    substituteInPlace phpunit.xml \
      --replace-fail 'bootstrap="tests/bootstrap.php"' 'bootstrap="web/core/tests/bootstrap.php"' \
      --replace-fail 'value="sites/simpletest/browser_output"' 'value="web/sites/simpletest/browser_output"'
    mkdir -p web/sites/simpletest/browser_output
    cp web/profiles/farm/docker/dev/files/phpcs.xml .
    cp web/profiles/farm/docker/dev/files/phpstan.neon .
    cp web/profiles/farm/docker/dev/files/rector.php .
    cp web/profiles/farm/docker/dev/files/entity_mapping.neon .
    if [ -d vendor/phpstan/phpstan/turbo-ext ]; then
      find vendor/phpstan/phpstan/turbo-ext -mindepth 1 -delete
    fi
    php ${./normalize-phpstan.php}
  '';

  mkComposerApp =
    {
      pname,
      version,
      src,
      outputHash,
      composerSnapshot,
      prepareSource ? "",
      prepareComposer,
      postInstall ? "",
      development ? true,
      resolveDependencies ? false,
    }:
    pkgs.stdenvNoCC.mkDerivation {
      inherit pname version src postInstall;

      nativeBuildInputs = [
        composerPhp
        composerPhp.packages.composer
        pkgs.cacert
        pkgs.git
        pkgs.patch
        pkgs.unzip
      ];

      impureEnvVars = lib.fetchers.proxyImpureEnvVars;
      outputHashMode = "recursive";
      outputHashAlgo = "sha256";
      outputHash = if outputHash == "" then lib.fakeHash else outputHash;

      dontPatchShebangs = true;
      dontFixup = true;

      passthru = lib.optionalAttrs (!resolveDependencies) {
        resolveDependencies = mkComposerApp {
          inherit pname version src composerSnapshot prepareSource prepareComposer development;
          outputHash = lib.fakeHash;
          resolveDependencies = true;
        };
      };

      buildPhase = ''
        runHook preBuild
        export HOME=$TMPDIR/home
        export COMPOSER_HOME=$TMPDIR/composer-home
        export COMPOSER_CACHE_DIR=$TMPDIR/composer-cache
        export COMPOSER_MEMORY_LIMIT=-1
        export COMPOSER_ALLOW_SUPERUSER=1
        mkdir -p "$HOME" "$COMPOSER_HOME" "$COMPOSER_CACHE_DIR"

        ${prepareSource}
        ${if resolveDependencies then ''
          rm -f composer.lock
          composer config policy.advisories.block false
          composer config platform.ext-geos 1.0.0
          ${allowComposerPlugins}
          ${prepareComposer}
          composer update --no-audit --no-interaction --no-progress --prefer-dist --with-all-dependencies
          php ${./save-composer-lock.php} ${composerPhp.packages.composer}
        '' else ''
          cp ${composerSnapshot}/composer.json composer.json
          cp ${composerSnapshot}/composer.lock composer.lock
          chmod u+w composer.json composer.lock
          composer install --no-interaction --no-progress --prefer-dist ${lib.optionalString (!development) "--no-dev"}
          cmp ${composerSnapshot}/composer.json composer.json
          cmp ${composerSnapshot}/composer.lock composer.lock
          ${lib.optionalString development developmentConfiguration}
        ''}
        runHook postBuild
      '';

      installPhase = ''
        runHook preInstall
        mkdir -p $out
        ${if resolveDependencies then "cp composer.json composer.lock $out/" else ''
          cp -a ./. $out/
          # Source-only packages can include Git hooks with build-store paths.
          find "$out" -name .git -prune -exec rm -rf {} +
        ''}
        runHook postInstall
      '';
    };

  releaseProject = {
    version = release.version;
    src = ./composer/project;
    composerSnapshot = releaseComposerSnapshot;
    prepareComposer = ''
      composer require "farmos/farmos:${release.version}" \
        --no-update --no-interaction \
        --ignore-platform-req=ext-geos
    '';
  };

  farmosRelease = mkComposerApp (releaseProject // {
    pname = "farmos";
    outputHash = release.prodHash;
    development = false;
  });

  farmosReleaseDevelopment = mkComposerApp (releaseProject // {
    pname = "farmos-dev";
    outputHash = release.devHash;
  });

  farmosBranchDevelopment = mkComposerApp {
    pname = "farmos-4x-dev";
    version = "4.x";
    src = composerProjectTar;
    outputHash = branch.devHash;
    composerSnapshot = branchComposerSnapshot;
    prepareSource = ''
      mkdir .farmos-source
      cp -a ${farmosBranchSource}/. .farmos-source/
      chmod -R u+w .farmos-source
    '';
    prepareComposer = ''
      composer config repositories.farmos \
        '{"type":"path","url":".farmos-source","options":{"symlink":false,"versions":{"farmos/farmos":"4.x-dev"}}}'
      composer require "farmos/farmos:${branch.constraint}" \
        --no-update --no-interaction \
        --ignore-platform-req=ext-geos
    '';
  };

in
{
  inherit farmosRelease farmosReleaseDevelopment farmosBranchDevelopment;
}
