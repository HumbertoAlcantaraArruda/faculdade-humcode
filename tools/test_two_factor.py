"""Validação em 2 etapas: código por e-mail, navegador lembrado, admins obrigatórios e troca de e-mail."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import threading
import time
import test_portal as portal
from test_runtime_fixes import test_server


class FakeSMTP:
    """Servidor SMTP mínimo, sem TLS, para conferir o protocolo do mailer."""
    def __init__(self):
        self.listener = socket.socket(); self.listener.bind(('127.0.0.1', 0)); self.listener.listen(1)
        self.port = self.listener.getsockname()[1]; self.log = []; self.data = b''
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        connection, _ = self.listener.accept()
        stream = connection.makefile('rb')
        send = lambda line: connection.sendall(line.encode() + b'\r\n')
        send('220 fake')
        state = None
        while True:
            line = stream.readline()
            if not line:
                break
            text = line.rstrip(b'\r\n').decode()
            self.log.append(text)
            if state == 'user':
                state = 'pass'; send('334 UGFzc3dvcmQ6')
            elif state == 'pass':
                state = None; send('235 ok')
            elif text.startswith('EHLO'):
                send('250-fake'); send('250 AUTH LOGIN')
            elif text == 'AUTH LOGIN':
                state = 'user'; send('334 VXNlcm5hbWU6')
            elif text == 'DATA':
                send('354 go')
                while True:
                    chunk = stream.readline()
                    if chunk in (b'.\r\n', b''):
                        break
                    self.data += chunk
                send('250 queued')
            elif text == 'QUIT':
                send('221 bye'); break
            else:
                send('250 ok')
        connection.close(); self.listener.close()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--php', required=True); args = parser.parse_args(); checks = []

    def check(value, label):
        assert value, label
        checks.append(label)

    with test_server(Path(args.php)) as (base, db, config, _, _, folder, _):
        original = config.read_text(encoding='utf-8')
        # Configuração de produção: administradores obrigatórios (chave ausente).
        config.write_text(original.replace('"two_factor_required_roles" => [], ', ''), encoding='utf-8')
        user_id = lambda login: db.execute('SELECT id FROM hc_portal_users WHERE login=?', (login,)).fetchone()[0]
        user = lambda login: dict(zip(['email', 'two_factor_enabled'], db.execute('SELECT email, two_factor_enabled FROM hc_portal_users WHERE login=?', (login,)).fetchone()))
        admin_id, member_id = user_id('admin'), user_id('aluno')
        devices = lambda id: db.execute('SELECT COUNT(*) FROM hc_portal_trusted_devices WHERE user_id=?', (id,)).fetchone()[0]
        location = lambda response: response[1].get('Location', '')
        def age_codes(id):
            db.execute('UPDATE hc_portal_two_factor_codes SET created_at = created_at - 120 WHERE user_id=?', (id,)); db.commit()

        # Administrador sem 2FA: entra, mas só usa a Minha conta até ativar.
        admin = portal.Client(base)
        check(admin.login()[0] == 303, 'Senha do administrador sem 2FA conferida')
        blocked = admin.request('/biblioteca')
        check(blocked[0] == 303 and location(blocked).endswith('/minha-conta'), 'Administrador sem 2FA é levado à Minha conta')
        check(location(admin.request('/contas')).endswith('/minha-conta'), 'Gestão de contas bloqueada até ativar 2FA')
        account = admin.request('/minha-conta')[2]
        check(b'data-two-factor-required' in account and b'data-two-factor-active="0"' in account, 'Minha conta avisa que a ativação é obrigatória')
        token = admin.csrf('/minha-conta')
        before = db.execute('SELECT COUNT(*) FROM hc_portal_subjects').fetchone()[0]
        admin.request('/materias/criar', dict(csrf=token, name='Bloqueada', color='teal'))
        check(db.execute('SELECT COUNT(*) FROM hc_portal_subjects').fetchone()[0] == before, 'Administrador sem 2FA não altera dados')
        check(admin.request('/minha-conta/verificacao', dict(csrf='invalido', action='start', email='admin@example.test'))[0] == 403, 'Ativação exige CSRF')
        check(admin.request('/minha-conta/verificacao', dict(csrf=token, action='start', email='invalido'))[0] == 400, 'Ativação recusa e-mail inválido')
        check(admin.request('/minha-conta/verificacao', dict(csrf=token, action='start', email='admin@example.test'))[0] == 303, 'Administrador pede código de ativação')
        check(portal.sent_mail(folder)[-1]['to'] == 'admin@example.test', 'Código de ativação enviado ao e-mail informado')
        check(user('admin')['two_factor_enabled'] == 0 and user('admin')['email'] is None, 'Ativação só vale após o código')
        check(b'data-two-factor-pending="enable"' in admin.request('/minha-conta')[2], 'Minha conta mostra a confirmação pendente')
        code = portal.mail_code(folder, 'admin@example.test')
        admin.request('/minha-conta/verificacao', dict(csrf=token, action='confirm', code='000000' if code != '000000' else '111111'))
        check(user('admin')['two_factor_enabled'] == 0, 'Código errado não ativa')
        check(admin.request('/minha-conta/verificacao', dict(csrf=token, action='confirm', code=code))[0] == 303, 'Código certo confirma a ativação')
        check(user('admin') == {'email': 'admin@example.test', 'two_factor_enabled': 1}, 'Ativação grava e-mail confirmado e 2FA')
        check(admin.request('/minha-conta/verificacao', dict(csrf=token, action='confirm', code=code))[0] == 303 and b'data-two-factor-active="1"' in admin.request('/minha-conta')[2], 'Código usado não vale de novo')
        check(admin.request('/biblioteca')[0] == 200, 'Administrador com 2FA acessa o portal')
        check(admin.request('/minha-conta/verificacao', dict(csrf=token, action='disable', current_password=portal.ADMIN_PASSWORD))[0] == 403 and user('admin')['two_factor_enabled'] == 1, 'Administrador não desativa 2FA')
        check(admin.request('/minha-conta/email', dict(csrf=token, email=''))[0] == 400 and user('admin')['email'] == 'admin@example.test', 'Administrador não remove o e-mail do 2FA')

        # Login com código e opção de lembrar o navegador.
        fresh = portal.Client(base); sent = len(portal.sent_mail(folder))
        response = fresh.login()
        check(response[0] == 303 and location(response).endswith('/entrar/verificacao'), 'Senha certa leva à verificação')
        check(len(portal.sent_mail(folder)) == sent + 1 and portal.sent_mail(folder)[-1]['to'] == 'admin@example.test', 'Código de login enviado ao e-mail da conta')
        check(location(fresh.request('/biblioteca')).endswith('/entrar'), 'Sem código, o portal continua fechado')
        page = fresh.request('/entrar/verificacao')
        check(page[0] == 200 and 'ad••••@example.test'.encode() in page[2] and b'admin@example.test' not in page[2], 'Verificação mostra e-mail mascarado')
        check(b'Lembrar deste navegador por 30 dias' in page[2], 'Opção de lembrar por 30 dias')
        vtoken = fresh.csrf('/entrar/verificacao')
        check(fresh.request('/entrar/verificacao', dict(csrf='invalido', code='123456'))[0] == 403, 'Verificação exige CSRF')
        check(fresh.request('/entrar/verificacao', dict(csrf=vtoken, code='12ab'))[0] == 422, 'Formato inválido recusado')
        code = portal.mail_code(folder)
        resent = fresh.request('/entrar/verificacao', dict(csrf=vtoken, action='resend'))
        check(b'Aguarde um minuto' in resent[2], 'Reenvio respeita intervalo de um minuto')
        done = fresh.request('/entrar/verificacao', dict(csrf=vtoken, code=code[:3] + ' ' + code[3:], remember='1'))
        check(done[0] == 303 and not location(done).endswith('/entrar/verificacao'), 'Código certo conclui o login')
        cookie = next((c for c in fresh.cookies if c.name == 'humcode_2fa_' + str(admin_id)), None)
        check(cookie is not None and cookie.expires and 29 * 86400 < cookie.expires - time.time() <= 30 * 86400, 'Navegador lembrado por 30 dias')
        check(devices(admin_id) == 1 and db.execute('SELECT token_hash FROM hc_portal_trusted_devices WHERE user_id=?', (admin_id,)).fetchone()[0] != cookie.value, 'Token do navegador guardado somente como hash')
        check(fresh.request('/biblioteca')[0] == 200, 'Sessão verificada acessa o portal')

        remembered = portal.Client(base); remembered.trust(cookie.name, cookie.value); sent = len(portal.sent_mail(folder))
        response = remembered.login()
        check(response[0] == 303 and not location(response).endswith('/entrar/verificacao') and len(portal.sent_mail(folder)) == sent, 'Navegador lembrado entra sem código')
        wrongpass = portal.Client(base); wrongpass.trust(cookie.name, cookie.value)
        check(wrongpass.login('admin', 'senha-errada-123')[0] == 401 and location(wrongpass.request('/biblioteca')).endswith('/entrar'), 'Navegador lembrado não dispensa a senha')
        other = portal.Client(base); other.trust(cookie.name, 'f' * 64)
        check(location(other.login()).endswith('/entrar/verificacao'), 'Cookie falso não dispensa o código')
        db.execute('UPDATE hc_portal_trusted_devices SET expires_at=? WHERE user_id=?', (int(time.time()) - 1, admin_id)); db.commit()
        expired = portal.Client(base); expired.trust(cookie.name, cookie.value)
        check(location(expired.login()).endswith('/entrar/verificacao'), 'Navegador lembrado expira após 30 dias')
        db.execute('UPDATE hc_portal_trusted_devices SET expires_at=? WHERE user_id=?', (int(time.time()) + 86400, admin_id)); db.commit()

        # Limites: cinco tentativas por código, expiração e códigos por hora.
        attempt = portal.Client(base); attempt.login(); atoken = attempt.csrf('/entrar/verificacao'); code = portal.mail_code(folder)
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            attempt.request('/entrar/verificacao', dict(csrf=atoken, code=wrong))
        check(attempt.request('/entrar/verificacao', dict(csrf=atoken, code=code))[0] == 422, 'Cinco erros invalidam o código')
        age_codes(admin_id)
        check(b'Enviamos um novo c' in attempt.request('/entrar/verificacao', dict(csrf=atoken, action='resend'))[2], 'Novo código após o intervalo')
        db.execute('UPDATE hc_portal_two_factor_codes SET expires_at=? WHERE user_id=?', (int(time.time()) - 1, admin_id)); db.commit()
        check(attempt.request('/entrar/verificacao', dict(csrf=atoken, code=portal.mail_code(folder)))[0] == 422, 'Código expirado recusado')
        age_codes(admin_id)
        db.execute('UPDATE hc_portal_two_factor_codes SET created_at=? WHERE user_id=?', (int(time.time()) - 600, admin_id)); db.commit()
        for _ in range(6):
            db.execute('INSERT INTO hc_portal_two_factor_codes (user_id,purpose,email,code_hash,expires_at,created_at) VALUES (?,?,?,?,?,?)', (admin_id, 'login', 'x@example.test', 'x', 0, int(time.time()) - 300))
        db.commit()
        check(b'Muitos c' in attempt.request('/entrar/verificacao', dict(csrf=atoken, action='resend'))[2], 'Limite de códigos por hora')
        db.execute('DELETE FROM hc_portal_two_factor_codes WHERE user_id=?', (admin_id,)); db.commit()
        check(location(attempt.request('/entrar/verificacao', dict(csrf=atoken, action='cancel'))).endswith('/entrar') and location(attempt.request('/entrar/verificacao')).endswith('/entrar'), 'Cancelar encerra o login pendente')

        # Troca de e-mail: só vale após o código no novo endereço e revoga navegadores lembrados.
        check(devices(admin_id) == 1, 'Há navegador lembrado antes da troca')
        token = fresh.csrf('/minha-conta')
        check(fresh.request('/minha-conta/email', dict(csrf=token, email='novo@example.test'))[0] == 303, 'Troca de e-mail pede confirmação')
        check(user('admin')['email'] == 'admin@example.test' and devices(admin_id) == 1, 'E-mail anterior vale até confirmar')
        check(b'data-two-factor-pending="email"' in fresh.request('/minha-conta')[2], 'Confirmação do novo e-mail pendente')
        check(fresh.request('/minha-conta/verificacao', dict(csrf=token, action='confirm', code=portal.mail_code(folder, 'novo@example.test')))[0] == 303, 'Código do novo e-mail confirmado')
        check(user('admin') == {'email': 'novo@example.test', 'two_factor_enabled': 1}, 'Novo e-mail passa a receber o 2FA')
        check(devices(admin_id) == 0, 'Troca de e-mail revoga navegadores lembrados')
        again = portal.Client(base); again.trust(cookie.name, cookie.value)
        check(location(again.login()).endswith('/entrar/verificacao') and portal.sent_mail(folder)[-1]['to'] == 'novo@example.test', 'Navegador antes lembrado volta a pedir o código no novo e-mail')
        age_codes(admin_id)
        fresh.request('/minha-conta/email', dict(csrf=token, email='desistiu@example.test'))
        fresh.request('/minha-conta/verificacao', dict(csrf=token, action='cancel'))
        check(user('admin')['email'] == 'novo@example.test' and b'data-two-factor-pending' not in fresh.request('/minha-conta')[2], 'Troca cancelada mantém o e-mail')

        # Estudante: 2FA opcional.
        member = portal.Client(base)
        response = member.login('aluno', portal.MEMBER_PASSWORD)
        check(response[0] == 303 and not location(response).endswith('/entrar/verificacao') and member.request('/biblioteca')[0] == 200, 'Estudante sem 2FA entra só com a senha')
        mtoken = member.csrf('/minha-conta')
        check(b'data-two-factor-active="0"' in member.request('/minha-conta')[2] and b'data-two-factor-required' not in member.request('/minha-conta')[2], 'Estudante vê 2FA opcional')
        member.request('/minha-conta/verificacao', dict(csrf=mtoken, action='start', email='aluno@example.test'))
        member.request('/minha-conta/verificacao', dict(csrf=mtoken, action='confirm', code=portal.mail_code(folder, 'aluno@example.test')))
        check(user('aluno') == {'email': 'aluno@example.test', 'two_factor_enabled': 1}, 'Estudante ativa 2FA')
        second = portal.Client(base)
        check(location(second.login('aluno', portal.MEMBER_PASSWORD)).endswith('/entrar/verificacao'), 'Estudante com 2FA recebe código no login')
        stoken = second.csrf('/entrar/verificacao')
        check(second.request('/entrar/verificacao', dict(csrf=stoken, code=portal.mail_code(folder, 'aluno@example.test'), remember='1'))[0] == 303 and devices(member_id) == 1, 'Estudante lembra o navegador')
        check(member.request('/minha-conta/email', dict(csrf=mtoken, email=''))[0] == 400, 'Estudante com 2FA não remove o e-mail sem desativar')
        check(member.request('/minha-conta/verificacao', dict(csrf=mtoken, action='disable', current_password='errada-errada-1'))[0] == 400 and user('aluno')['two_factor_enabled'] == 1, 'Desativar exige a senha atual')
        check(member.request('/minha-conta/verificacao', dict(csrf=mtoken, action='disable', current_password=portal.MEMBER_PASSWORD))[0] == 303, 'Estudante desativa 2FA')
        check(user('aluno') == {'email': 'aluno@example.test', 'two_factor_enabled': 0} and devices(member_id) == 0, 'Desativação mantém o e-mail e esquece navegadores')
        check(not location(portal.Client(base).login('aluno', portal.MEMBER_PASSWORD)).endswith('/entrar/verificacao'), 'Sem 2FA, estudante volta a entrar só com a senha')
        age_codes(member_id)
        member.request('/minha-conta/email', dict(csrf=mtoken, email='outro@example.test'))
        check(user('aluno')['email'] == 'aluno@example.test', 'Estudante sem 2FA também confirma novo e-mail')
        check(member.request('/minha-conta/email', dict(csrf=mtoken, email=''))[0] == 303 and user('aluno')['email'] is None, 'Estudante sem 2FA remove o e-mail')

        # Senha temporária: o código vem antes da troca obrigatória de senha.
        db.execute('UPDATE hc_portal_users SET must_change_password=1 WHERE id=?', (admin_id,)); db.commit()
        temp = portal.Client(base); temp.login(); ttoken = temp.csrf('/entrar/verificacao')
        response = temp.request('/entrar/verificacao', dict(csrf=ttoken, code=portal.mail_code(folder, 'novo@example.test')))
        check(location(response).endswith('/minha-conta'), 'Após o código, senha temporária exige troca')
        db.execute('UPDATE hc_portal_users SET must_change_password=0 WHERE id=?', (admin_id,)); db.commit()

        # Conta desativada durante a verificação não conclui o login.
        age_codes(admin_id)
        pending = portal.Client(base); pending.login(); ptoken = pending.csrf('/entrar/verificacao'); pcode = portal.mail_code(folder)
        db.execute('UPDATE hc_portal_users SET session_version=session_version+1 WHERE id=?', (admin_id,)); db.commit()
        check(location(pending.request('/entrar/verificacao', dict(csrf=ptoken, code=pcode))).endswith('/entrar') and location(pending.request('/biblioteca')).endswith('/entrar'), 'Senha redefinida ou conta desativada invalida o login pendente')

        # Sem e-mail configurado: mensagem clara, sem liberar o acesso.
        config.write_text(original.replace('"two_factor_required_roles" => [], ', '').replace('"mail" => ["transport" => "file"', '"no_mail" => ["transport" => "file"'), encoding='utf-8')
        age_codes(admin_id)
        nomail = portal.Client(base); response = nomail.login()
        body = nomail.request('/entrar/verificacao')[2]
        check(location(response).endswith('/entrar/verificacao') and 'não está configurado'.encode() in body, 'Sem SMTP o login avisa e não entra')
        check(location(nomail.request('/biblioteca')).endswith('/entrar'), 'Sem SMTP o portal continua fechado')

        # Protocolo SMTP: STARTTLS fica a cargo do servidor real; aqui, AUTH LOGIN, envelope e corpo.
        smtp = FakeSMTP()
        config.write_text(original.replace('"two_factor_required_roles" => [], ', '').replace('"mail" => ["transport" => "file", "directory" => ', '"mail" => ["transport" => "smtp", "host" => "127.0.0.1", "port" => ' + str(smtp.port) + ', "encryption" => "none", "username" => "portal@humcode.test", "password" => "segredo", "from" => "portal@humcode.test", "from_name" => "Humcode", "unused" => '), encoding='utf-8')
        age_codes(admin_id)
        viasmtp = portal.Client(base); response = viasmtp.login()
        for _ in range(50):
            if 'QUIT' in smtp.log:
                break
            time.sleep(.1)
        message = smtp.data.decode()
        header, _, body64 = message.partition('\r\n\r\n')
        decoded = base64.b64decode(''.join(body64.split())).decode('utf-8')
        check(location(response).endswith('/entrar/verificacao') and b'n\xc3\xa3o est' not in viasmtp.request('/entrar/verificacao')[2], 'Login envia código por SMTP')
        check(base64.b64decode(smtp.log[smtp.log.index('AUTH LOGIN') + 1]) == b'portal@humcode.test' and base64.b64decode(smtp.log[smtp.log.index('AUTH LOGIN') + 2]) == b'segredo', 'SMTP autentica com AUTH LOGIN')
        check('MAIL FROM:<portal@humcode.test>' in smtp.log and 'RCPT TO:<novo@example.test>' in smtp.log, 'Envelope SMTP com remetente e destinatário')
        check('Content-Type: text/plain; charset=UTF-8' in header and 'Subject: =?UTF-8?B?' in header, 'Mensagem UTF-8 com assunto codificado')
        check('Seu código de verificação do Humcode é:' in decoded, 'Corpo da mensagem traz o código')
        config.write_text(original.replace('"two_factor_required_roles" => [], ', ''), encoding='utf-8')

        # Exclusão de conta remove códigos e navegadores lembrados.
        check(db.execute('SELECT COUNT(*) FROM hc_portal_two_factor_codes WHERE user_id=?', (member_id,)).fetchone()[0] > 0, 'Estudante tem códigos registrados')
        db.execute('INSERT INTO hc_portal_trusted_devices (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)', (member_id, 'a' * 64, int(time.time()) + 100, int(time.time()))); db.commit()
        reauth = portal.Client(base); reauth.trust(cookie.name, cookie.value)
        db.execute('DELETE FROM hc_portal_two_factor_codes WHERE user_id=?', (admin_id,)); db.commit()  # limite por hora já coberto acima
        reauth.login(); rtoken = reauth.csrf('/entrar/verificacao'); reauth.request('/entrar/verificacao', dict(csrf=rtoken, code=portal.mail_code(folder, 'novo@example.test')))
        rtoken = reauth.csrf('/contas')
        check(reauth.request('/contas/atualizar', dict(csrf=rtoken, id=member_id, action='delete', confirm='1'))[0] == 303, 'Administrador exclui conta com 2FA')
        check(db.execute('SELECT (SELECT COUNT(*) FROM hc_portal_two_factor_codes WHERE user_id=?) + (SELECT COUNT(*) FROM hc_portal_trusted_devices WHERE user_id=?)', (member_id, member_id)).fetchone()[0] == 0, 'Exclusão remove códigos e navegadores da conta')

    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'checks': len(checks), 'labels': checks, 'database': 'SQLite temporário; e-mails em arquivo e SMTP falso local'}
    (portal.ROOT / 'artifacts/two-factor-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('2FA:', len(checks), 'verificações aprovadas')


if __name__ == '__main__':
    main()
