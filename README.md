# Humcode — Portal acadêmico

Portal web para organizar a vida acadêmica da faculdade: materiais de estudo por
disciplina, vídeos, agenda, tarefas e anotações, com controle de acesso por usuário.

Feito em **PHP puro**, sem framework, com rotas próprias, banco **MySQL/MariaDB**
em produção e **SQLite** nos testes automatizados.

## Funcionalidades

- **Disciplinas e materiais (mini-GED):** pastas aninhadas sem limite de
  profundidade, upload de arquivos com categoria (Materiais, Trabalhos ou Provas),
  visualização no navegador e download.
- **Vídeos:** vídeos do YouTube vinculados às disciplinas e pastas.
- **Progresso de estudo:** marcação do que já foi estudado em cada arquivo e vídeo.
- **Agenda:** compromissos com recorrência, categorias, convites para outros
  usuários e notificações.
- **Tarefas:** status, prazos, alerta de horários sobrepostos e notificações.
- **Vínculo de conteúdo:** compromissos e tarefas podem apontar para arquivos,
  vídeos e pastas das disciplinas.
- **Meu dia:** painel com os compromissos e tarefas do dia.
- **Anotações privadas:** com anexos e marcação de importantes.
- **Usuários:** área administrativa, foto de perfil, troca obrigatória de senha
  no primeiro acesso e autenticação em dois fatores por e-mail, com dispositivos
  confiáveis.
- **Interface:** tema claro e escuro, layout responsivo e tabelas com busca e
  filtros.

## Segurança

- Proteção CSRF em todos os formulários e limite de tentativas de login.
- Senhas com `password_hash` e sessão com troca obrigatória de senha inicial.
- Uploads validados por tipo, bloqueio de arquivos executáveis e armazenamento
  fora da área pública.
- Regras de `.htaccess` que expõem só os arquivos estáticos e mandam todas as
  rotas para o `index.php`.
- Credenciais fora do repositório: `portal/config.php` e as senhas de deploy
  ficam apenas no servidor e no cofre do Windows.

## Tecnologias

| Camada | Tecnologias |
| --- | --- |
| Back-end | PHP 7.4+ (PDO), MySQL/MariaDB |
| Front-end | HTML, CSS, JavaScript, jQuery, Select2, SweetAlert2, Tabulator |
| Testes | Python, SQLite, Playwright (Chromium) |
| Deploy | Python com FTPS, backup e verificação pós-publicação |

## Estrutura

```
index.php               Ponto de entrada: carrega os módulos e o controlador
.htaccess               Roteamento e bloqueio de acesso no Apache
portal/
  src/                  Módulos: rotas, views, agenda, tarefas, notas, 2FA etc.
  assets/               CSS, JavaScript e bibliotecas de terceiros
  migrations/           Migrações SQL numeradas
  schema.sql            Esquema completo do banco (tabelas hc_portal_*)
  bin/                  Instalação e migração pela linha de comando
  config.example.php    Modelo de configuração
tools/
  test_*.py             Testes HTTP e de navegador
  deploy.py             Primeira publicação no servidor
  update_portal.py      Atualização com backup, migração e verificação
  dev-router.php        Roteador para o servidor embutido do PHP
```

## Como rodar os testes

Os testes sobem o portal no servidor embutido do PHP, com um banco SQLite
temporário e dados de exemplo. Eles não acessam o servidor nem o banco de produção.

Requisitos: PHP 7.4+ com as extensões `pdo_sqlite` e `fileinfo`, e Python 3.

```bash
python tools/test_portal.py --php "C:/php/php.exe"
python tools/test_tasks.py --php "C:/php/php.exe"
```

Os testes de navegador (`*_browser.py`) usam o Playwright e o caminho do Chrome:

```bash
pip install -r tools/requirements-test.txt
python tools/test_tasks_browser.py --php "C:/php/php.exe" --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

## Instalação em servidor

1. Copie `portal/config.example.php` para `portal/config.php` e preencha os
   dados do banco.
2. Crie o banco e o administrador inicial:
   `HUMCODE_ADMIN_PASSWORD="senha-forte" php portal/bin/install.php`
3. Em instalações existentes, aplique as migrações com `php portal/bin/migrate.php`.

O instalador também importa os materiais originais listados em
`portal/import-manifest.json`. Esses arquivos não fazem parte do repositório.

## Autor

Humberto Alcantara Arruda — [GitHub](https://github.com/HumbertoAlcantaraArruda)
