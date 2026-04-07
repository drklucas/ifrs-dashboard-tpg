# Como rodar o projeto

## 1) Configurar variaveis de ambiente

1. Copie o arquivo de exemplo:

```powershell
Copy-Item .env.example .env
```

2. Edite o `.env` com seus dados:
- `MOODLE_USER`
- `MOODLE_PASS`
- `COURSE_IDS` (ids separados por virgula)
- opcional: `FORCE_SCRAPE=1` para forcar novo scrape no dia

## 2) Rodar localmente (Python)

No PowerShell, na pasta raiz do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r .\scraper\requirements.txt
python .\scraper\main.py
```

Ao finalizar, o dashboard sera gerado em:
- `output/dashboard.html`

## 3) Rodar com Docker (opcional)

```powershell
docker compose up --build
```

Tambem gera:
- `output/dashboard.html`

## 4) Regra de execucao diaria

Agora o scraper so roda 1 vez por dia (baseado em `data/courses.json` -> `last_updated`).

- Se ja rodou hoje: pula o scrape e so regenera o HTML (mais rapido).
- Para forcar scrape no mesmo dia, adicione no `.env`:

```env
FORCE_SCRAPE=1
```

# Github Pages 

Como publicar:

```
git add docs/index.html
git commit -m "Atualiza dashboard"
git push
```

O GitHub Pages atualiza automaticamente após o push (leva ~1 min).