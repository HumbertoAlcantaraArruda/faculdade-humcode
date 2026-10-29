<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require dirname(__DIR__) . '/src/bootstrap.php';
require dirname(__DIR__) . '/src/documents.php';
require dirname(__DIR__) . '/src/install.php';
$result = install_portal(getenv('HUMCODE_ADMIN_LOGIN') ?: 'admin', getenv('HUMCODE_ADMIN_NAME') ?: 'Administrador', getenv('HUMCODE_ADMIN_PASSWORD') ?: '');
echo json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . PHP_EOL;
