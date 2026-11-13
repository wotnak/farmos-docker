<?php

return (static function (): string {
    $provided = getenv('FARMOS_HASH_SALT');
    if ($provided !== false && $provided !== '') {
        if (strlen($provided) < 32) {
            throw new RuntimeException('FARMOS_HASH_SALT must contain at least 32 characters when set.');
        }
        return $provided;
    }

    $path = '/opt/farmos/private_files/hash_salt';
    $lock = @fopen($path . '.lock', 'c');
    if ($lock === false) {
        throw new RuntimeException('Cannot open the hash salt lock. Mount private_files writable by the container user.');
    }
    $temporary = false;
    try {
        if (!flock($lock, LOCK_EX)) {
            throw new RuntimeException('Cannot lock the persistent hash salt.');
        }
        if (file_exists($path)) {
            $salt = @file_get_contents($path);
            if ($salt === false || strlen($salt) < 32) {
                throw new RuntimeException('The persistent hash salt is unreadable or invalid. Restore it from backup.');
            }
            return $salt;
        }

        $salt = bin2hex(random_bytes(32));
        // tempnam creates a 0600 file; rename publishes only the complete salt.
        $temporary = @tempnam(dirname($path), '.hash_salt-');
        if ($temporary === false) {
            throw new RuntimeException('Cannot create the persistent hash salt file.');
        }
        $file = @fopen($temporary, 'wb');
        if ($file === false) {
            throw new RuntimeException('Cannot open the persistent hash salt file.');
        }
        try {
            if (fwrite($file, $salt) !== strlen($salt) || !fflush($file) || !fsync($file)) {
                throw new RuntimeException('Cannot write the persistent hash salt file.');
            }
        }
        finally {
            fclose($file);
        }
        if (!@rename($temporary, $path)) {
            throw new RuntimeException('Cannot save the persistent hash salt file.');
        }
        return $salt;
    }
    finally {
        if ($temporary !== false && file_exists($temporary)) {
            unlink($temporary);
        }
        flock($lock, LOCK_UN);
        fclose($lock);
    }
})();
