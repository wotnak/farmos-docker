<?php

declare(strict_types=1);

// Run only after an explicit dependency update has installed the merge plugin
// and all farmOS manifests. Normal builds consume the resulting files directly.
require $argv[1] . '/share/php/composer/vendor/autoload.php';

$composer = Composer\Factory::create(new Composer\IO\NullIO());
$composer->getEventDispatcher()->dispatchScript(Composer\Script\ScriptEvents::PRE_INSTALL_CMD, true);
$merged = (new Composer\Package\Dumper\ArrayDumper())->dump($composer->getPackage());
// The merge plugin inserts repository objects into the root package. Serialize
// their configuration explicitly; json_encode would silently turn them into {}.
$merged['repositories'] = array_values(array_map(static function ($repository): array {
    if (is_array($repository)) {
        return $repository;
    }
    if ($repository instanceof Composer\Repository\PackageRepository) {
        $dumper = new Composer\Package\Dumper\ArrayDumper();
        return ['type' => 'package', 'package' => array_map([$dumper, 'dump'], $repository->getPackages())];
    }
    if ($repository instanceof Composer\Repository\ConfigurableRepositoryInterface) {
        return $repository->getRepoConfig();
    }
    throw new RuntimeException('Cannot save merged Composer repository: ' . get_debug_type($repository));
}, $merged['repositories']));
$manifest = json_decode(file_get_contents('composer.json'), true, 512, JSON_THROW_ON_ERROR);
foreach (['require', 'require-dev', 'conflict', 'provide', 'replace', 'suggest', 'autoload', 'autoload-dev', 'extra', 'repositories', 'scripts'] as $key) {
    if (array_key_exists($key, $merged)) {
        $manifest[$key] = $merged[$key];
    }
}
// The merged requirements and patches are now explicit. On first installation
// this plugin would otherwise invoke an implicit update, even with a lock file.
unset($manifest['extra']['merge-plugin']);
$manifest['config']['allow-plugins']['wikimedia/composer-merge-plugin'] = false;
$json = json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
file_put_contents('composer.json', $json);
$lock = json_decode(file_get_contents('composer.lock'), true, 512, JSON_THROW_ON_ERROR);
$lock['content-hash'] = Composer\Package\Locker::getContentHash($json);
file_put_contents('composer.lock', json_encode($lock, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");
