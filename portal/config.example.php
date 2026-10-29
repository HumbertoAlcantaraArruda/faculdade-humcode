<?php
// Copie como config.php na instalação. Nunca publique nem versione senhas.
return [
    'db' => [
        'dsn' => 'mysql:host=localhost;port=3306;dbname=NOME_DO_BANCO;charset=utf8mb4',
        'user' => 'USUARIO_DO_BANCO',
        'password' => '',
    ],
    'site_url' => 'https://www.exemplo.com.br',
    'base_path' => '',
    'force_https' => true,
    'document_root' => dirname(__DIR__),
    'storage_path' => __DIR__ . '/storage',
    'max_upload_bytes' => 25 * 1024 * 1024,
    'max_upload_files' => 10,
];
