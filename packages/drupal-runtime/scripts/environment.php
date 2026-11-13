<?php

// Shared by Drupal settings and server startup. Accept addresses, never Caddy
// directives or regular expressions, in deployment environment variables.
$domain = getenv('FARMOS_DOMAIN') ?: 'localhost';
$validHost = static function (string $host): bool {
    return filter_var($host, FILTER_VALIDATE_DOMAIN, FILTER_FLAG_HOSTNAME) !== false
        || filter_var(trim($host, '[]'), FILTER_VALIDATE_IP) !== false;
};
if (!$validHost($domain) || str_contains($domain, ':')) {
    throw new RuntimeException('FARMOS_DOMAIN must be a hostname without a scheme, path, or port.');
}
$https = strtolower(getenv('FARMOS_AUTO_HTTPS') ?: 'false');
if (!in_array($https, ['true', 'false'], true)) {
    throw new RuntimeException('FARMOS_AUTO_HTTPS must be true or false.');
}
if ($https === 'true' && ($domain === 'localhost' || !str_contains($domain, '.')
    || filter_var($domain, FILTER_VALIDATE_IP) !== false)) {
    throw new RuntimeException('Automatic HTTPS requires a public DNS hostname in FARMOS_DOMAIN.');
}
$hosts = array_values(array_filter(array_map('trim', explode(',', getenv('FARMOS_TRUSTED_HOSTS') ?: $domain))));
if ($domain === 'localhost' && !getenv('FARMOS_TRUSTED_HOSTS')) {
    $hosts[] = '127.0.0.1';
    $hosts[] = '[::1]';
}
if ($hosts === [] || array_filter($hosts, static fn (string $host): bool => !$validHost($host))) {
    throw new RuntimeException('FARMOS_TRUSTED_HOSTS must contain comma-separated exact hostnames.');
}
$proxies = array_values(array_filter(array_map('trim', explode(',', getenv('FARMOS_TRUSTED_PROXIES') ?: ''))));
foreach ($proxies as $proxy) {
    $parts = explode('/', $proxy);
    $ip = $parts[0];
    $maxBits = str_contains($ip, ':') ? 128 : 32;
    if (count($parts) > 2 || filter_var($ip, FILTER_VALIDATE_IP) === false
        || (isset($parts[1]) && (!ctype_digit($parts[1]) || (int) $parts[1] > $maxBits || (int) $parts[1] === 0))) {
        throw new RuntimeException('FARMOS_TRUSTED_PROXIES must contain explicit IP addresses or nonzero CIDR ranges.');
    }
}
return ['domain' => $domain, 'https' => $https === 'true', 'hosts' => $hosts, 'proxies' => $proxies];
