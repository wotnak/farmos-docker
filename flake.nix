{
  description = "farmOS images built from freshly generated dependencies with Nix and nix2container";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    nix2container = {
      url = "github:nlewo/nix2container";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    { self, nixpkgs, nix2container, ... }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      generatedInputs = ./. + "/.build-inputs";
      versionsFile = generatedInputs + "/versions.json";
      metadata = if builtins.pathExists versionsFile then
        builtins.fromJSON (builtins.readFile versionsFile)
      else throw "Generated build inputs are missing. Run scripts/prepare-build first.";
      versionPins = metadata.versions;
      # CI supplies the actual checkout identity alongside refreshed pins.
      # Keep metadata explicit so pure evaluation never depends on CI variables.
      sourceMetadata = builtins.fromJSON (builtins.readFile ./images/source.json);
      imageSource = {
        source = sourceMetadata.source or "https://github.com/farmOS/farmOS";
        # A builder checkout revision does not describe the upstream farmOS URL.
        revision = if sourceMetadata ? source then
          sourceMetadata.revision or (self.rev or (self.dirtyRev or null))
        else null;
      };
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          releaseMajors = pkgs.lib.sort
            (a: b: builtins.fromJSON a < builtins.fromJSON b)
            (builtins.filter
              (name: builtins.match "0|[1-9][0-9]*" name != null)
              (builtins.attrNames versionPins));
          branch = versionPins."4.x" or null;
          # Resolvers and app hash builds bootstrap the generated inputs. Image
          # builds must wait until the complete generation has been validated.
          preparedImages = images: pkgs.lib.mapAttrs (name: value:
            if (name == "default" || (pkgs.lib.hasPrefix "farmos" name
                && !(pkgs.lib.hasSuffix "-app" name)))
                && builtins.pathExists (generatedInputs + "/.preparing") then
              throw "Build input preparation is still running. Wait for scripts/prepare-build to finish before building images."
            else value
          ) images;
          drupalRuntime = import ./packages/drupal-runtime { inherit pkgs; };
          runtime = import ./packages/farmos-runtime { inherit pkgs drupalRuntime; };
          releasePackages = pkgs.lib.genAttrs releaseMajors (
            releaseMajor:
            let
              release = versionPins.${releaseMajor};
              app = import ./packages/farmos {
                inherit pkgs release branch releaseMajor;
                releaseComposerSnapshot = generatedInputs + "/composer/releases/${releaseMajor}";
                branchComposerSnapshot = generatedInputs + "/composer/4.x";
              };
            in
            preparedImages (import ./images {
              inherit pkgs release runtime app imageSource;
              nix2container = nix2container.packages.${system}.nix2container;
            })
          );
          latestPackages = if releaseMajors == [ ] then { } else
            builtins.removeAttrs releasePackages.${pkgs.lib.last releaseMajors}
              [ "farmos-4x-dev" "farmos-4x-dev-app" ];
          branchPackages = if branch == null then { } else
            let
              app = import ./packages/farmos {
                inherit pkgs branch;
                branchComposerSnapshot = generatedInputs + "/composer/4.x";
              };
              images = preparedImages (import ./images {
                inherit pkgs runtime app imageSource;
                release = { version = "4.x-dev"; };
                nix2container = nix2container.packages.${system}.nix2container;
              });
            in {
              inherit (images) farmos-4x-dev farmos-4x-dev-app;
            };
          perMajorPackages = pkgs.lib.foldl' (
            outputs: releaseMajor:
            let
              images = releasePackages.${releaseMajor};
            in
            outputs // {
              "farmos-${releaseMajor}" = images.farmos;
              "farmos-${releaseMajor}-dev" = images.farmos-dev;
              "farmos-${releaseMajor}-runtime" = images.farmos-runtime;
              "farmos-${releaseMajor}-dev-runtime" = images.farmos-dev-runtime;
              "farmos-${releaseMajor}-app" = images.farmos-app;
              "farmos-${releaseMajor}-dev-app" = images.farmos-dev-app;
            }
          ) { } releaseMajors;
        in
        if pkgs.stdenv.hostPlatform.isLinux then
          latestPackages // perMajorPackages // branchPackages
          // {
            "composerPhar" = drupalRuntime.composerPhar;
            "frankenphp-drupal" = drupalRuntime.frankenphpProduction;
            "frankenphp-farmos" = runtime.frankenphpProduction;
            "frankenphp-farmos-dev" = runtime.frankenphpDevelopment;
            "php-drupal" = drupalRuntime.phpCliProduction;
            "skopeo-nix2container" = nix2container.packages.${system}.skopeo-nix2container;
          }
        else
          {
            # Copy Linux images using a native executable on the Docker host.
            "skopeo-nix2container" = nix2container.packages.${system}.skopeo-nix2container;
          }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          php = pkgs.php84.withExtensions (
            { all, enabled }:
            enabled
            ++ (with all; [
              bcmath
              exif
              pdo_pgsql
              simplexml
            ])
          );
        in
        {
          default = pkgs.mkShellNoCC {
            packages = [
              php
              php.packages.composer
              pkgs.git
              pkgs.go-task
              pkgs.python3
              pkgs.jq
              pkgs.openssl
              pkgs.postgresql_17
            ];
          };
        }
      );
    };
}
