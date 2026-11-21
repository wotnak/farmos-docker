<?php

if (PHP_MAJOR_VERSION !== 8 || PHP_MINOR_VERSION !== 5) {
    fwrite(STDERR, 'Expected PHP 8.5, got ' . PHP_VERSION . PHP_EOL);
    exit(1);
}

$required = [
    'bcmath',
    'exif',
    'filter',
    'gd',
    'geos',
    'iconv',
    'pdo_pgsql',
    'pdo_sqlite',
    'session',
    'simplexml',
    'tokenizer',
    'xml',
    'Zend OPcache',
];
$missing = array_filter($required, static fn (string $extension): bool => !extension_loaded($extension));

if ($missing) {
    fwrite(STDERR, 'Missing PHP extensions: ' . implode(', ', $missing) . PHP_EOL);
    exit(1);
}

// Exercise the codecs Drupal uses for image styles, including AVIF. Merely
// loading GD does not prove its trimmed native dependencies still work.
$image = imagecreatetruecolor(4, 3);
imagefill($image, 0, 0, imagecolorallocate($image, 32, 96, 160));
foreach (['png', 'jpeg', 'gif', 'webp', 'avif'] as $format) {
    ob_start();
    $encoded = ('image' . $format)($image);
    $bytes = ob_get_clean();
    $decoded = $encoded && $bytes !== '' ? imagecreatefromstring($bytes) : false;
    if (!$decoded || imagesx($decoded) !== 4 || imagesy($decoded) !== 3) {
        fwrite(STDERR, 'GD image round-trip failed: ' . $format . PHP_EOL);
        exit(1);
    }
}

echo PHP_VERSION . PHP_EOL;
