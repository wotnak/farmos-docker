<?php

// phpcs:ignoreFile

/**
 * Load default configuration.
 */
include $app_root . '/' . $site_path . '/default.settings.php';

/**
 * Get database settings from env variables.
 */
$databases['default']['default'] = [
  'driver' => $_ENV['FARMOS_DB_DRIVER'],
  'host' => $_ENV['FARMOS_DB_HOST'],
  'port' => $_ENV['FARMOS_DB_PORT'],
  'database' => $_ENV['FARMOS_DB_NAME'],
  'username' => $_ENV['FARMOS_DB_USER'],
  'password' => $_ENV['FARMOS_DB_PASS'],
];

/**
 * Location of the site configuration files.
 */
$settings['config_sync_directory'] = '../config/sync';

/**
 * Salt for one-time login links, cancel links, form tokens, etc.
 */
$settings['hash_salt'] = 'G5b6S8Qa1jgoCHh6bpL8nvGPQ5SwLTUOyiM3ZLRUf_rQnYod78fEembj4kikz5IbgIlylWY2Qg';

/**
 * Private file path.
 */
$settings['file_private_path'] = '../private_files';

/**
 * Load services definition file.
 */
$settings['container_yamls'][] = $app_root . '/' . $site_path . '/default.services.yml';
$settings['container_yamls'][] = $app_root . '/' . $site_path . '/services.yml';

/**
 * Trusted host configuration.
 */
if (isset($_ENV['FARMOS_DOMAIN'])) {
  $baseDomain = str_replace('.', '\.', $_ENV['FARMOS_DOMAIN']);
  $settings['trusted_host_patterns'] = [
    "^$baseDomain$",
    "^.+\.$baseDomain$",
  ];
}

/**
 * Load local settings overrides.
 */
if (file_exists($app_root . '/' . $site_path . '/settings.local.php')) {
  include $app_root . '/' . $site_path . '/settings.local.php';
}
