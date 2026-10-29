<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require dirname(__DIR__) . '/src/bootstrap.php';
echo json_encode(['applied' => migrate_portal(), 'schema_ready' => portal_schema_ready()], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . PHP_EOL;
