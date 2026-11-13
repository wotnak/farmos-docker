<?php

declare(strict_types=1);

namespace Drupal\Tests\farm_ci_example\Unit;

use Drupal\Tests\UnitTestCase;
use Drupal\farm_ci_example\Calculator;
use PHPUnit\Framework\Attributes\CoversClass;
use PHPUnit\Framework\Attributes\Group;
use Symfony\Component\Clock\MockClock;

/**
 * Verifies that tests load the checked-out module's PHP namespace.
 */
#[CoversClass(Calculator::class)]
#[Group('farm_ci_example')]
final class CalculatorTest extends UnitTestCase {

  /**
   * Tests addition with a negative adjustment.
   */
  public function testAddition(): void {
    $this->assertSame(7, (new Calculator())->add(11, -4));
    $clock = new MockClock('2026-01-01');
    $clock->modify('+1 day');
    $this->assertSame('2026-01-02', $clock->now()->format('Y-m-d'));
  }

}
