{
  pkgs,
  profile,
  composerSnapshot,
}:

let
  inherit (pkgs) lib;
  composerPhp = pkgs.php84.withExtensions (
    { all, enabled }:
    enabled ++ (with all; [ bcmath exif pdo_pgsql simplexml ])
  );
  template = builtins.fromJSON (builtins.readFile ./composer/project/composer.json);
  repository = if profile.repository == null then null
    else builtins.fromJSON profile.repository;
  manifest = pkgs.writeText "farmos-composer.json" (builtins.toJSON (template // {
    require = template.require // { "farmos/farmos" = profile."farmos-version"; };
    repositories = lib.optional (repository != null) repository ++ template.repositories;
  }));
  version = lib.strings.sanitizeDerivationName (profile.resolved.version or "unresolved");

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
      outputHash,
      development ? true,
      resolveDependencies ? false,
    }:
    pkgs.stdenvNoCC.mkDerivation {
      inherit pname version;
      src = ./composer/project;
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
          inherit pname development;
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

        ${if resolveDependencies then ''
          cp ${manifest} composer.json
          chmod u+w composer.json
          rm -f composer.lock
          composer config policy.advisories.block false
          composer config platform.ext-geos 1.0.0
          ${allowComposerPlugins}
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
          find "$out" -name .git -prune -exec rm -rf {} +
        ''}
        runHook postInstall
      '';
    };
in
{
  farmosProduction = mkComposerApp {
    pname = "farmos";
    outputHash = profile.prodHash;
    development = false;
  };
  farmosDevelopment = mkComposerApp {
    pname = "farmos-dev";
    outputHash = profile.devHash;
  };
}
