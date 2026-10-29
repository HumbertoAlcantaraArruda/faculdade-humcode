<?php
declare(strict_types=1);

// Validação em 2 etapas por código enviado ao e-mail da conta.
// Perfis obrigatórios: config two_factor_required_roles (padrão: administradores).
const TWO_FACTOR_CODE_TTL = 600;
const TWO_FACTOR_MAX_ATTEMPTS = 5;
const TWO_FACTOR_RESEND_WAIT = 60;
const TWO_FACTOR_CODES_PER_HOUR = 6;
const TWO_FACTOR_LOGIN_TTL = 900;
const TRUSTED_DEVICE_TTL = 30 * 86400;
const TWO_FACTOR_WAIT_MESSAGE = 'Aguarde um minuto antes de pedir outro código.';

function two_factor_required(array $user): bool {
    $roles = config('two_factor_required_roles');
    return in_array($user['role'], is_array($roles) ? $roles : ['admin'], true);
}
function two_factor_active(array $user): bool { return (int) ($user['two_factor_enabled'] ?? 0) === 1 && (string) ($user['email'] ?? '') !== ''; }
function masked_email(string $email): string {
    [$name, $domain] = array_pad(explode('@', $email, 2), 2, '');
    $visible = function_exists('mb_substr') ? mb_substr($name, 0, 2) : substr($name, 0, 2);
    return $visible . str_repeat('•', 4) . '@' . $domain;
}

function trusted_cookie_name(int $userId): string { return 'humcode_2fa_' . $userId; }
function trusted_cookie(string $name, string $value, int $expires): void {
    setcookie($name, $value, ['expires' => $expires, 'path' => (config('base_path') ?: '') . '/', 'secure' => is_https(), 'httponly' => true, 'samesite' => 'Lax']);
}
function trusted_device_valid(array $user): bool {
    $token = $_COOKIE[trusted_cookie_name((int) $user['id'])] ?? '';
    if (!is_string($token) || !preg_match('/^[a-f0-9]{64}$/D', $token)) { return false; }
    return (bool) query('SELECT id FROM hc_portal_trusted_devices WHERE user_id = ? AND token_hash = ? AND expires_at > ?', [$user['id'], hash('sha256', $token), time()])->fetchColumn();
}
function remember_device(int $userId): void {
    $token = bin2hex(random_bytes(32)); $expires = time() + TRUSTED_DEVICE_TTL;
    query('DELETE FROM hc_portal_trusted_devices WHERE user_id = ? AND expires_at <= ?', [$userId, time()]);
    query('INSERT INTO hc_portal_trusted_devices (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)', [$userId, hash('sha256', $token), $expires, time()]);
    trusted_cookie(trusted_cookie_name($userId), $token, $expires);
}
// Navegadores lembrados voltam a pedir o código no próximo login.
function forget_devices(int $userId): void { query('DELETE FROM hc_portal_trusted_devices WHERE user_id = ?', [$userId]); }

