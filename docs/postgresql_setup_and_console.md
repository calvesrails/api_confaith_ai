# PostgreSQL E Console Do Banco

## Banco recomendado

A API agora esta preparada para rodar com PostgreSQL em producao e continuar usando SQLite apenas em testes locais, se necessario.

Exemplo de `DATABASE_URL` para PostgreSQL:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/contact_validation
```

## Dependencia do driver

O projeto usa o driver `psycopg[binary]` para conectar o SQLAlchemy ao PostgreSQL.

## Como criar o banco localmente

Exemplo com `psql` no Linux:

```bash
sudo -u postgres psql
```

Dentro do `psql`:

```sql
CREATE DATABASE contact_validation;
CREATE USER contact_validation_user WITH PASSWORD 'troque_essa_senha';
GRANT ALL PRIVILEGES ON DATABASE contact_validation TO contact_validation_user;
```

Depois, ajuste o `.env`:

```env
DATABASE_URL=postgresql+psycopg://contact_validation_user:troque_essa_senha@localhost:5433/contact_validation
```

## Como subir a API com PostgreSQL

1. Ajuste `DATABASE_URL` no `.env`.
2. Instale as dependencias:

```bash
./.venv/bin/pip install -r requirements.txt
```

3. Reinicie o `uvicorn`.

Na subida, a aplicacao executa `Base.metadata.create_all(...)`, entao as tabelas sao criadas automaticamente se ainda nao existirem.

## Como acessar o banco pelo terminal

### Opcao 1: SQL puro com psql

Se o `DATABASE_URL` estiver apontando para PostgreSQL:

```bash
psql "$DATABASE_URL"
```

Exemplos uteis dentro do `psql`:

```sql
\dt
SELECT id, company_name, status FROM platform_accounts ORDER BY id DESC;
SELECT id, batch_id, batch_status, created_at FROM validation_batches ORDER BY id DESC LIMIT 20;
SELECT id, external_id, supplier_name, final_status FROM validation_records ORDER BY id DESC LIMIT 20;
SELECT id, provider_call_id, status, result, duration_seconds FROM call_attempts ORDER BY id DESC LIMIT 20;
```

### Opcao 2: console da aplicacao, estilo rails console

Foi adicionado o arquivo:
- `/home/calves/api_confaith_ai/scripts/db_console.py`

Para abrir:

```bash
./.venv/bin/python scripts/db_console.py
```

O console abre com estes objetos disponiveis:
- `session`
- `sql(...)`
- `first(Model)`
- `all_rows(Model)`
- todos os models principais

Exemplos:

```python
session.query(PlatformAccountModel).all()
session.query(ValidationBatchModel).order_by(ValidationBatchModel.id.desc()).limit(10).all()
session.query(ValidationRecordModel).filter_by(final_status='validated').count()
sql("select id, batch_id, batch_status from validation_batches order by id desc limit 10")
```

## Observacoes

- O arquivo `.env.example` agora mostra PostgreSQL como exemplo principal.
- O projeto ainda aceita SQLite se `DATABASE_URL` continuar apontando para `sqlite:///...`.
- Os testes automatizados continuam livres para usar SQLite temporario em `/tmp`.
