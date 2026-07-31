# InterRats Tracker

Aplicacao desktop/console para Windows voltada ao diagnostico de instabilidades intermitentes de rede, internet, DNS, telefonia IP e audio local.

## Requisitos

- Windows 10 ou Windows 11
- Python 3.12 recomendado
- Dependencias listadas em `requirements.txt`

## Instalacao

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Execucao

```powershell
python -m src.main
```

Ao executar, a aplicacao cria automaticamente as pastas locais de trabalho quando necessario:

```text
data/
logs/
reports/
```

Essas pastas armazenam banco SQLite, logs e relatorios gerados durante o uso, por isso nao fazem parte do repositorio.

## Estrutura do Codigo

```text
src/
  main.py
  app/
  audio/
  analysis/
  config/
  monitoring/
  reports/
  storage/
  utils/
```

## Privacidade

A aplicacao coleta apenas evidencias tecnicas para diagnostico de conectividade, telefonia, desempenho e dispositivos. Ela nao coleta senhas, credenciais SIP, historico de navegacao, arquivos pessoais, chamadas, cookies ou tokens.

O modulo de audio nao grava chamadas, nao salva audio bruto por padrao, nao faz transcricao e nao reconhece fala.