// Gera e envia um código; devolve a mensagem de erro ou null quando enviado.
function issue_two_factor_code(array $user, string $purpose, string $email): ?string {
    $now = time();
    query('DELETE FROM hc_portal_two_factor_codes WHERE user_id = ? AND created_at < ?', [$user['id'], $now - 86400]);
    $last = query('SELECT created_at FROM hc_portal_two_factor_codes WHERE user_id = ? AND purpose = ? ORDER BY id DESC LIMIT 1', [$user['id'], $purpose])->fetchColumn();
    if ($last !== false && $now - (int) $last < TWO_FACTOR_RESEND_WAIT) { return TWO_FACTOR_WAIT_MESSAGE; }
    $recent = (int) query('SELECT COUNT(*) FROM hc_portal_two_factor_codes WHERE user_id = ? AND created_at > ?', [$user['id'], $now - 3600])->fetchColumn();
    if ($recent >= TWO_FACTOR_CODES_PER_HOUR) { return 'Muitos códigos solicitados. Aguarde alguns minutos e tente novamente.'; }
    if (!mail_available()) { return 'O envio de e-mail não está configurado no portal. Fale com o administrador.'; }
    $code = str_pad((string) random_int(0, 999999), 6, '0', STR_PAD_LEFT);
    query('INSERT INTO hc_portal_two_factor_codes (user_id, purpose, email, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)', [$user['id'], $purpose, $email, password_hash($code, PASSWORD_DEFAULT), $now + TWO_FACTOR_CODE_TTL, $now]);
    $id = (int) db()->lastInsertId();
    $text = "Olá, {$user['name']}.\n\nSeu código de verificação do Humcode é: {$code}\n\nEle expira em 10 minutos. Se você não pediu este código, ignore este e-mail e considere trocar sua senha.\n\nHumcode";
    if (!send_portal_mail($email, 'Código de verificação do Humcode: ' . $code, $text)) {
        query('DELETE FROM hc_portal_two_factor_codes WHERE id = ?', [$id]);
        return 'Não foi possível enviar o código por e-mail. Tente novamente em instantes.';
    }
    // Enviado o novo código, os anteriores do mesmo fluxo deixam de valer (ativação e troca de e-mail são um só fluxo).
    $group = $purpose === 'login' ? ['login'] : ['enable', 'email'];
    query('UPDATE hc_portal_two_factor_codes SET consumed_at = ? WHERE user_id = ? AND id <> ? AND consumed_at IS NULL AND purpose IN (' . implode(',', array_fill(0, count($group), '?')) . ')', array_merge([$now, $user['id'], $id], $group));
    return null;
}
function pending_two_factor_code(int $userId, array $purposes): ?array {
    $row = query('SELECT * FROM hc_portal_two_factor_codes WHERE user_id = ? AND consumed_at IS NULL AND expires_at > ? AND attempts < ? AND purpose IN (' . implode(',', array_fill(0, count($purposes), '?')) . ') ORDER BY id DESC LIMIT 1', array_merge([$userId, time(), TWO_FACTOR_MAX_ATTEMPTS], $purposes))->fetch();
    return $row ?: null;
}
// Confere o código digitado; devolve a linha consumida ou a mensagem de erro.
function verify_two_factor_code(int $userId, array $purposes) {
    $code = preg_replace('/\s+/', '', (string) (is_string($_POST['code'] ?? null) ? $_POST['code'] : ''));
    if (!preg_match('/^\d{6}$/D', $code)) { return 'Digite os 6 números do código.'; }
    $row = pending_two_factor_code($userId, $purposes);
    if (!$row) { return 'O código expirou ou foi substituído. Peça um novo código.'; }
    // O incremento condicional impede tentativas simultâneas além do limite.
    $counted = query('UPDATE hc_portal_two_factor_codes SET attempts = attempts + 1 WHERE id = ? AND consumed_at IS NULL AND attempts < ?', [$row['id'], TWO_FACTOR_MAX_ATTEMPTS])->rowCount();
    if ($counted !== 1) { return 'O código expirou ou foi substituído. Peça um novo código.'; }
    if (!password_verify($code, $row['code_hash'])) {
        return (int) $row['attempts'] + 1 >= TWO_FACTOR_MAX_ATTEMPTS ? 'Código incorreto. Limite de tentativas atingido; peça um novo código.' : 'Código incorreto. Confira o e-mail e tente novamente.';
    }
    if (query('UPDATE hc_portal_two_factor_codes SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL', [time(), $row['id']])->rowCount() !== 1) { return 'O código já foi utilizado. Peça um novo código.'; }
    return $row;
}

