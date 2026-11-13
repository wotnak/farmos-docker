<?php

declare(strict_types=1);

namespace Drupal\Tests\farm_ci_example\Kernel;

use Drupal\KernelTests\KernelTestBase;
use PHPUnit\Framework\Attributes\CoversNothing;
use PHPUnit\Framework\Attributes\Group;

/**
 * Checks database access and discovery of a declared Composer dependency.
 */
#[CoversNothing]
#[Group('farm_ci_example')]
final class DatabaseTest extends KernelTestBase {

  /**
   * {@inheritdoc}
   */
  protected static $modules = ['system', 'farm_ci_example'];

  /**
   * Persists a quantity through Drupal's actual database connection.
   */
  public function testDatabaseAndDependency(): void {
    $database = $this->container->get('database');
    $database->schema()->createTable('farm_ci_quantity', [
      'fields' => [
        'id' => ['type' => 'int', 'not null' => TRUE],
        'quantity' => ['type' => 'int', 'not null' => TRUE],
      ],
      'primary key' => ['id'],
    ]);
    $database->insert('farm_ci_quantity')->fields(['id' => 1, 'quantity' => 7])->execute();
    $this->assertEquals(7, $database->select('farm_ci_quantity')->fields('farm_ci_quantity', ['quantity'])->execute()->fetchField());
    $path = $this->container->get('extension.list.module')->getPath('farm_ledger');
    $this->assertFileExists(DRUPAL_ROOT . '/' . $path . '/farm_ledger.info.yml');
  }

}
