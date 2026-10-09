# álbuns

Uma vitrine das minhas playlists e álbuns salvos do Spotify, tratados como álbuns de uma exposição. Quem abre o link vê as capas; ao clicar numa, vê as faixas, o gênero, quem colaborou, o total de faixas, os minutos e a data de criação, com um botão que leva direto para a playlist no Spotify.

**Site:** https://luanchr.github.io/albuns/

<!-- Adicione uma captura de tela em docs/captura.png e troque esta linha por: ![álbuns](docs/captura.png) -->

## Por que fiz

As minhas playlists são parte de quem eu sou, mas o perfil do Spotify mostra só uma lista de nomes. Quis uma página bonita para elas, com a informação que o Spotify não dá (gênero, colaboradores), e que eu pudesse deixar num link.

## Como funciona

```
Spotify  ──►  painel local (Python)  ──►  docs/data/playlists.json  ──►  site estático (GitHub Pages)
              login + edição                  gerado por mim                 HTML, CSS e JS puros
```

- **Painel local** (`servidor/`, FastAPI + SQLite): entro com o Spotify, o servidor busca playlists e álbuns salvos, e eu preencho **gênero, colaboradores e nota** direto na página de cada playlist. Um botão publica o resultado.
- **Site publicado** (`docs/`): HTML, CSS e JavaScript sem framework, lendo um JSON. Quem visita nunca fala com o Spotify, então o site é rápido, grátis e continua no ar com o meu computador desligado.
- **Detalhes de interface:** a capa sobe, inclina e reflete o cursor (estilo vitrine de loja); ao abrir uma playlist a capa viaja até a página de detalhe (View Transitions API); o título "álbuns" é um desenho vetorial extraído da fonte Bricolage Grotesque.
- **Login:** OAuth 2.0 com PKCE, sem guardar senha. O servidor só pede permissão de leitura.

## Por que não é um serviço aberto para todo mundo

A ideia original era mais ambiciosa: qualquer pessoa entra com o Spotify e ganha a sua vitrine para pôr na bio das redes sociais. Isso **não é possível para um desenvolvedor individual**, por regras da plataforma do Spotify:

- **Limite de 5 usuários.** Um app novo fica em *development mode*: só até 5 contas, cadastradas à mão pelo dono do app, conseguem usá-lo. Quem não está na lista consegue fazer login, mas as chamadas à API são recusadas (erro 403).
- **O aumento do limite é só para empresas.** O *extended quota*, que libera usuários ilimitados, desde maio de 2025 só é concedido a organizações: empresa registrada, serviço já em operação e pelo menos 250 mil usuários ativos por mês. Um projeto pessoal não cumpre isso. ([regras de cotas do Spotify](https://developer.spotify.com/documentation/web-api/concepts/quota-modes))
- **A API ficou mais fechada em 2026.** O conteúdo de playlists que não são da própria pessoa logada deixou de ser fornecido, e a prévia de áudio de 30 segundos não existe mais para apps novos. Por isso o site mostra a lista de faixas e não toca trechos.
- **Hospedar o painel custa.** Um servidor sempre ligado, com banco persistente, é pago (na casa de alguns dólares por mês); os planos grátis costumam "dormir" quando ninguém acessa. Para um link de portfólio, o site estático é melhor.

A decisão foi separar as duas partes: o **painel** (que precisa do Spotify e de um servidor) roda só na minha máquina, e o **site** (que é o que as pessoas veem) é estático. Assim o projeto funciona para mim sem custo e sem limite de visitantes.

O painel já está preparado para virar um serviço, com um `Dockerfile`, vitrines por usuário (`/u/nome`) e colaboradores que viram link para a vitrine de outra pessoa. Com até 5 amigos liberados no app do Spotify, funciona como um beta fechado.

## O que aprendi

- Fluxo OAuth com PKCE, renovação de token e tratamento de limites de uso (HTTP 429) de uma API real.
- Ler a documentação a fundo antes de prometer um produto: as regras de cota mudaram o escopo do projeto.
- Separar o que precisa de servidor do que pode ser estático.
- Acessibilidade e movimento: respeito a `prefers-reduced-motion`, foco por teclado, efeitos de hover só para quem tem mouse.

## Rodar a sua própria cópia

Cada pessoa pode usar o seu app gratuito do Spotify (o dono precisa ter Premium) e publicar a sua vitrine. O passo a passo, para Windows, está no [GUIA.md](GUIA.md).

```
fetch_playlists.py   versão em linha de comando: busca no Spotify e gera o JSON
servidor/            painel com login e edição (FastAPI)
docs/                o site publicado (HTML, CSS, JS, capas, dados)
config.json          gênero, colaboradores e nota da versão em linha de comando
Dockerfile           para hospedar o painel, se um dia fizer sentido
```

Feito com Python, FastAPI, SQLite e JavaScript puro.
