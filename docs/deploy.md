# Publicar o OddVision na nuvem

Este guia leva o app para a internet usando serviços gratuitos. São três peças:

| Peça | Serviço sugerido | Para quê |
|---|---|---|
| Código | GitHub (já publicado em `eduardools12/OddVision`) | O Streamlit Community Cloud lê o código de lá |
| Banco | **Neon** (PostgreSQL gratuito) | Guarda o `core` e as views de `analytics` |
| App | **Streamlit Community Cloud** | Roda `app/Home.py` e mostra o site |

Os nomes dos botões desses serviços podem mudar um pouco com o tempo; o que importa está em **negrito**.
O banco local tem 211 MB. Confira os limites atuais do plano gratuito do Neon antes de começar.

## O que o projeto já faz por você

- O app aceita a conexão por uma **URL** (`ODDVISION_DATABASE_URL`), nos *secrets* do Streamlit ou numa variável de ambiente. Sem ela, usa o `config/database.toml` local.
- Toda consulta do app roda em transação **somente leitura**: o banco recusa qualquer escrita vinda do site.
- `sql/deploy/reader_role.sql` cria uma role que só lê o schema `analytics` (nem as tabelas-fonte ela enxerga).
- As páginas colocam `src/` no caminho de importação, então a nuvem não precisa instalar o pacote.

## 1. Criar o banco no Neon (navegador)

1. Entre em neon.tech e crie uma conta (pode ser com o GitHub).
2. **Create project**. Dê o nome `oddvision` e escolha o **PostgreSQL 18** (a mesma versão do seu computador), numa região próxima.
3. Na tela do projeto, abra **Connection details** (ou **Connect**) e copie a *connection string* da conexão **direta** (sem `-pooler` no endereço). Ela tem este formato:
   `postgresql://USUARIO:SENHA@ep-xxxx.regiao.aws.neon.tech/neondb?sslmode=require`
4. Guarde essa string num lugar privado (gerenciador de senhas). **Ela dá acesso total ao banco: nunca a coloque no código, no Git ou em print.**

## 2. Enviar os dados (PowerShell, na pasta do projeto)

Isto copia o schema `core` do seu banco local para o Neon. É bem mais rápido do que recarregar tudo pelo pipeline pela internet.

```powershell
$pg = "C:\Program Files\PostgreSQL\18\bin"
& "$pg\pg_dump.exe" -h localhost -p 1212 -U oddvision_app -d oddvision --schema=core --no-owner --no-privileges -Fc -f "$env:TEMP\oddvision_core.dump"
```

Ele pede a senha do `oddvision_app` (a do seu `config/database.toml`). Depois, troque a string abaixo pela do Neon (passo 1):

```powershell
& "$pg\pg_restore.exe" --no-owner --no-privileges -d "postgresql://USUARIO:SENHA@ep-xxxx.regiao.aws.neon.tech/neondb?sslmode=require" "$env:TEMP\oddvision_core.dump"
```

Se o caminho do PostgreSQL for outro, ajuste a primeira linha. Se aparecer erro de versão, me envie o texto.

## 3. Criar as views no Neon (PowerShell)

O `init-db` lê `config/database.toml`. Para apontá-lo ao Neon por alguns minutos, guarde uma cópia e troque o conteúdo:

```powershell
Copy-Item config\database.toml config\database.local.toml
notepad config\database.toml
```

No Bloco de Notas, deixe o arquivo assim (valores do passo 1; a porta no Neon é 5432):

```toml
[connection]
host = "ep-xxxx.regiao.aws.neon.tech"
port = 5432
user = "USUARIO"
password = "SENHA"

[databases]
main = "neondb"
test = "oddvision_test"
```

Salve, feche e rode:

```powershell
.\.venv\Scripts\python.exe -m oddvision.pipeline init-db
.\.venv\Scripts\python.exe -m oddvision.pipeline check
```

