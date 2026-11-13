<?php

// Immutable production settings. Secrets and deployment addresses are supplied
// at runtime; the browser installer only writes application data to the database.
require __DIR__ . '/default.settings.php';
$environment = require '/usr/share/farmos/environment.php';

$databases['default']['default'] = require '/usr/share/farmos/database.php';
$settings['hash_salt'] = require '/usr/share/farmos/hash-salt.php';
$settings['config_sync_directory'] = '/opt/farmos/config/sync';
$settings['file_public_path'] = 'sites/default/files';
$settings['file_private_path'] = '/opt/farmos/private_files/files';
$settings['file_temp_path'] = '/tmp';
// Generated executable PHP must not share the public upload directory.
$settings['php_storage']['default']['directory'] = '/tmp/farmos/php';
$settings['trusted_host_patterns'] = array_map(
    static fn (string $host): string => '^' . preg_quote($host, '/') . '$',
    $environment['hosts'],
);
$settings['reverse_proxy'] = $environment['proxies'] !== [];
$settings['reverse_proxy_addresses'] = $environment['proxies'];
$settings['reverse_proxy_trusted_headers'] =
    \Symfony\Component\HttpFoundation\Request::HEADER_X_FORWARDED_FOR
    | \Symfony\Component\HttpFoundation\Request::HEADER_X_FORWARDED_PROTO
    | \Symfony\Component\HttpFoundation\Request::HEADER_X_FORWARDED_PORT;
// Preserve Host at the proxy; never trust a client-provided forwarded hostname.
$settings['update_free_access'] = false;
$config['system.logging']['error_level'] = 'hide';
// Keep OAuth keys outside Drupal's private:// file tree.
$config['simple_oauth.settings']['public_key'] = '/opt/farmos/private_files/keys/public.key';
$config['simple_oauth.settings']['private_key'] = '/opt/farmos/private_files/keys/private.key';

unset($environment);
