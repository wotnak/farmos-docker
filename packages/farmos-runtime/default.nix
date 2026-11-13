{ pkgs, drupalRuntime }:

let
  inherit (pkgs) lib;

  mkGeosExtension = php: php.buildPecl {
    pname = "geos";
    version = "1.0.0-unstable-2024-01-29";
    src = pkgs.fetchurl {
      url = "https://github.com/libgeos/php-geos/archive/dfe1ab17b0f155cc315bc13c75689371676e02e1.tar.gz";
      hash = "sha256-4/2/YBjCrd+ZrO1w6W8mq4FRzV96Ix/2qAuBmAwaJho=";
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
