<?php

declare(strict_types=1);

namespace Drupal\Tests\farm_ci_example\Functional;

use Drupal\Tests\BrowserTestBase;
use PHPUnit\Framework\Attributes\CoversNothing;
use PHPUnit\Framework\Attributes\Group;

/**
 * Tests the module and its declared farmOS dependency through HTTP.
 */
#[CoversNothing]
#[Group('farm_ci_example')]
final class ModulePageTest extends BrowserTestBase {

  /**
   * {@inheritdoc}
   */
  protected static $modules = ['farm_ci_example'];

  /**
   * {@inheritdoc}
   */
  protected $profile = 'farm';

  /**
   * {@inheritdoc}
   */
  protected $defaultTheme = 'stark';

  /**
   * Tests the module's route and automatic dependency installation.
   */
  public function testModulePage(): void {
    $this->assertTrue($this->container->get('module_handler')->moduleExists('farm_ledger'));
    $this->drupalLogin($this->drupalCreateUser(['access content']));
    $this->drupalGet('/farm-ci-example');
    $this->assertSession()->statusCodeEquals(200);
    $this->assertSession()->pageTextContains('Inventory total: 11');
  }

}
