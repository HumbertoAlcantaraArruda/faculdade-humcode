"""Verifica entrada, saída e interrupção de animações em um navegador real."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
import test_portal as portal
from test_runtime_fixes import test_server


def verify_motion(base, browser_path, login, password, output):
    checks = []
    measurements = {}
    output.mkdir(parents=True, exist_ok=True)

    def check(condition, label):
        assert condition, label
        checks.append(label)

    def sample(page, selector, button):
        return page.evaluate('''async ({selector, button}) => {
          const node = document.querySelector(selector);
          const read = () => {
            const style = getComputedStyle(node);
            return {opacity: Number(style.opacity), margin: parseFloat(style.marginLeft),
              x: node.getBoundingClientRect().x, visibility: style.visibility, display: style.display};
          };
          const before = read();
          document.querySelector(button).click();
          const frames = [];
          await new Promise(resolve => {
            const start = performance.now();
            const tick = now => {
              frames.push({time: now - start, ...read()});
              if (now - start < 360) requestAnimationFrame(tick); else resolve();
            };
            requestAnimationFrame(tick);
          });
          return {before, frames, after: read()};
        }''', {'selector': selector, 'button': button})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=browser_path, headless=True)
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/entrar')
            page.get_by_label('Usuário', exact=True).fill(login)
            page.get_by_label('Senha', exact=True).fill(password)
            page.get_by_role('button', name='Entrar no portal', exact=True).click()
            page.wait_for_url('**/biblioteca')
            page.wait_for_function('() => document.documentElement.classList.contains("motion-ready")')
            closing = sample(page, '.workspace', '[data-sidebar-toggle]')
            check(any(68 < f['margin'] < 240 for f in closing['frames']), 'Conteúdo acompanha o recolhimento sem salto instantâneo')
            check(abs(closing['after']['margin'] - 68) < 1, 'Recolhimento termina na largura da navegação compacta')
            expect(page.locator('.sidebar')).to_be_hidden()
            check(page.locator('.sidebar').evaluate('n => n.inert'), 'Sidebar recolhida não recebe foco')
            opening = sample(page, '.workspace', '[data-rail-menu]')
            check(any(68 < f['margin'] < 240 for f in opening['frames']), 'Conteúdo acompanha a expansão com transição')
            check(abs(opening['after']['margin'] - 240) < 1, 'Expansão restaura a largura original')
            measurements['desktop_close'] = closing
            measurements['desktop_open'] = opening
            intervals = [b['time'] - a['time'] for s in (closing, opening) for a, b in zip(s['frames'], s['frames'][1:])]
            measurements['desktop_frame_intervals_ms'] = {'samples': len(intervals), 'max': round(max(intervals), 2), 'average': round(sum(intervals) / len(intervals), 2)}
            check(len(intervals) >= 12, 'Transição observada em múltiplos frames do navegador')
            page.evaluate('''async () => {
              for (let i = 0; i < 9; i++) {
                document.querySelector('[data-sidebar-toggle]').click();
                await new Promise(resolve => setTimeout(resolve, 25));
              }
            }''')
            expect(page.locator('[data-sidebar-toggle]')).to_have_attribute('aria-expanded', 'false')
            page.wait_for_function('() => parseFloat(getComputedStyle(document.querySelector(".workspace")).marginLeft) === 68')
            expect(page.locator('.sidebar')).to_be_hidden()
            checks.append('Cliques rápidos terminam no estado correto sem enfileirar animações')
            menu_enter = sample(page, '[data-user-menu]', '[data-user-toggle]')
            check(any(0 < f['opacity'] < 1 for f in menu_enter['frames']), 'Menu do usuário entra com fade suave')
            menu_exit = sample(page, '[data-user-menu]', '[data-user-toggle]')
            check(any(f['display'] != 'none' and 0 < f['opacity'] < 1 for f in menu_exit['frames']), 'Menu do usuário anima a saída')
            check(page.locator('[data-user-menu]').evaluate('n => n.inert'), 'Menu fechado não deixa controles acessíveis ao teclado')
            page.evaluate('''async () => {
              const button = document.querySelector('[data-user-toggle]');
              button.click();
              await new Promise(resolve => setTimeout(resolve, 25));
              button.click();
              await new Promise(resolve => setTimeout(resolve, 25));
              button.click();
            }''')
            expect(page.locator('[data-user-toggle]')).to_have_attribute('aria-expanded', 'true')
            check(not page.locator('[data-user-menu]').evaluate('n => n.inert'), 'Menu pode reabrir durante a saída sem ficar bloqueado')
            page.keyboard.press('Escape')
            expect(page.locator('[data-user-menu]')).to_be_hidden()
            measurements['user_menu_enter'] = menu_enter
            measurements['user_menu_exit'] = menu_exit
            entered = sample(page, '#upload-dialog', '[data-open="upload-dialog"]')
            check(any(0 < f['opacity'] < 1 for f in entered['frames']), 'Modal entra com fade e deslocamento suave')
            dialog = page.locator('#upload-dialog')
            backdrop = dialog.evaluate('n => getComputedStyle(n, "::backdrop").backgroundColor')
            check(backdrop == 'rgba(0, 0, 0, 0.72)', 'Fundo do modal é preto neutro')
            check(dialog.evaluate('n => getComputedStyle(n).backgroundColor') == 'rgb(25, 26, 29)', 'Superfície do modal é cinza neutro')
            page.screenshot(path=str(output / 'motion-modal-desktop.png'))
            exited = sample(page, '#upload-dialog', '#upload-dialog [data-close]')
            check(any(f['display'] != 'none' and 0 < f['opacity'] < 1 for f in exited['frames']), 'Modal permanece visível durante a animação de saída')
            expect(dialog).to_be_hidden()
            checks.append('Modal sai completamente e devolve o acesso à página')
            measurements['modal_enter'] = entered
            measurements['modal_exit'] = exited
            page.set_viewport_size({'width': 390, 'height': 844})
            entered = sample(page, '.sidebar', '[data-sidebar-toggle]')
            check(any(-310 < f['x'] < 0 for f in entered['frames']), 'Sidebar mobile entra com deslizamento')
            check(page.locator('.sidebar-shade').evaluate('n => getComputedStyle(n).backgroundColor') == 'rgba(0, 0, 0, 0.72)', 'Sobreposição da sidebar também é preta neutra')
            page.screenshot(path=str(output / 'motion-sidebar-mobile.png'))
            exited = sample(page, '.sidebar', '[data-sidebar-close]')
            check(any(f['visibility'] == 'visible' and -310 < f['x'] < 0 for f in exited['frames']), 'Sidebar mobile continua visível até terminar a saída')
            expect(page.locator('.sidebar')).to_be_hidden()
            check(page.locator('.sidebar').evaluate('n => n.inert'), 'Menu mobile fechado não recebe foco')
            check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Animações não criam rolagem horizontal no celular')
            measurements['mobile_enter'] = entered
            measurements['mobile_exit'] = exited
            page.get_by_role('button', name='Adicionar materiais', exact=True).first.click()
            expect(dialog).to_be_visible()
            dialog.get_by_role('combobox', name='Matéria', exact=True).click()
            expect(dialog.locator('.select2-dropdown')).to_be_visible()
            page.keyboard.press('Escape')
            expect(dialog.locator('.select2-dropdown')).to_have_count(0)
            check(dialog.evaluate('n => n.open'), 'Escape fecha Select2 e mantém o modal aberto')
            page.keyboard.press('Escape')
            expect(dialog).to_be_hidden()
            checks.append('Escape fecha o modal com a transição de saída')
            reduced = browser.new_context(storage_state=context.storage_state(), viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
            reduced_page = reduced.new_page()
            reduced_page.goto(base + '/biblioteca')
            check(reduced_page.locator('.workspace').evaluate('n => getComputedStyle(n).transitionDuration') == '0s', 'Preferência de movimento reduzido desativa as transições')
            reduced_page.locator('[data-open="upload-dialog"]').first.click()
            reduced_page.locator('#upload-dialog [data-close]').first.click()
            expect(reduced_page.locator('#upload-dialog')).to_be_hidden()
            checks.append('Modal abre e fecha sem atraso com movimento reduzido')
            check(not errors, 'Nenhum erro JavaScript durante as transições')
        finally:
            browser.close()
    return checks, measurements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--php', required=True)
    parser.add_argument('--browser', required=True)
    args = parser.parse_args()
    with test_server(Path(args.php)) as fixture:
        checks, measurements = verify_motion(fixture[0], args.browser, 'admin', portal.ADMIN_PASSWORD, portal.ROOT / 'artifacts')
    files = ['portal/src/views.php', 'portal/assets/app.js', 'portal/assets/app.css']
    report = {'status': 'passed', 'verified_at': datetime.now(timezone.utc).isoformat(), 'checks_count': len(checks), 'checks': checks, 'measurements': measurements, 'sha256': {name: hashlib.sha256((portal.ROOT / name).read_bytes()).hexdigest() for name in files}}
    (portal.ROOT / 'artifacts/motion-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks), 'frames': measurements['desktop_frame_intervals_ms']}))


if __name__ == '__main__':
    main()
