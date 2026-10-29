"""Chrome: validação em 2 etapas na Minha conta e na tela de código, em 1440/390/320 px."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import test_portal as portal
from test_runtime_fixes import test_server


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--php', required=True); parser.add_argument('--browser', required=True); args = parser.parse_args(); checks, errors = [], []

    def check(value, label):
        assert value, label
        checks.append(label)

    with test_server(Path(args.php)) as (base, db, config, _, _, folder, _):
        config.write_text(config.read_text(encoding='utf-8').replace('"two_factor_required_roles" => [], ', ''), encoding='utf-8')
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.browser, headless=True)
            for index, width in enumerate([1440, 390, 320]):
                email = f'admin{width}@example.test'
                db.execute("UPDATE hc_portal_users SET two_factor_enabled=0, email=NULL WHERE login='admin'"); db.execute('DELETE FROM hc_portal_two_factor_codes'); db.execute('DELETE FROM hc_portal_trusted_devices'); db.commit()
                context = browser.new_context(viewport=dict(width=width, height=900), color_scheme='light' if index == 1 else 'dark')
                page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                fits = lambda: page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.goto(base + '/entrar'); page.get_by_label('Usuário', exact=True).fill('admin'); page.get_by_label('Senha', exact=True).fill(portal.ADMIN_PASSWORD); page.get_by_role('button', name='Entrar no portal').click()
                page.wait_for_url('**/minha-conta')
                check(page.locator('[data-two-factor-required]').is_visible(), f'{width}: admin sem 2FA vê aviso obrigatório')
                page.goto(base + '/biblioteca'); page.wait_for_url('**/minha-conta'); check(True, f'{width}: biblioteca redireciona admin sem 2FA')
                section = page.locator('[data-two-factor-settings]')
                section.get_by_label('E-mail para receber os códigos').fill(email); section.get_by_role('button', name='Enviar código de ativação').click()
                page.wait_for_selector('[data-two-factor-pending="enable"]')
                check(fits(), f'{width}: confirmação pendente sem overflow')
                page.screenshot(path=str(portal.ROOT / f'artifacts/two-factor-ativar-{width}.png'), full_page=True)
                page.locator('[data-two-factor-pending]').get_by_label('Código de verificação').fill(portal.mail_code(folder, email))
                page.get_by_role('button', name='Confirmar código').click()
                page.wait_for_selector('[data-two-factor-active="1"]')
                check(page.get_by_text('Validação em 2 etapas ativada', exact=False).is_visible(), f'{width}: ativação confirmada na interface')
                check(page.get_by_text('Obrigatória para administradores.').is_visible() and page.get_by_role('button', name='Desativar validação em 2 etapas').count() == 0, f'{width}: admin não vê opção de desativar')
                page.goto(base + '/biblioteca'); check(page.url.endswith('/biblioteca'), f'{width}: admin com 2FA acessa a biblioteca')
                context.clear_cookies()  # nova sessão no mesmo navegador, sem navegador lembrado
                page.goto(base + '/entrar'); page.get_by_label('Usuário', exact=True).fill('admin'); page.get_by_label('Senha', exact=True).fill(portal.ADMIN_PASSWORD); page.get_by_role('button', name='Entrar no portal').click()
                page.wait_for_url('**/entrar/verificacao')
                code_input = page.get_by_label('Código de verificação')
                check(code_input.evaluate('e => e === document.activeElement') and code_input.get_attribute('autocomplete') == 'one-time-code' and code_input.get_attribute('inputmode') == 'numeric', f'{width}: campo de código focado e preparado para celular')
                check(page.get_by_label('Lembrar deste navegador por 30 dias').is_visible() and fits(), f'{width}: tela de código com lembrar e sem overflow')
                check(page.locator('.login-mobile-brand').is_visible(), f'{width}: tela de código mostra a marca')
                code_input.fill('000000' if portal.mail_code(folder) != '000000' else '111111'); page.get_by_role('button', name='Verificar e entrar').click()
                check(page.get_by_role('alert').inner_text().startswith('Código incorreto'), f'{width}: código errado avisa na tela')
                page.screenshot(path=str(portal.ROOT / f'artifacts/two-factor-codigo-{width}.png'), full_page=True)
                page.get_by_label('Código de verificação').fill(portal.mail_code(folder)); page.get_by_label('Lembrar deste navegador por 30 dias').check(); page.get_by_role('button', name='Verificar e entrar').click()
                page.wait_for_url(lambda url: '/entrar' not in url)
                check(any(c['name'].startswith('humcode_2fa_') and c['httpOnly'] for c in context.cookies()), f'{width}: navegador lembrado com cookie httpOnly')
                context.close()
            browser.close()
        check(not errors, 'Sem erros de JavaScript: ' + '; '.join(errors))
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': len(checks), 'labels': checks, 'browser': 'Chrome', 'widths': [1440, 390, 320]}
    (portal.ROOT / 'artifacts/two-factor-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('2FA Chrome:', len(checks), 'verificações aprovadas')


if __name__ == '__main__':
    main()
