<?php

declare(strict_types=1);

namespace Drupal\farm_ci_example\Controller;

use Drupal\Core\Controller\ControllerBase;
use Drupal\farm_ci_example\Calculator;

/**
 * Provides a real browser route for the CI integration fixture.
 */
final class ExampleController extends ControllerBase {

  /**
   * Renders the calculated inventory quantity.
   */
  public function result(): array {
    return ['#markup' => $this->t('Inventory total: @value', ['@value' => (new Calculator())->add(4, 7)])];
  }

}
