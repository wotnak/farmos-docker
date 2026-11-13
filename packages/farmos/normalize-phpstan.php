<?php

declare(strict_types=1);

// PHPStan's installer records the random Nix build directory. Preserve each
// extension's location using a PHP constant expression relative to this file.
$file = 'vendor/phpstan/extension-installer/src/GeneratedConfig.php';
$source = file_get_contents($file);
$count = 0;
$source = preg_replace_callback(
    "~'install_path' => '[^']*',([\\s]*)'relative_install_path' => ('[^']*')~",
    static fn(array $match): string => "'install_path' => __DIR__ . '/' . " . $match[2] . ',' . $match[1] . "'relative_install_path' => " . $match[2],
    $source,
    -1,
    $count,
);
if ($source === null || $count === 0 || str_contains($source, getcwd())) {
    throw new RuntimeException('PHPStan generated configuration could not be normalized.');
}
file_put_contents($file, $source);
require $file;
foreach (PHPStan\ExtensionInstaller\GeneratedConfig::EXTENSIONS as $name => $extension) {
    if (!is_dir($extension['install_path'])) {
        throw new RuntimeException("Normalized PHPStan extension path does not exist: $name");
    }
}
