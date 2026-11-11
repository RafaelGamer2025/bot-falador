# Bot de fatos e clima com síntese de fala

Projeto didático em Python que combina a tarefa `!start`/`!fact` com o exemplo de clima do anexo.

## O que faz

- `!start`: envia uma mensagem de boas-vindas e apresenta os comandos.
- `!fact`: consulta `https://uselessfacts.jsph.pl/random.json`, usa o campo JSON `text`, envia o fato no Discord e, em seguida, lê o fato com `pyttsx3`.
- `!weather <cidade>`: consulta `wttr.in`, envia condição, temperatura, sensação térmica, umidade e vento, e lê um resumo com `pyttsx3`.
- Depois de `!weather`, cria ou reutiliza um canal chamado `áudio-descrição-do-clima` na categoria do canal de texto. Se quem chamou já estiver em uma chamada de voz, o bot tenta mover essa pessoa para o canal; se não estiver, informa que não a moveu.
- A API do fato imprime sua resposta JSON no console local para facilitar a atividade.

**Importante:** `pyttsx3` reproduz áudio na saída local do computador onde o script está rodando. Esta versão não transmite o áudio do TTS para dentro de um canal de voz do Discord. A criação/movimentação de canal é independente dessa fala local.

## Configurar o bot no Discord

1. Crie uma aplicação no Discord Developer Portal, adicione um Bot e copie o token. Nunca envie o token em chat, captura de tela ou GitHub. Se vazar, regenere-o imediatamente no portal.
2. Em **Bot → Privileged Gateway Intents**, ative **Message Content Intent**. O programa ativa `message_content` no código, mas o portal também precisa permitir.
3. Convide o bot ao servidor com estas permissões: Ver canais, Enviar mensagens, Ler histórico, Gerenciar canais e Mover membros. Para os comandos de texto, o bot precisa enxergar o canal onde serão enviados.
4. Coloque `bot.py`, `requirements.txt` e `.env.example` na mesma pasta. Copie `.env.example` para `.env` e substitua o placeholder pelo token real.

## Executar no Windows

Instale Python 3.10+ e execute no Prompt de Comando, dentro da pasta do projeto:

```bat
py -m pip install -r requirements.txt
py bot.py
```

No Linux/macOS, use `python3 -m pip install -r requirements.txt` e `python3 bot.py`. `pyttsx3` usa o mecanismo de voz instalado no sistema; no Windows normalmente usa SAPI5. No Linux pode ser necessário instalar e configurar eSpeak e uma saída de áudio.

## Testar

No servidor, teste:

```text
!start
!fact
!weather Lisboa
```

Para `!weather` criar canal, o bot precisa de **Gerenciar canais**; para mover quem chamou, precisa de **Mover membros**. O membro só é movido se já estiver conectado a um canal de voz quando executa o comando. Erros das APIs e do Discord são reportados sem mostrar o token.

## Arquivos e segurança

- `.env` é ignorado pelo `.gitignore` do pacote; mantenha-o privado.
- O bot só consulta as APIs públicas descritas no código e não guarda dados de usuários.
- O fato pode vir em inglês, dependendo do idioma retornado pela API.
- O comando de clima reutiliza o canal criado dentro da mesma categoria para evitar criar um canal novo a cada chamada.


## Launcher e verificações

No Windows, `iniciar_bot.bat` cria o `.env` a partir do modelo na primeira execução, pede para você editá-lo e instala as dependências. Depois, você pode iniciar pelo mesmo `.bat`. Não coloque o token no código-fonte.

Os testes de lógica sem rede são executados com `py -m unittest test_bot.py`. Eles verificam o campo `text`, o tratamento do JSON de clima e o carregamento seguro do token.