function complete_login(array $user): void {
    session_regenerate_id(true);
    unset($_SESSION['two_factor']);
    $_SESSION['user_id'] = (int) $user['id'];
    $_SESSION['session_version'] = (int) $user['session_version'];
    $_SESSION['signed_at'] = time();
    $_SESSION['csrf'] = bin2hex(random_bytes(32));
    if ((int) $user['must_change_password']) { redirect('password'); }
    redirect_to_destination();
}
// Senha conferida: entra direto, pelo navegador lembrado, ou segue para o código.
function continue_login(array $user): void {
    if (!two_factor_active($user) || trusted_device_valid($user)) { complete_login($user); }
    session_regenerate_id(true);
    $_SESSION['two_factor'] = ['user_id' => (int) $user['id'], 'version' => (int) $user['session_version'], 'started' => time()];
    $error = issue_two_factor_code($user, 'login', (string) $user['email']);
    // Novo login logo após outro: o código enviado há menos de um minuto continua valendo.
    if ($error !== null && !($error === TWO_FACTOR_WAIT_MESSAGE && pending_two_factor_code((int) $user['id'], ['login']))) { $_SESSION['two_factor']['error'] = $error; }
    redirect('two-factor');
}
function pending_login_user(): ?array {
    $pending = $_SESSION['two_factor'] ?? null;
    if (!is_array($pending) || time() - (int) $pending['started'] > TWO_FACTOR_LOGIN_TTL) { unset($_SESSION['two_factor']); return null; }
    $user = query('SELECT * FROM hc_portal_users WHERE id = ? AND active = 1', [$pending['user_id']])->fetch();
    if (!$user || (int) $user['session_version'] !== (int) $pending['version'] || !two_factor_active($user)) { unset($_SESSION['two_factor']); return null; }
    return $user;
}
function handle_two_factor_login(): void {
    if (current_user()) { redirect(); }
    $user = pending_login_user();
    if (!$user) { redirect('login'); }
    $error = $_SESSION['two_factor']['error'] ?? null; unset($_SESSION['two_factor']['error']);
    $message = null;
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        check_csrf();
        $action = $_POST['action'] ?? 'verify';
        if ($action === 'cancel') { unset($_SESSION['two_factor']); redirect('login'); }
        if ($action === 'resend') {
            $error = issue_two_factor_code($user, 'login', (string) $user['email']);
            if ($error === null) { $message = 'Enviamos um novo código.'; }
        } elseif ($action === 'verify') {
            $result = verify_two_factor_code((int) $user['id'], ['login']);
            if (is_array($result)) {
                if (($_POST['remember'] ?? '') === '1') { remember_device((int) $user['id']); }
                complete_login($user);
            }
            $error = $result; http_response_code(422);
        } else { fail('Operação inválida.'); }
    } elseif ($_SERVER['REQUEST_METHOD'] !== 'GET') { fail('Método não permitido.', 405); }
    render_two_factor_login($user, $error, $message);
    exit;
}