O esperado é `11 checks | 0 erros | 1 aviso`. **Volte o arquivo ao normal** (o `config/database.local.toml` fica como cópia; ambos estão ignorados pelo Git):

```powershell
Move-Item -Force config\database.local.toml config\database.toml
```

## 4. Criar a role só de leitura (navegador, Neon)

1. Abra o arquivo `sql/deploy/reader_role.sql` e troque `TROQUE-ESTA-SENHA` por uma senha nova, **só com letras e números** (24 ou mais caracteres), para não precisar codificar símbolos na URL.
2. No Neon, abra o **SQL Editor**, cole o conteúdo do arquivo e execute. Rode como o dono do banco (a conexão padrão do editor).
3. Monte a URL do app, com a role nova e o mesmo endereço do Neon:
   `postgresql://oddvision_reader:SENHA-NOVA@ep-xxxx.regiao.aws.neon.tech/neondb?sslmode=require`
   (aqui pode usar o endereço com `-pooler`; o app já está preparado para isso).

Não faça `commit` do arquivo com a senha preenchida.

## 5. Publicar o app (navegador)

1. Entre em share.streamlit.io com a conta do GitHub e autorize o acesso ao repositório `OddVision`.
2. **Create app** → **Deploy a public app from GitHub**.
3. Repositório `eduardools12/OddVision`, branch `main`, arquivo principal **`app/Home.py`**.
4. Em **Advanced settings**:
   - **Python version: 3.13** (o projeto exige 3.13).
   - **Secrets**: cole a linha abaixo, com a URL do passo 4.
     ```toml
     ODDVISION_DATABASE_URL = "postgresql://oddvision_reader:SENHA-NOVA@ep-xxxx.regiao.aws.neon.tech/neondb?sslmode=require"
     ```
5. **Deploy**. A primeira publicação instala as dependências e demora alguns minutos.

## 6. Conferir

- A página inicial deve mostrar **64** partidas e **64** com eventos carregados.
- Em **Partida**, a final deve abrir com **Argentina 3 – 3 France** e a disputa **4 – 2**.
- A primeira abertura depois de um tempo parado pode demorar alguns segundos: o banco gratuito "acorda" e o app "acorda" também.

## Problemas comuns

| O que aparece | Causa provável |
|---|---|
| "Banco não configurado" | O secret `ODDVISION_DATABASE_URL` não foi salvo, ou o nome está diferente |
| "Não foi possível conectar ao PostgreSQL" | URL errada, senha com símbolos sem codificar (`@` vira `%40`, `/` vira `%2F`), ou o banco ainda está acordando: tente de novo |
| "As views de `analytics` não existem neste banco" | Faltou o passo 3 (`init-db`), ou a role de leitura foi criada antes das views |
| `ModuleNotFoundError` | A versão do Python não é a 3.13: ajuste em **Advanced settings** |

## Atualizar os dados depois

Se os dados locais mudarem, repita os passos 2 e 3 (no Neon, antes do `pg_restore`, apague o schema antigo no **SQL Editor**: `DROP SCHEMA core CASCADE;`). A role de leitura continua valendo; o app guarda as consultas em cache por 10 minutos.

## Segurança

- A URL do banco só existe nos *secrets* do Streamlit e no seu gerenciador de senhas. O arquivo `.streamlit/secrets.toml` (para testar localmente) está no `.gitignore`.
- O app usa a role `oddvision_reader` e, além disso, abre toda transação como somente leitura.
- Se a URL aparecer em algum lugar público, troque a senha da role no Neon (`ALTER ROLE oddvision_reader PASSWORD '...';`) e atualize o secret.
- Para testar a configuração da nuvem no seu computador, sem tocar no `database.toml`:
  ```powershell
  $env:ODDVISION_DATABASE_URL = "postgresql://oddvision_reader:SENHA-NOVA@ep-xxxx.regiao.aws.neon.tech/neondb?sslmode=require"
  .\.venv\Scripts\python.exe -m streamlit run app/Home.py
  ```
