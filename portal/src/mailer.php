<?php
declare(strict_types=1);

// Configuração em config('mail') ou em portal/mail-config.php (somente no servidor, fora do Git):
// transport smtp (host, port, encryption tls|ssl|none, username, password, from, from_name)
// ou file (directory), usado apenas nos testes locais.
function mail_settings(): ?array {
    static $loaded = false, $settings = null;
    if (!$loaded) {
        $loaded = true;
        $settings = config('mail');
        $file = dirname(__DIR__) . '/mail-config.php';
        if (!is_array($settings) && is_file($file)) { $settings = require $file; }
        if (!is_array($settings)) { $settings = null; }
    }
    return $settings;
}
function mail_available(): bool { return mail_settings() !== null; }

function mail_header_text(string $value): string { return '=?UTF-8?B?' . base64_encode($value) . '?='; }

function send_portal_mail(string $to, string $subject, string $text): bool {
    $settings = mail_settings();
    if ($settings === null || !filter_var($to, FILTER_VALIDATE_EMAIL) || preg_match('/[\r\n]/', $to)) { return false; }
    try {
        if (($settings['transport'] ?? 'smtp') === 'file') { return mail_to_file($settings, $to, $subject, $text); }
        return mail_to_smtp($settings, $to, $subject, $text);
    } catch (Throwable $error) {
        error_log('Humcode mail: ' . $error->getMessage());
        return false;
    }
}

// Confere conexão, TLS e autenticação do SMTP sem enviar mensagem (usado pela verificação da publicação).
function mail_probe(): bool {
    $settings = mail_settings();
    if ($settings === null || ($settings['transport'] ?? 'smtp') !== 'smtp') { return false; }
    try { return mail_to_smtp($settings, null, '', ''); }
    catch (Throwable $error) { error_log('Humcode mail probe: ' . $error->getMessage()); return false; }
}

function mail_to_file(array $settings, string $to, string $subject, string $text): bool {
    $directory = (string) ($settings['directory'] ?? '');
    if ($directory === '' || !is_dir($directory)) { return false; }
    $name = sprintf('%.6f-%s.json', microtime(true), bin2hex(random_bytes(4)));
    return file_put_contents($directory . '/' . $name, json_encode(['to' => $to, 'subject' => $subject, 'text' => $text], JSON_UNESCAPED_UNICODE)) !== false;
}

function mail_to_smtp(array $settings, ?string $to, string $subject, string $text): bool {
    $host = (string) ($settings['host'] ?? ''); $port = (int) ($settings['port'] ?? 587);
    $encryption = (string) ($settings['encryption'] ?? 'tls');
    $from = (string) ($settings['from'] ?? '');
    if ($host === '' || !filter_var($from, FILTER_VALIDATE_EMAIL)) { throw new RuntimeException('SMTP sem servidor ou remetente.'); }
    $context = stream_context_create(['ssl' => ['peer_name' => $host, 'verify_peer' => true, 'verify_peer_name' => true]]);
    $socket = stream_socket_client(($encryption === 'ssl' ? 'ssl://' : 'tcp://') . $host . ':' . $port, $errno, $errstr, 15, STREAM_CLIENT_CONNECT, $context);
    if (!$socket) { throw new RuntimeException('SMTP indisponível: ' . $errstr); }
    stream_set_timeout($socket, 15);
    $read = function () use ($socket): array {
        $lines = '';
        while (($line = fgets($socket, 1024)) !== false) {
            $lines .= $line;
            if (strlen($line) < 4 || $line[3] !== '-') { break; }
        }
        return [(int) substr($lines, 0, 3), $lines];
    };
    $command = function (?string $line, array $expected) use ($socket, $read): string {
        if ($line !== null) { fwrite($socket, $line . "\r\n"); }
        [$code, $reply] = $read();
        if (!in_array($code, $expected, true)) { throw new RuntimeException('SMTP recusou (' . $code . ').'); }
        return $reply;
    };
    try {
        $command(null, [220]);
        $name = parse_url((string) config('site_url'), PHP_URL_HOST) ?: 'localhost';
        $command('EHLO ' . $name, [250]);
        if ($encryption === 'tls') {
            $command('STARTTLS', [220]);
            if (!stream_socket_enable_crypto($socket, true, STREAM_CRYPTO_METHOD_TLS_CLIENT)) { throw new RuntimeException('Falha ao iniciar TLS no SMTP.'); }
            $command('EHLO ' . $name, [250]);
        }
        if ((string) ($settings['username'] ?? '') !== '') {
            $command('AUTH LOGIN', [334]);
            $command(base64_encode((string) $settings['username']), [334]);
            $command(base64_encode((string) ($settings['password'] ?? '')), [235]);
        }
        if ($to === null) { fwrite($socket, "QUIT
"); return true; }
        $command('MAIL FROM:<' . $from . '>', [250]);
        $command('RCPT TO:<' . $to . '>', [250, 251]);
        $command('DATA', [354]);
        $fromName = (string) ($settings['from_name'] ?? 'Humcode');
        $headers = ['Date: ' . date('r'), 'From: ' . mail_header_text($fromName) . ' <' . $from . '>', 'To: <' . $to . '>', 'Subject: ' . mail_header_text($subject),
            'Message-ID: <' . bin2hex(random_bytes(12)) . '@' . (explode('@', $from)[1] ?? $name) . '>', 'MIME-Version: 1.0', 'Content-Type: text/plain; charset=UTF-8', 'Content-Transfer-Encoding: base64'];
        // Corpo em base64: nenhuma linha começa com ponto, então não há "dot-stuffing".
        $command(implode("\r\n", $headers) . "\r\n\r\n" . rtrim(chunk_split(base64_encode($text), 76, "\r\n")) . "\r\n.", [250]);
        // A mensagem já foi aceita; a resposta ao QUIT não altera o resultado.
        fwrite($socket, "QUIT\r\n");
        return true;
    } finally { fclose($socket); }
}
