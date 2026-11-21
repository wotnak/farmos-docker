<?php

// Drupal's test client turns native PHP deprecations from HTTP responses into
// test errors. Keep those notices enabled for the PHPUnit CLI process.
if (PHP_SAPI !== 'cli') {
    error_reporting(error_reporting() & ~E_DEPRECATED);
}
