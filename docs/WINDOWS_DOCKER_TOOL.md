# Kevin — Backend Docker Tool Executor no Windows

## 1. Visão Geral
Este documento descreve a integração do executor Docker real, estritamente **opt-in** e restrito ao runtime existente do Kevin (`SWE-AF`).
O backend executa operações da ferramenta `Write` dentro de containers Linux descartáveis e confinados, sem montagem de diretórios do host, sem acesso à rede e sem persistência de arquivos na máquina local.

## 2. Pré-requisitos e Instalação
- **Sistema Operacional**: Windows 10/11 com PowerShell 5.1+ ou PowerShell 7+ (pwsh).
- **Docker Desktop**: Engine ativo configurado com backend WSL2.
- **Python**: Python 3.12 (ou ambiente virtual com dependências do Kevin instaladas via `pip install -e .[dev]`).
- **Imagem Base Fixada por Digest**:
  - Imagem: `python:3.12-alpine`
  - Digest: `sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`
  - Referência: `python@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`
  - Plataforma: `linux/amd64`
  - Verificação de presença local:
    ```powershell
    docker images --digests python
    ```

## 3. Seleção Opt-in do Backend
A ativação é estritamente manual e explícita via variável de ambiente:

```powershell
$env:SWE_HARNESS_BACKEND = "docker-tool"
```

### Comportamento Fail-Closed:
- Se `SWE_HARNESS_BACKEND` não estiver definido (unset), o backend padrão permanece inalterado (`agentfield`).
- Se `SWE_HARNESS_BACKEND` estiver vazio ou apontar para um backend inexistente, o Kevin **falha imediatamente** (`HarnessBackendUnavailable` / `HarnessBackendConfigurationError`), sem fallback silencioso para `agentfield` ou outros backends.
- O backend `local-tool` continua disponível via `$env:SWE_HARNESS_BACKEND = "local-tool"`.

## 4. Confinamento e Segurança do Container
Cada invocação do executor executa um container Docker descartável com as seguintes restrições:
- `--rm`: remoção automática do container após o encerramento.
- `--name <uuid>`: nome único com remoção explícita garantida (`docker rm -f <uuid>`) no bloco `finally`, prevenindo containers órfãos mesmo sob timeout ou cancelamento (`asyncio.CancelledError`).
- `--network none`: isolamento completo de rede.
- `--read-only`: filesystem raiz somente leitura (qualquer tentativa de escrita fora do tmpfs falha imediatamente com `Read-only file system`).
- `--cap-drop ALL`: eliminação de todas as capacidades Linux (capabilities).
- `--security-opt no-new-privileges`: bloqueio total de escalada de privilégios.
- `--pids-limit 64`: limite rígido de processos simultâneos.
- `--memory 128m`: limite de memória RAM alocada.
- `--cpus 1`: limite de processador.
- `--user 65534:65534`: execução sob usuário desprivilegiado (`nobody:nobody`).
- `--tmpfs /tmp:rw,noexec,nosuid,size=16m`: workspace efêmero em memória.
- `--workdir /tmp`: diretório de trabalho apontando para o tmpfs.
- **Sem Bind Mounts**: nenhum diretório do host, socket do Docker (`/var/run/docker.sock`), chaves SSH ou tokens são montados.
- **Protocolo de Comunicação**: entrada estruturada via `stdin` com protocolo JSON validado. Não há interpolação de dados do usuário em código Python, scripts ou argumentos shell.
- **Limite de Saída durante a Leitura**: o limite de bytes de saída (`max_output_bytes`) é imposto durante a leitura em chunks dos fluxos `stdout`/`stderr`, abortando a execução se o limite for ultrapassado.

## 5. Limites Conhecidos e Superfície Permitida
- **Ferramenta Suportada**: exclusivamente a ferramenta `Write`. Ferramentas como `Bash`, `Read`, `Edit`, `Glob`, `Grep` são explicitamente rejeitadas.
- **Validação de Caminho**:
  - Aceita apenas caminhos relativos no formato POSIX (ex: `sub/output.txt`).
  - Rejeita caminhos absolutos (`/etc`, `C:/`, `\\server\share`).
  - Rejeita directory traversal (`..`, `../`, `foo/../../bar`).
  - Rejeita separadores do Windows (`\`).
  - Rejeita caractere NUL (`\0`).
  - Rejeita caracteres inválidos (`*`, `?`, `"`, `<`, `>`, `|`, `:`).
  - Rejeita nomes reservados de dispositivos (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).
- **Limites de Tamanho**:
  - Caminho: máximo de 1024 bytes.
  - Conteúdo: máximo de 64 KB.
  - Saída: máximo de 64 KB (ou limite configurado no `ToolExecutionContext`).
- **Natureza Efêmera**: o arquivo gravado existe apenas no container durante a execução. O resultado retornado é a evidência estruturada da escrita, e o arquivo não persiste no disco do host.

## 6. Execução Reproduzível

### Executando Testes Unitários e de Integração:
```powershell
# Define o guard local de testes exigido pelo conftest do Kevin
$env:AGENTFIELD_SERVER = "http://localhost:9999"

# Execução da suíte completa de testes do executor e dispatchers
python -m pytest -v `
  tests/test_docker_tool_executor.py `
  tests/test_docker_tool_harness.py `
  tests/test_docker_tool_integration.py `
  tests/test_harness_dispatch.py `
  tests/test_tool_harness.py `
  tests/test_candidate_tool_executor.py
```

### Invocação via Dispatcher do Kevin:
```python
import asyncio
from pathlib import Path
from swe_af.runtime.application_harness import dispatch_harness
from swe_af.runtime.docker_tool_harness import register_docker_tool_backend

# Registra o backend
register_docker_tool_backend()

# Seleciona o backend opt-in
import os
os.environ["SWE_HARNESS_BACKEND"] = "docker-tool"

class MinimalAgent:
    async def harness(self, *args, **kwargs): pass

async def main():
    outcome = await dispatch_harness(
        MinimalAgent(),
        "Teste de execução",
        tools=["Write"],
        cwd=str(Path.cwd()),
        tool_args={"path": "resultado.txt", "content": "Evidência de execução Docker."},
    )
    print("Status:", outcome.parsed["ok"])
    print("Resultado:", outcome.parsed["executed_tools"])

asyncio.run(main())
```

## 7. Como Desligar
Para desativar o backend Docker e retornar ao comportamento padrão:

```powershell
Remove-Item env:SWE_HARNESS_BACKEND
```
Ou no código:
```python
import os
os.environ.pop("SWE_HARNESS_BACKEND", None)
```

## 8. Rollback
Para reverter as alterações desta branch e restaurar o estado de `origin/main`:

```powershell
git checkout origin/main
# ou na branch de trabalho:
git reset --hard origin/main
```

## 9. Evidências de Teste
Execução realizada no host Windows com Python 3.12.10 e Docker Engine 29.8.1:
- `python -m compileall -q swe_af`: código de saída 0 (sem erros de compilação).
- `git diff --check`: código de saída 0 (sem problemas de formatação/espaçamento).
- `pytest`: 61 testes executados, 61 PASSADOS, 0 FALHAS, 0 SKIPS (duração: 8.86 segundos).