// E-mail e validação em 2 etapas na Minha conta. A troca de e-mail só vale após o código.
function save_contact_email(array $user): void {
    $email = field('email', 254, false);
    if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) { fail('Informe um e-mail válido.'); }
    if (strcasecmp($email, (string) ($user['email'] ?? '')) === 0) { flash('O e-mail informado já é o atual.'); redirect('password'); }
    if ($email === '') {
        if (two_factor_active($user)) { fail(two_factor_required($user) ? 'A validação em 2 etapas é obrigatória para sua conta; informe outro e-mail em vez de removê-lo.' : 'Desative a validação em 2 etapas antes de remover o e-mail.'); }
        query('UPDATE hc_portal_users SET email = NULL WHERE id = ?', [$user['id']]);
        flash('E-mail removido.'); redirect('password');
    }
    $error = issue_two_factor_code($user, 'email', $email);
    if ($error !== null) { flash($error, 'error'); redirect('password'); }
    flash('Enviamos um código para ' . $email . '. Digite-o abaixo para confirmar o novo e-mail.'); redirect('password');
}
function update_two_factor(array $user): void {
    $action = $_POST['action'] ?? '';
    $pending = pending_two_factor_code((int) $user['id'], ['enable', 'email']);
    if ($action === 'start') {
        if (two_factor_active($user)) { flash('A validação em 2 etapas já está ativa.'); redirect('password'); }
        $email = field('email', 254);
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) { fail('Informe um e-mail válido.'); }
        $error = issue_two_factor_code($user, 'enable', $email);
        flash($error ?? 'Enviamos um código para ' . $email . '. Digite-o abaixo para ativar.', $error === null ? 'success' : 'error'); redirect('password');
    }
    if ($action === 'resend') {
        if (!$pending) { flash('Não há confirmação pendente. Comece novamente.', 'error'); redirect('password'); }
        $error = issue_two_factor_code($user, $pending['purpose'], $pending['email']);
        flash($error ?? 'Enviamos um novo código para ' . $pending['email'] . '.', $error === null ? 'success' : 'error'); redirect('password');
    }
    if ($action === 'cancel') {
        query('UPDATE hc_portal_two_factor_codes SET consumed_at = ? WHERE user_id = ? AND consumed_at IS NULL AND purpose IN (\'enable\', \'email\')', [time(), $user['id']]);
        flash('Confirmação cancelada.'); redirect('password');
    }
    if ($action === 'confirm') {
        $result = verify_two_factor_code((int) $user['id'], ['enable', 'email']);
        if (!is_array($result)) { flash($result, 'error'); redirect('password'); }
        if ($result['purpose'] === 'enable') {
            query('UPDATE hc_portal_users SET email = ?, two_factor_enabled = 1 WHERE id = ?', [$result['email'], $user['id']]);
            forget_devices((int) $user['id']);
            flash('Validação em 2 etapas ativada. Os próximos acessos pedirão um código enviado a ' . $result['email'] . '.');
        } else {
            query('UPDATE hc_portal_users SET email = ? WHERE id = ?', [$result['email'], $user['id']]);
            forget_devices((int) $user['id']);
            flash('E-mail confirmado. Os navegadores lembrados voltarão a pedir o código.');
        }
        redirect('password');
    }
    if ($action === 'disable') {
        if (two_factor_required($user)) { fail('A validação em 2 etapas é obrigatória para administradores.', 403); }
        $password = $_POST['current_password'] ?? '';
        if (!is_string($password) || !password_verify($password, $user['password_hash'])) { fail('A senha atual não confere.'); }
        query('UPDATE hc_portal_users SET two_factor_enabled = 0 WHERE id = ?', [$user['id']]);
        query('UPDATE hc_portal_two_factor_codes SET consumed_at = ? WHERE user_id = ? AND consumed_at IS NULL', [time(), $user['id']]);
        forget_devices((int) $user['id']);
        flash('Validação em 2 etapas desativada.'); redirect('password');
    }
    fail('Operação inválida.');
}

function render_two_factor_login(array $user, ?string $error, ?string $message): void { document_head('Verificação em 2 etapas'); ?>
<body class="login-body"><main class="login-layout login-layout-single"><section class="login-panel"><div class="login-mobile-brand"><?php brand(true); ?></div><div class="login-form-wrap" data-two-factor-login><div class="login-lock"><?= icon('lock') ?></div><span class="eyebrow">Validação em 2 etapas</span><h2>Digite o código</h2><p class="muted">Enviamos um código de 6 números para <strong><?= e(masked_email((string) $user['email'])) ?></strong>. Ele vale por 10 minutos.</p><?php if ($error): ?><div class="notice notice-error" role="alert"><?= e($error) ?></div><?php elseif ($message): ?><div class="notice notice-success" role="status"><?= e($message) ?></div><?php endif; ?><form method="post" action="<?= e(url('two-factor')) ?>" class="login-form"><?= csrf() ?><input type="hidden" name="action" value="verify"><label>Código de verificação<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{6,7}" maxlength="7" placeholder="000000" required autofocus></label><label class="remember-check"><input type="checkbox" name="remember" value="1">Lembrar deste navegador por 30 dias</label><button type="submit" class="button button-primary button-full">Verificar e entrar<?= icon('arrow') ?></button></form><div class="two-factor-actions"><form method="post" action="<?= e(url('two-factor')) ?>"><?= csrf() ?><input type="hidden" name="action" value="resend"><button type="submit" class="text-button">Reenviar código</button></form><form method="post" action="<?= e(url('two-factor')) ?>"><?= csrf() ?><input type="hidden" name="action" value="cancel"><button type="submit" class="text-button">Voltar ao login</button></form></div></div></section></main></body></html>
<?php }

