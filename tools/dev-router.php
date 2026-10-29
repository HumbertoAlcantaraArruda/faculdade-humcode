<?php
// Somente para o servidor local de testes; não é publicado.
$root = dirname(__DIR__);
$path = rawurldecode(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/');
if (preg_match('~^/portal/assets/[a-zA-Z0-9._/-]+\.(?:css|js|svg)$~', $path)) { return false; }
if (strpos($path, '/portal') === 0 || $path === '/.htaccess') { http_response_code(403); exit; }
require $root . '/index.php';
