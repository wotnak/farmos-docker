<?php

declare(strict_types=1);

namespace Drupal\farm_ci_example;

/**
 * Adds two inventory quantities for the CI integration fixture.
 */
final class Calculator {

  /**
   * Returns the combined quantity.
   */
  public function add(int $first, int $second): int {
    return $first + $second;
  }

}
