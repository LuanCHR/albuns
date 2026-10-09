álbuns

Uma galeria pessoal das minhas playlists do Spotify, tratadas como álbuns. Quem abre o link vê as capas; ao tocar numa, vê as faixas, o gênero, os colaboradores, a duração e a data de criação, com um botão que leva direto para a playlist no Spotify.

    Python (fetch_playlists.py): entra na minha conta do Spotify, busca as playlists e as faixas e gera docs/data/playlists.json.
    Site estático (docs/): HTML, CSS e JavaScript puros que leem esse JSON. Publicado no GitHub Pages.

Quem visita o site nunca fala com a API do Spotify. Só o script, na minha máquina, fala. Para atualizar a galeria, rodo o script de novo e faço push.
Quer ter o seu?

Este projeto é um modelo: cada pessoa roda a sua própria cópia, com a sua conta do Spotify, e publica o seu próprio site. Não existe um servidor central. O que muda de uma pessoa para outra é só o config.json e o app do Spotify (que é de graça, mas o dono precisa ter Premium).

O site mostra o que você escolher:

    suas playlists (por padrão, só as públicas);
    álbuns que você salvou na biblioteca do Spotify (opcional, veja o passo 2);
    sua foto de perfil ao lado do título, levando ao seu perfil no Spotify.

Passo a passo (Windows)

Antes de tudo: extraia o zip (botão direito, Extrair tudo) e use só a pasta que sair. Dentro dela têm que aparecer rodar.bat, fetch_playlists.py e docs.
1. Criar o app no Spotify (uma vez só)

    Entre em https://developer.spotify.com/dashboard com a conta que tem Premium (o Spotify exige Premium do dono do app).
    Create app. Nome e descrição livres. O campo Website pode ficar vazio.
    Em Redirect URIs, escreva exatamente http://127.0.0.1:8888/callback e clique em Add. O endereço tem que aparecer numa lista abaixo do campo.
    Em Which API/SDKs are you planning to use?, marque só Web API.
    Marque a caixa dos termos e clique em Save.
    Abra o app, entre em Settings e use o ícone de copiar ao lado do Client ID.

2. Buscar as playlists

Dê dois cliques em rodar.bat.

    Se pedir o Client ID, cole o que você copiou e aperte Enter. Ele fica salvo e não pergunta de novo.
    O navegador abre para você aceitar o acesso ao Spotify. Clique em Aceito e volte para a janela preta.
    No fim, aparece "Pronto" e a lista de playlists que ainda estão sem gênero.

O script traz só as suas playlists públicas. Para incluir as privadas, rode no terminal: python fetch_playlists.py --include-private.

Álbuns salvos: para mostrar também os álbuns da sua biblioteca, rode uma vez python fetch_playlists.py --source all. O Spotify vai pedir uma permissão nova (ler a biblioteca), então o navegador abre de novo. Para isso virar o padrão, coloque "sources": ["playlists", "albums"] no config.json (o rodar.bat passa a trazer os dois). Por padrão vêm os 100 álbuns salvos mais recentes (--max-albums muda isso). Álbuns mostram a data de lançamento e a de quando você salvou, e o artista no lugar de colaboradores. O gênero, se quiser, você escreve no config.json como nas playlists.

Foto do perfil: o script baixa a foto do seu Spotify. Se você não tem foto lá, o site mostra a inicial do seu nome. Para usar outra, ponha a imagem na pasta docs e escreva o nome do arquivo em site.avatar no config.json.
3. Preencher o que o Spotify não informa

O script cria o config.json com uma entrada por playlist. Abra e preencha:

"3cEYpjA9oz9GiPac4AsH4n": {
  "name": "christian diagnosis",
  "genre": "trilha sonora de jogo",
  "created": "2025-02-02",
  "collaborators": [],
  "hidden": false,
  "note": ""
}

campo 	o que faz
genre 	Gênero do álbum. Aparece embaixo do nome na galeria e na página do álbum. Pode ter mais de um, separados por vírgula ("pop, indie").
created 	Data de criação (2025-02-02, 2025-02 ou 2025). Se ficar vazio, o site usa a data em que a primeira faixa foi adicionada.
collaborators 	Nomes de quem colaborou. Se ficar vazio em uma playlist colaborativa, o script tenta descobrir sozinho e, se não conseguir, o site mostra "playlist colaborativa".
hidden 	true esconde a playlist do site.
note 	Texto opcional que aparece embaixo do título.
title 	Opcional. Troca o nome exibido no site sem mexer na playlist.
name 	Só referência para você achar a playlist. O script atualiza sozinho.

A ordem das entradas no config.json é a ordem da galeria. Mude as entradas de lugar para reorganizar. Playlists novas entram no topo.