function render_account_security(array $user): void {
    $pending = pending_two_factor_code((int) $user['id'], ['enable', 'email']);
    $active = two_factor_active($user); $required = two_factor_required($user); ?>
<section class="contact-email"><h3>E-mail</h3><form method="post" action="<?= e(url('save-email')) ?>"><?= csrf() ?><label>E-mail<input name="email" type="email" maxlength="254" value="<?= e($user['email'] ?? '') ?>" autocomplete="email"></label><p class="form-hint">Um novo e-mail só passa a valer depois de confirmado com o código que enviaremos a ele.<?= $active ? ' A troca faz os navegadores lembrados pedirem o código de novo.' : '' ?></p><button class="button button-secondary" type="submit">Salvar e-mail</button></form></section>
<section class="two-factor-settings" data-two-factor-settings data-two-factor-active="<?= $active ? '1' : '0' ?>"><h3>Validação em 2 etapas <span class="status-pill <?= $active ? 'status-active' : 'status-inactive' ?>"><?= $active ? 'Ativa' : 'Desativada' ?></span></h3>
<?php if ($pending): ?><div class="two-factor-pending" data-two-factor-pending="<?= e($pending['purpose']) ?>"><p>Digite o código enviado para <strong><?= e($pending['email']) ?></strong> para <?= $pending['purpose'] === 'enable' ? 'ativar a validação em 2 etapas' : 'confirmar o novo e-mail' ?>.</p><form method="post" action="<?= e(url('two-factor-settings')) ?>"><?= csrf() ?><input type="hidden" name="action" value="confirm"><label>Código de verificação<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{6,7}" maxlength="7" placeholder="000000" required></label><button class="button button-primary" type="submit"><?= icon('check') ?>Confirmar código</button></form><div class="two-factor-actions"><form method="post" action="<?= e(url('two-factor-settings')) ?>"><?= csrf() ?><input type="hidden" name="action" value="resend"><button type="submit" class="text-button">Reenviar código</button></form><form method="post" action="<?= e(url('two-factor-settings')) ?>"><?= csrf() ?><input type="hidden" name="action" value="cancel"><button type="submit" class="text-button">Cancelar</button></form></div></div>
<?php elseif ($active): ?><p class="form-hint">Ao entrar, enviamos um código para <?= e($user['email']) ?>. Você pode lembrar um navegador por 30 dias.</p><?php if ($required): ?><p class="form-hint">Obrigatória para administradores.</p><?php else: ?><form method="post" action="<?= e(url('two-factor-settings')) ?>"><?= csrf() ?><input type="hidden" name="action" value="disable"><label>Senha atual<input type="password" name="current_password" autocomplete="current-password" required></label><button class="button button-secondary" type="submit">Desativar validação em 2 etapas</button></form><?php endif; ?>
<?php else: ?><p class="form-hint">Ao entrar, além da senha, será pedido um código enviado ao seu e-mail.<?= $required ? ' Obrigatória para administradores: ative para continuar usando o portal.' : '' ?></p><form method="post" action="<?= e(url('two-factor-settings')) ?>"><?= csrf() ?><input type="hidden" name="action" value="start"><label>E-mail para receber os códigos<input name="email" type="email" maxlength="254" value="<?= e($user['email'] ?? '') ?>" autocomplete="email" required></label><button class="button button-primary" type="submit"><?= icon('lock') ?>Enviar código de ativação</button></form><?php endif; ?></section>
<?php }
