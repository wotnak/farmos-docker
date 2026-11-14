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
    { nixpkgs, nix2container, ... }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      generatedInputs = ./. + "/.build-inputs";
      buildFile = generatedInputs + "/build.json";
      metadata = if builtins.pathExists buildFile then
        builtins.fromJSON (builtins.readFile buildFile)
      else throw "Generated build inputs are missing. Run scripts/prepare-build first.";
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          drupalRuntime = import ./packages/drupal-runtime { inherit pkgs; };
          runtime = import ./packages/farmos-runtime { inherit pkgs drupalRuntime; };
          app = import ./packages/farmos {
            inherit pkgs;
            profile = metadata;
            composerSnapshot = generatedInputs + "/composer";
          };
          images = import ./images {
            inherit pkgs runtime app;
            profile = metadata;
            nix2container = nix2container.packages.${system}.nix2container;
          };
          preparedImages = pkgs.lib.mapAttrs (name: value:
            if builtins.elem name [ "default" "farmos" "farmos-dev" "farmos-runtime" "farmos-dev-runtime" ]
                && builtins.pathExists (generatedInputs + "/.preparing") then
              throw "Build input preparation is still running. Wait for scripts/prepare-build to finish before building images."
            else value
          ) images;
        in
        if pkgs.stdenv.hostPlatform.isLinux then
          preparedImages // {
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