No começo do arquivo, o bloco site muda o título grande (title; o "álbuns" padrão é um desenho da fonte, e um título diferente aparece como texto na mesma fonte), o texto ao lado da foto (subtitle), o nome (owner), o link do perfil (profile_url) e a foto (avatar). Tudo isso o script preenche sozinho a partir do seu Spotify; só escreva se quiser trocar.

Depois de editar, dê dois cliques em rodar.bat de novo.
4. Ver no computador

Dê dois cliques em ver-site.bat. O navegador abre em http://localhost:8000. Feche a janela preta quando terminar. (Abrir o index.html com duplo clique não funciona, porque o navegador bloqueia a leitura do JSON.)
5. Publicar no GitHub Pages

    Crie um repositório no GitHub e envie o projeto (git add . && git commit -m "primeira versão" && git push).
    No repositório: Settings → Pages → Build and deployment. Em Source escolha Deploy from a branch, branch main, pasta /docs.
    Em um ou dois minutos o site fica em https://SEU-USUARIO.github.io/NOME-DO-REPOSITORIO/.

Esse é o link para a bio do Instagram e do TikTok, e para o post do LinkedIn. Cada álbum também tem link próprio: .../#ID-DA-PLAYLIST.
6. Atualizar depois

Dois cliques em rodar.bat, depois:

git add .
git commit -m "atualiza playlists"
git push

Estrutura

rodar.bat            atualiza as playlists (dois cliques)
ver-site.bat         mostra o site no seu computador (dois cliques)
fetch_playlists.py   busca no Spotify e gera o JSON
config.json          gênero, data, colaboradores, ordem (você edita)
requirements.txt     dependências do Python
docs/
  index.html         página
  style.css          visual
  app.js             galeria e detalhe de cada álbum
  data/playlists.json  gerado pelo script
  covers/            capas baixadas pelo script

Arquivos que o script cria e o Git ignora: .env (seu Client ID) e .spotify_token.json (o login).
Limites da API do Spotify (2026)

    A prévia em áudio de 30 segundos não existe mais para apps novos. Por isso o site mostra a lista de faixas.
    Playlist não tem gênero nem data de criação na API. Daí o config.json.
    Apps em modo de desenvolvimento têm limite de usuários e de chamadas. Isso não afeta o site, só o script.
    Cada playlist guarda até 100 faixas no site (--max-tracks muda isso). O total de faixas e a duração sempre contam a playlist inteira.

Painel com login (servidor)

O servidor em Python (servidor/) é o jeito mais confortável de montar a vitrine: você entra com o Spotify, edita gênero, colaboradores e nota direto na página da playlist e, quando estiver bom, publica no GitHub Pages. O servidor roda só no seu computador e só enquanto você edita; o site publicado não depende dele.

Rodar:

    No painel do Spotify (developer.spotify.com/dashboard > seu app > Settings), adicione http://127.0.0.1:8000/callback em Redirect URIs e salve.
    Confira que o .env tem SPOTIFY_CLIENT_ID=....
    No terminal do VS Code: python -m pip install -r requirements.txt e depois python -m uvicorn servidor.app:app --host 127.0.0.1 --port 8000 (ou dois cliques em servidor.bat, fora do VS Code).
    Abra http://127.0.0.1:8000 no navegador, clique em entrar com o Spotify.

Na primeira entrada, o que você já escreveu no config.json (gênero, colaboradores, nota) é importado sozinho.

Publicar no GitHub Pages (o que vai no LinkedIn):

    Com o painel aberto e logado, clique em publicar no github pages no rodapé. Isso grava docs/data/playlists.json e baixa as capas.
    Envie para o GitHub (no VS Code: Source Control, mensagem, Commit, Sync Changes; ou git add . && git commit -m "atualiza" && git push).
    Na primeira vez: no repositório, Settings > Pages > Deploy from a branch, branch main, pasta /docs. O endereço sai como https://SEU-USUARIO.github.io/NOME-DO-REPOSITORIO/.

O site publicado mostra tudo: capas, faixas, total de faixas, minutos, gênero, colaboradores e o botão para abrir no Spotify.

Limite do Spotify: o app em modo de desenvolvimento aceita até 5 pessoas (cada uma cadastrada em Settings > User Management). Para você sozinho não pesa.

Colocar o painel na internet (opcional): o Dockerfile está pronto. Em uma hospedagem de aplicativos com disco persistente montado em /data, defina BASE_URL=https://seu-endereco, SPOTIFY_CLIENT_ID=... e SECRET_KEY=... (um texto longo qualquer), e cadastre https://seu-endereco/callback no Spotify. Cada pessoa liberada ganha uma vitrine em /u/nome, e o nome de um colaborador que também tem conta vira link para a vitrine dele.