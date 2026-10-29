"""Confere recuperação após falhas de ativação e de validação, sem acessar FTP."""
import ftplib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import update_portal as update

REMOTE = update.deploy.REMOTE + '/'


class FakeFTP:
    def __init__(self, files, fail_rename=False):
        self.files = dict(files)
        self.fail_rename = fail_rename
        self.expired = False

    def require_live(self):
        if self.expired:
            raise EOFError('FTP ocioso encerrado pela hospedagem')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def delete(self, path):
        self.require_live()
        if path not in self.files:
            raise ftplib.error_perm('550 File not found')
        del self.files[path]

    def rename(self, source, target):
        self.require_live()
        if self.fail_rename and target.endswith('/index.php'):
            raise RuntimeError('Falha simulada na ativação')
        self.files[target] = self.files.pop(source)


class PublicationRecoveryTests(unittest.TestCase):
    def run_publication(self, failure, change_rules=False, expire_ftp=False, read_timeout=False, initial_timeout=False, write_reset=False):
        with tempfile.TemporaryDirectory(prefix='humcode-publication-test-') as temporary:
            root = Path(temporary)
            (root / 'artifacts').mkdir()
            rules = b'RewriteEngine On\nRewriteRule ^index\\.php$ - [L]\n'
            target_rules = rules + (b'RewriteRule ^(.+)$ index.php [L]\n' if change_rules else b'')
            (root / '.htaccess').write_bytes(target_rules)
            previous_rules = root / 'previous-rules'
            previous_rules.write_bytes(rules)
            paths = ['portal/src/migrations.php', 'portal/src/bootstrap.php', 'index.php']
            before = {REMOTE + '.htaccess': rules}
            for path in paths:
                local = root / path
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(b'<?php // new version')
                before[REMOTE + path] = b'<?php // previous version'
            ftp = FakeFTP(before, fail_rename=failure == 'activate')
            connections = []
            def connect(password):
                connection = FakeFTP({}, fail_rename=failure == 'activate')
                connection.files = ftp.files
                connections.append(connection)
                return connection
            actions = []
            timeouts = []
            write_resets = []
            snapshot = {'hc_portal_users': {'count': 3, 'sha256': 'unchanged'}}

            def read_remote(ftp, path):
                if not timeouts and ((read_timeout and 'cleanup' in actions) or initial_timeout):
                    timeouts.append(path)
                    raise TimeoutError('Leitura FTPS interrompida na conferência final')
                ftp.require_live()
                remote = REMOTE + path
                if remote not in ftp.files:
                    raise ftplib.error_perm('550 File not found')
                return ftp.files[remote]

            def http(path, data=None):
                if data is None:
                    return 200, {}, b'Entrar no portal'
                action = data['action']
                actions.append(action)
                if action == 'probe':
                    result = {'schema_ready': False, 'snapshot': snapshot}
                elif action == 'migrate':
                    result = {'schema_ready': failure != 'migrate', 'snapshot': snapshot, 'applied': ['unexpected'] if failure == 'second_migration' and actions.count('migrate') == 2 else []}
                    if failure == 'classification':
                        result['classification'] = [{'kind': 'prova', 'total': 1}]
                else:
                    result = {'snapshot': snapshot}
                return 200, {}, json.dumps(result).encode()

            def verify(*args):
                if expire_ftp:
                    for connection in connections: connection.expired = True
                if failure == 'verify':
                    raise RuntimeError('Falha simulada na verificação')
                return ['Verificação simulada aprovada']

            def upload(connection, path, data):
                if write_reset and '.pending-' in path and not write_resets:
                    write_resets.append(path)
                    raise ConnectionResetError('Sessão FTPS encerrada pela hospedagem')
                connection.require_live()
                connection.files[REMOTE + path] = data

            arguments = ['update_portal.py', '--publish'] + (['--previous-rules', str(previous_rules)] if change_rules else [])
            with patch.object(update, 'ROOT', root), patch.object(update, 'FILES', paths), patch.object(update.getpass, 'getpass', return_value='test-only'), patch.object(update.subprocess, 'check_output', return_value=b'test-commit'), patch.object(update.deploy, 'connect', side_effect=connect), patch.object(update.deploy, 'remote_bytes', side_effect=read_remote), patch.object(update.deploy, 'upload', side_effect=upload), patch.object(update.deploy, 'http', side_effect=http), patch.object(update, 'verify_features', side_effect=verify), patch.object(sys, 'argv', arguments):
                if failure:
                    with self.assertRaises(RuntimeError):
                        update.main()
                else:
                    update.main()
            report = json.loads((root / 'artifacts/runtime-publication.json').read_text(encoding='utf-8'))
            self.assertEqual(ftp.files[REMOTE + '.htaccess'], rules if failure else target_rules)
            self.assertFalse(any('.pending-' in name or 'portal-update-' in name for name in ftp.files))
            self.assertEqual(report['status'], 'failed' if failure else 'verified')
            if read_timeout or initial_timeout:
                self.assertEqual(report['read_retries'], [paths[0]])
                self.assertEqual(actions.count('fixtures'), 0)
                self.assertEqual(actions.count('migrate'), 2)
            if failure:
                self.assertEqual(ftp.files, before)
            else:
                for path in paths:
                    self.assertEqual(ftp.files[REMOTE + path], (root / path).read_bytes())
            if write_reset:
                self.assertEqual(report['write_retries'], write_resets)
            if failure == 'verify':
                self.assertIn('cleanup', actions)
            self.assertTrue((root / report['backup'] / 'index.php').is_file())

    def test_activation_failure_restores_previous_files(self):
        self.run_publication('activate')

    def test_verification_failure_cleans_fixtures_and_restores(self):
        self.run_publication('verify')

    def test_success_removes_temporary_files_and_records_hashes(self):
        self.run_publication(None)

    def test_ftp_idle_timeout_after_http_checks_reconnects(self):
        self.run_publication(None, expire_ftp=True)

    def test_final_hash_read_timeout_retries_only_the_read(self):
        self.run_publication(None, read_timeout=True)

    def test_initial_comparison_timeout_retries_without_mutation(self):
        self.run_publication(None, initial_timeout=True)

    def test_upload_reset_reconnects_and_retries_the_write(self):
        self.run_publication(None, write_reset=True)

    def test_verification_failure_with_expired_ftp_recovers(self):
        self.run_publication('verify', expire_ftp=True)

    def test_new_rules_are_activated_after_files(self):
        self.run_publication(None, change_rules=True)

    def test_activation_failure_preserves_previous_rules(self):
        self.run_publication('activate', change_rules=True)

    def test_verification_failure_restores_previous_rules(self):
        self.run_publication('verify', change_rules=True)

    def test_incomplete_migration_does_not_activate_files(self):
        self.run_publication('migrate')

    def test_changed_classification_does_not_activate_files(self):
        self.run_publication('classification')

    def test_non_idempotent_second_migration_does_not_activate_files(self):
        self.run_publication('second_migration')

    def test_helper_uses_new_migration_before_and_after_activation(self):
        php = Path(os.environ.get('HUMCODE_TEST_PHP', str(Path(tempfile.gettempdir()) / 'humcode-php-8.5.11/php.exe')))
        if not php.is_file():
            self.skipTest('Defina HUMCODE_TEST_PHP para verificar o carregamento real em PHP.')
        with tempfile.TemporaryDirectory(prefix='humcode-migration-loader-') as temporary:
            root = Path(temporary)
            connection, config, _, _ = update.test_portal.create_fixture(root, php)
            try:
                video_schema = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'hc_portal_videos'").fetchone()[0]
                task_schemas = [connection.execute('SELECT sql FROM sqlite_master WHERE name = ?', (table,)).fetchone()[0] for table in ['hc_portal_tasks', 'hc_portal_task_notifications']]
                connection.execute('DROP TABLE hc_portal_task_notifications')
                connection.execute('DROP TABLE hc_portal_tasks')
                event_schemas = [connection.execute('SELECT sql FROM sqlite_master WHERE name = ?', (table,)).fetchone()[0] for table in ['hc_portal_events', 'hc_portal_event_notifications']]
                connection.execute('DROP TABLE hc_portal_event_notifications')
                connection.execute('DROP TABLE hc_portal_events')
                connection.execute('DROP TABLE hc_portal_videos')
                connection.commit()
                source = root / 'portal/src'
                source.mkdir(parents=True)
                bootstrap = (update.ROOT / 'portal/src/bootstrap.php').read_text(encoding='utf-8')
                (source / 'bootstrap.php').write_text(bootstrap.replace("$humcodeMigrationFile ?? __DIR__ . '/migrations.php'", "__DIR__ . '/migrations.php'"), encoding='utf-8')
                (source / 'bootstrap.php.pending-test').write_text(bootstrap, encoding='utf-8')
                (source / 'migrations.php').write_text('<?php function portal_schema_ready(): bool { return true; } function portal_schema_columns(): array { return []; }', encoding='utf-8')
                (source / 'migrations.php.pending-test').write_bytes((update.ROOT / 'portal/src/migrations.php').read_bytes())
                (source / 'documents.php').write_bytes((update.ROOT / 'portal/src/documents.php').read_bytes())
                helper = root / 'helper.php'
                helper.write_bytes(update.helper_source('loader-test', 'portal/src/migrations.php.pending-test', 'portal/src/bootstrap.php.pending-test'))
                runner = root / 'runner.php'
                runner.write_text("<?php $_SERVER['REQUEST_METHOD'] = 'POST'; $_POST = ['token' => 'loader-test', 'action' => 'probe']; require __DIR__ . '/helper.php';", encoding='utf-8')
                environment = dict(os.environ, HUMCODE_CONFIG_FILE=str(config))
                command = [str(php), '-n', '-d', 'extension_dir=' + str(php.parent / 'ext'), '-d', 'extension=pdo_sqlite', str(runner)]

                def probe():
                    result = subprocess.run(command, env=environment, capture_output=True, check=True)
                    return json.loads(result.stdout)

                before = probe()
                self.assertFalse(before['schema_ready'], 'O helper deve detectar vídeos e agenda ausentes, apesar da migração antiga retornar true.')
                connection.execute(video_schema)
                for schema in event_schemas:
                    connection.execute(schema)
                for schema in task_schemas:
                    connection.execute(schema)
                connection.commit()
                for name in ['migrations.php', 'bootstrap.php']:
                    (source / (name + '.pending-test')).replace(source / name)
                after = probe()
                self.assertTrue(after['schema_ready'])
                self.assertEqual(before['snapshot'], after['snapshot'])
                owner = connection.execute('SELECT id FROM hc_portal_users ORDER BY id LIMIT 1').fetchone()[0]
                connection.execute("INSERT INTO hc_portal_events (user_id, title, description, event_date) VALUES (?, 'Evento anterior preservado', 'Descrição anterior', '2030-01-15')", (owner,))
                connection.commit()
                with_category = probe()
                connection.execute('ALTER TABLE hc_portal_events DROP COLUMN category')
                connection.commit()
                legacy_event = probe()
                self.assertFalse(legacy_event['schema_ready'], 'O esquema sem categoria deve pedir migração.')
                self.assertEqual(with_category['snapshot'], legacy_event['snapshot'], 'Snapshot normaliza categoria ausente como nula.')
                connection.execute('ALTER TABLE hc_portal_events ADD COLUMN category VARCHAR(32) NULL DEFAULT NULL')
                connection.commit()
                upgraded_event = probe()
                self.assertTrue(upgraded_event['schema_ready'])
                self.assertEqual(legacy_event['snapshot'], upgraded_event['snapshot'], 'Adicionar categoria preserva evento existente.')
            finally:
                connection.close()

    def test_recurrence_snapshot_preserves_legacy_events_and_tasks(self):
        php = Path(os.environ.get('HUMCODE_TEST_PHP', str(Path(tempfile.gettempdir()) / 'humcode-php-8.5.11/php.exe')))
        if not php.is_file(): self.skipTest('PHP indisponível para teste do snapshot.')
        with tempfile.TemporaryDirectory(prefix='humcode-recurrence-snapshot-') as temporary:
            root = Path(temporary)
            connection, config, _, _ = update.test_portal.create_fixture(root, php)
            try:
                owner = connection.execute('SELECT id FROM hc_portal_users ORDER BY id LIMIT 1').fetchone()[0]
                connection.execute("INSERT INTO hc_portal_events (user_id,title,description,event_date,category) VALUES (?, 'Evento anterior', 'Texto anterior', '2030-01-15', 'curso')", (owner,))
                connection.execute("INSERT INTO hc_portal_tasks (user_id,title,description,task_date,category) VALUES (?, 'Tarefa anterior', 'Texto anterior', '2030-01-14', 'curso')", (owner,))
                connection.commit()
                schemas = {table:connection.execute('SELECT sql FROM sqlite_master WHERE name = ?', (table,)).fetchone()[0] for table in ['hc_portal_events','hc_portal_tasks','hc_portal_recurrences']}
                source = root / 'portal/src'
                source.mkdir(parents=True)
                for name in ['bootstrap.php','migrations.php','documents.php']:
                    (source/name).write_bytes((update.ROOT/'portal/src'/name).read_bytes())
                (root/'helper.php').write_bytes(update.helper_source('snapshot-test','portal/src/migrations.php'))
                runner = root/'runner.php'
                runner.write_text("<?php $_SERVER['REQUEST_METHOD']='POST'; $_POST=['token'=>'snapshot-test','action'=>'probe']; require __DIR__.'/helper.php';",encoding='utf-8')
                env = dict(os.environ,HUMCODE_CONFIG_FILE=str(config))
                command = [str(php),'-n','-d','extension_dir='+str(php.parent/'ext'),'-d','extension=pdo_sqlite',str(runner)]
                def probe():
                    return json.loads(subprocess.run(command,env=env,capture_output=True,check=True).stdout)
                current = probe()
                self.assertTrue(current['schema_ready'])
                legacy_columns = {}
                for table in ['hc_portal_tasks','hc_portal_events']:
                    legacy_columns[table] = [r[1] for r in connection.execute('PRAGMA table_info('+table+')') if not r[1].startswith('recurrence_') and r[1]!='occurrence_date']
                    connection.execute('CREATE TABLE saved_'+table+' AS SELECT '+','.join(legacy_columns[table])+' FROM '+table)
                    connection.execute('DROP TABLE '+table)
                    connection.execute('CREATE TABLE '+table+' AS SELECT * FROM saved_'+table)
                connection.execute('DROP TABLE hc_portal_recurrences')
                connection.commit()
                legacy = probe()
                self.assertFalse(legacy['schema_ready'])
                self.assertEqual(current['snapshot'],legacy['snapshot'],'Novos campos devem ter defaults equivalentes no snapshot anterior.')
                connection.execute(schemas['hc_portal_recurrences'])
                for table in ['hc_portal_events','hc_portal_tasks']:
                    connection.execute('DROP TABLE '+table)
                    connection.execute(schemas[table])
                    connection.execute('INSERT INTO '+table+' ('+','.join(legacy_columns[table])+') SELECT * FROM saved_'+table)
                connection.commit()
                upgraded = probe()
                self.assertTrue(upgraded['schema_ready'])
                self.assertEqual(legacy['snapshot'],upgraded['snapshot'],'Adicionar recorrência preserva todos os campos dos registros anteriores.')
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
