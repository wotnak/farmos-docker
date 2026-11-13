<?php

return (static function (): array {
    // Connection settings shared by Drupal and container startup.
    $read = static function (string $name, string $default = ''): string {
        $value = getenv($name);
        return $value === false || $value === '' ? $default : $value;
    };
    $driver = $read('FARMOS_DB_DRIVER', 'pgsql');
    if (!in_array($driver, ['pgsql', 'sqlite'], true)) {
        throw new RuntimeException('Unsupported FARMOS_DB_DRIVER. Supported drivers: pgsql, sqlite.');
    }
    if (!extension_loaded('pdo_' . $driver)) {
        throw new RuntimeException('Missing PHP database extension: pdo_' . $driver);
    }

    $connection = [
        'driver' => $driver,
        'namespace' => 'Drupal\\' . $driver . '\\Driver\\Database\\' . $driver,
        'autoload' => 'core/modules/' . $driver . '/src/Driver/Database/' . $driver . '/',
        'prefix' => '',
    ];
    if ($driver === 'sqlite') {
        $connection['database'] = $read('FARMOS_DB_NAME', '/opt/farmos/private_files/database/farmos.sqlite');
        if (!str_starts_with($connection['database'], '/') || str_contains($connection['database'], "\0")) {
            throw new RuntimeException('For SQLite, FARMOS_DB_NAME must be an absolute database file path.');
        }
        return $connection;
    }

    $password = $read('FARMOS_DB_PASS');
    if ($password === '') {
        throw new RuntimeException('Set FARMOS_DB_PASS for PostgreSQL.');
    }
    $port = $read('FARMOS_DB_PORT', '5432');
    if (!ctype_digit($port) || (int) $port < 1 || (int) $port > 65535) {
        throw new RuntimeException('FARMOS_DB_PORT must be between 1 and 65535.');
    }
    $connection += [
        'database' => $read('FARMOS_DB_NAME', 'farmos'),
        'username' => $read('FARMOS_DB_USER', 'farm'),
        'password' => $password,
        'host' => $read('FARMOS_DB_HOST', 'db'),
        'port' => $port,
    ];
    return $connection;
})();
