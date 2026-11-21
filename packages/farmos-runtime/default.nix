{ pkgs, drupalRuntime }:

let
  inherit (pkgs) lib;

  mkGeosExtension = php: php.buildPecl {
    pname = "geos";
    version = "1.0.0-unstable-2026-10-16";
    src = pkgs.fetchurl {
      url = "https://github.com/libgeos/php-geos/archive/1a1c6a95697359892886a2050570007754ce575e.tar.gz";
      hash = "sha256-dKzaMiVyPO77JPreww73bM9Dctoqyy6+qByw0G8wn/Q=";
    };
    buildInputs = [ pkgs.geos ];
    configureFlags = [ "--with-geos-config=${lib.getExe' pkgs.geos "geos-config"}" ];
    doCheck = false;
    meta = {
      description = "GEOS extension for PHP";
      homepage = "https://git.osgeo.org/gitea/geos/php-geos";
      license = lib.licenses.mit;
    };
  };
in
drupalRuntime.mkRuntime {
  name = "farmos";
  applicationRoot = "/opt/farmos";
  extraExtensionNames = [ "bcmath" "exif" ];
  extraExtensions = php: [ (mkGeosExtension php) ];
  extraConfig = builtins.readFile ./config/php.ini;
}
