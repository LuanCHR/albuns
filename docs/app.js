(() => {
  "use strict";

  const PREVIEW_TRACKS = 8;
  const $ = (sel) => document.querySelector(sel);
  const wall = $("#wall");
  const gallery = $("#gallery");
  const sheet = $("#sheet");
  const sheetBody = $("#sheet-body");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  let siteTitle = "álbuns";
  let albums = [];
  let currentId = null; // álbum aberto no momento
  let openedByClick = false;
  let editable = false; // só no servidor, quando quem vê é o dono da vitrine
  let meInfo = null;
  let editing = false;
  let ownerName = "";
  let pollTimer = null;
  const API = document.body.dataset.api || "";

  // ---------------------------------------------------------- utilidades --
  function h(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === false || value == null) continue;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child != null) node.append(child);
    }
    return node;
  }

  const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro"];

  function formatDate(value) {
    if (!value) return null;
    const [y, m, d] = String(value).split("-").map(Number);
    if (!y) return null;
    if (!m) return String(y);
    if (!d) return `${MONTHS[m - 1]} de ${y}`;
    return `${d} de ${MONTHS[m - 1]} de ${y}`;
  }

  function formatMinutes(min) {
    if (!min) return "menos de 1 min";
    if (min < 60) return `${min} min`;
    const hours = Math.floor(min / 60);
    const rest = min % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
  }

  function formatTrackTime(ms) {
    const total = Math.round((ms || 0) / 1000);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  }

  function listNames(names) {
    try {
      return new Intl.ListFormat("pt-BR", { style: "long", type: "conjunction" }).format(names);
    } catch {
      return names.join(", ");
    }
  }

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const isSpotifyUrl = (url) => typeof url === "string" && /^https:\/\/open\.spotify\.com\//.test(url);

  function safeImageSrc(src) {
    if (!src || typeof src !== "string") return null;
    try {
      const url = new URL(src, location.href);
      return url.protocol === "https:" || url.protocol === "http:" ? src : null;
    } catch {
      return null;
    }
  }

  // Foto + nome de quem é dono do site. Tocar na foto ou no nome abre o perfil no Spotify.
  function renderOwner(site) {
    const box = $("#owner");
    const owner = (site.owner || "").trim();
    const profile = isSpotifyUrl(site.profile_url) ? site.profile_url : null;
    const photo = safeImageSrc(site.avatar);

    const noun = "playlists e álbuns"; // para quem faz o site, playlist é álbum

    const link = (children) => h("a", { href: profile, target: "_blank", rel: "noopener noreferrer" }, children);

    let avatar = null;
    if (photo || owner) {
      const face = photo
        ? h("img", { class: "avatar-img", src: photo, alt: "", width: 56, height: 56 })
        : h("span", { "aria-hidden": "true", text: owner.charAt(0).toUpperCase() });
      avatar = profile
        ? h("a", { class: "avatar", href: profile, target: "_blank", rel: "noopener noreferrer", "aria-label": `Abrir o perfil de ${owner || "quem fez este site"} no Spotify` }, face)
        : h("span", { class: "avatar" }, face);
    }

    let line = null;
    if (site.subtitle) {
      line = h("span", { class: "owner-line", text: site.subtitle });
    } else if (owner) {
      line = h("span", { class: "owner-line" }, `${noun} de `, profile ? link(owner) : owner);
    }

    box.replaceChildren(
      avatar,
      h("p", { class: "owner-text" }, line, h("span", { class: "owner-hint", text: editable ? "Toque numa capa para editar gênero e colaboradores." : "Toque numa capa para ver as faixas." }))
    );
    box.hidden = false;
  }

  function coverNode(album, className) {
    if (album.cover) {
      return h("img", { class: className, src: album.cover, alt: "", width: 600, height: 600 });
    }
    return h("div", { class: `${className} cover-empty`, "aria-hidden": "true", text: album.title.charAt(0) });
  }

  // ------------------------------------------------------------- galeria --
  // Efeito de vitrine: a capa sobe, inclina para o lado do cursor e ganha um brilho
  // que o acompanha. O CSS faz a elevação; aqui só passamos a posição do mouse.
  const TILT_DEGREES = 9;

  function attachTilt(card, frame) {
    const props = ["--mx", "--my", "--rx", "--ry"];
    let frameRequest = 0;
    let last = null;
    // No máximo uma atualização por quadro: o Firefox engasga se cada movimento do mouse refizer o estilo.
    const apply = () => {
      frameRequest = 0;
      if (!last) return;
      const box = frame.getBoundingClientRect(); // o .frame não se move, então a medida é estável
      const x = Math.min(Math.max((last.clientX - box.left) / box.width, 0), 1);
      const y = Math.min(Math.max((last.clientY - box.top) / box.height, 0), 1);
      frame.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
      frame.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
      frame.style.setProperty("--rx", `${((0.5 - y) * TILT_DEGREES).toFixed(2)}deg`);
      frame.style.setProperty("--ry", `${((x - 0.5) * TILT_DEGREES).toFixed(2)}deg`);
    };
    card.addEventListener("pointermove", (event) => {
      if (event.pointerType !== "mouse" || reduceMotion.matches) return;
      last = event;
      if (!frameRequest) frameRequest = requestAnimationFrame(apply);
    });
    card.addEventListener("pointerleave", () => {
      last = null;
      cancelAnimationFrame(frameRequest);
      frameRequest = 0;
      props.forEach((p) => frame.style.removeProperty(p));
    });
  }

  function renderGallery() {
    gallery.replaceChildren(
      ...albums.map((album) => {
        const secondary =
          album.genre || (album.kind === "album" && album.byline) || plural(album.track_count, "faixa", "faixas");
        const frame = h(
          "span",
          { class: "frame" },
          h("span", { class: "lift" }, coverNode(album, "cover"), h("span", { class: "glare", "aria-hidden": "true" }))
        );
        const button = h(
          "button",
          { class: album.hidden ? "card is-hidden" : "card", type: "button", "data-id": album.id },
          frame,
          h("span", { class: "t", text: album.title }),
          h("span", { class: "s", text: secondary })
        );
        attachTilt(button, frame);
        button.addEventListener("click", () => {
          openedByClick = true;
          location.hash = encodeURIComponent(album.id);
        });
        return h("li", {}, button);
      })
    );
  }

  const cardCover = (id) => gallery.querySelector(`.card[data-id="${CSS.escape(id)}"] .cover`);
  const sheetCover = () => sheetBody.querySelector(".sheet-cover");

  // ------------------------------------------------------------- detalhe --
  function fact(label, value) {
    return h("div", {}, h("dt", { text: label }), h("dd", {}, value));
  }

  // Colaborador pode ser texto (versão estática) ou {name, slug} (servidor).
  // Com slug, o nome leva direto para a vitrine daquela pessoa.
  function collaboratorsNode(list) {
    const people = list.map((c) => (typeof c === "string" ? { name: c, slug: null } : c));
    const nodes = [];
    people.forEach((c, i) => {
      if (i > 0) nodes.push(i === people.length - 1 ? " e " : ", ");
      nodes.push(c.slug ? h("a", { class: "collab", href: `/u/${encodeURIComponent(c.slug)}`, text: c.name }) : c.name);
    });
    return nodes;
  }

  function field(label, input, hint) {
    return h("label", { class: "field" }, h("span", { class: "field-l", text: label }), input, hint ? h("span", { class: "field-h", text: hint }) : null);
  }

  function editorNode(album) {
    const isAlbum = album.kind === "album";
    const genre = h("input", { type: "text", maxlength: 80, value: album.genre || "", placeholder: "ex.: indie, trilha sonora" });
    const collabs = h("input", {
      type: "text", value: (album.collaborators || []).map((c) => (typeof c === "string" ? c : c.name)).join(", "),
      placeholder: "nomes separados por vírgula",
    });
    const note = h("input", { type: "text", maxlength: 280, value: album.note || "", placeholder: "uma frase sobre esta playlist (opcional)" });
    const error = h("p", { class: "form-error", role: "alert" });
    const save = h("button", { class: "cta", type: "submit", text: "salvar" });
    const cancel = h("button", { class: "more", type: "button", text: "cancelar" });
    const form = h(
      "form",
      { class: "editor" },
      field("gênero", genre),
      isAlbum ? null : field("colaboradores", collabs, "Separe por vírgula. Se a pessoa já tem conta no álbuns, o nome dela vira link para a vitrine dela."),
      field("nota", note),
      error,
      h("div", { class: "editor-actions" }, save, cancel)
    );
    cancel.addEventListener("click", () => { editing = false; renderSheet(album); });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(`/api/item/${encodeURIComponent(album.id)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json", "X-Requested-With": "albuns" },
          body: JSON.stringify({
            genre: genre.value,
            collaborators: collabs.value.split(",").map((x) => x.trim()).filter(Boolean),
            note: note.value,
          }),
        });
        if (!response.ok) {
          let detail = "Não consegui salvar. Tente de novo.";
          try { detail = (await response.json()).detail || detail; } catch { /* sem corpo */ }
          throw new Error(typeof detail === "string" ? detail : "Dados inválidos.");
        }
        const updated = await response.json();
        const index = albums.findIndex((a) => a.id === album.id);
        if (index >= 0) albums[index] = updated;
        editing = false;
        renderGallery();
        renderSheet(updated);
      } catch (err) {
        error.textContent = err.message;
        save.disabled = false;
      }
    });
    return form;
  }

  function editButton(album) {
    const button = h("button", { class: "more edit-btn", type: "button", text: "editar" });
    button.addEventListener("click", () => { editing = true; renderSheet(album); });
    return button;
  }

  function renderSheet(album) {
    const isAlbum = album.kind === "album"; // álbum salvo na biblioteca (não é playlist sua)

    let facts;
    if (isAlbum) {
      facts = h(
        "dl",
        { class: "facts" },
        fact("lançado em", formatDate(album.released) || "sem data"),
        fact("salvo em", formatDate(album.saved_at) || "sem data"),
        fact("duração", formatMinutes(album.duration_min)),
        fact("faixas", String(album.track_count))
      );
    } else {
      let collaborators = ownerName || "só eu";
      if (album.collaborators && album.collaborators.length) collaborators = collaboratorsNode(album.collaborators);
      else if (album.collaborative) collaborators = "playlist colaborativa";
      facts = h(
        "dl",
        { class: "facts" },
        fact("criada em", formatDate(album.created) || "sem data"),
        fact("duração", formatMinutes(album.duration_min)),
        fact("faixas", String(album.track_count)),
        fact("colaboradores", collaborators)
      );
    }

    const tracks = album.tracks || [];
    const list = h("ol", { class: "tracks" });
    const rows = tracks.map((track, index) => {
      // Num álbum todas as faixas têm a mesma capa, então a miniatura não diz nada.
      const thumb = isAlbum
        ? null
        : track.cover
          ? h("img", { class: "thumb", src: track.cover, alt: "", width: 40, height: 40, loading: "lazy" })
          : h("span", { class: "thumb", "aria-hidden": "true" });
      return h(
        "li",
        { class: isAlbum ? "track no-thumb" : "track" },
        h("span", { class: "n", "aria-hidden": "true", text: String(index + 1) }),
        thumb,
        h("span", {}, h("span", { class: "tt", text: track.name }), h("span", { class: "ta", text: (track.artists || []).join(", ") })),
        h("span", { class: "d", text: formatTrackTime(track.duration_ms) })
      );
    });
    list.append(...rows.slice(0, PREVIEW_TRACKS));

    const tracksBlock = [h("h3", { class: "tracks-h", text: "faixas" }), list];
    if (rows.length > PREVIEW_TRACKS) {
      const hidden = rows.length - PREVIEW_TRACKS;
      const more = h("button", { class: "more", type: "button", "aria-expanded": "false", text: `mostrar mais ${plural(hidden, "faixa", "faixas")}` });
      more.addEventListener("click", () => {
        const expanded = more.getAttribute("aria-expanded") === "true";
        list.replaceChildren(...(expanded ? rows.slice(0, PREVIEW_TRACKS) : rows));
        more.setAttribute("aria-expanded", String(!expanded));
        more.textContent = expanded ? `mostrar mais ${plural(hidden, "faixa", "faixas")}` : "mostrar menos";
      });
      tracksBlock.push(more);
    }
    if (album.track_count > tracks.length) {
      tracksBlock.push(h("p", { class: "hint", text: `Mostrando as primeiras ${tracks.length} de ${album.track_count} faixas. O resto está no Spotify.` }));
    }

    const cta = isSpotifyUrl(album.url)
      ? h("a", { class: "cta", href: album.url, target: "_blank", rel: "noopener noreferrer", text: "abrir no spotify" })
      : null;

    sheetBody.replaceChildren(
      h(
        "div",
        { class: "sheet-grid" },
        h("div", { class: "sheet-cover-wrap" }, coverNode(album, "cover sheet-cover")),
        h(
          "div",
          {},
          h("h2", { class: "sheet-title", id: "sheet-title", text: album.title }),
          isAlbum && album.byline ? h("p", { class: "sheet-by", text: `de ${album.byline}` }) : null,
          editing ? editorNode(album) : album.genre ? h("p", { class: "sheet-genre", text: album.genre }) : null,
          facts,
          !editing && album.note ? h("p", { class: "note", text: album.note }) : null,
          h("div", { class: "actions" }, cta, editable && !editing ? editButton(album) : null),
          tracksBlock
        )
      )
    );
  }

  function showSheet(album) {
    editing = false;
    renderSheet(album);
    sheet.hidden = false;
    sheet.scrollTop = 0;
    wall.inert = true;
    document.body.classList.add("sheet-open");
    document.title = `${album.title} — ${siteTitle}`;
    $("#back").focus({ preventScroll: true });
  }

  function hideSheet(previousId) {
    sheet.hidden = true;
    wall.inert = false;
    document.body.classList.remove("sheet-open");
    document.title = siteTitle;
    const card = previousId && gallery.querySelector(`.card[data-id="${CSS.escape(previousId)}"]`);
    if (card) card.focus({ preventScroll: true });
  }

  // ---------------------------------------------------------- navegação --
  // O endereço (#id) é a fonte da verdade: dá para mandar o link de um álbum.
  function route() {
    let id = "";
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { /* hash inválido */ }
    const album = albums.find((a) => a.id === id) || null;
    const next = album ? album.id : null;
    if (next === currentId) return;

    const previous = currentId;
    currentId = next;
    const update = () => (album ? showSheet(album) : hideSheet(previous));

    const canAnimate = document.startViewTransition && !reduceMotion.matches && !(next && previous);
    if (!canAnimate) {
      update();
      return;
    }

    // A capa que está na tela ganha um nome; depois da troca, quem a substitui herda o nome.
    const from = next ? cardCover(next) : sheetCover();
    if (from) from.style.viewTransitionName = "cover";
    const transition = document.startViewTransition(() => {
      if (from) from.style.viewTransitionName = "";
      update();
      const to = next ? sheetCover() : cardCover(previous);
      if (to) to.style.viewTransitionName = "cover";
    });
    transition.finished.finally(() => {
      document.querySelectorAll(".cover").forEach((el) => { el.style.viewTransitionName = ""; });
    });
  }

  function closeSheet() {
    if (openedByClick) {
      openedByClick = false;
      history.back(); // volta para a galeria e dispara o route()
    } else {
      history.replaceState(null, "", location.pathname + location.search);
      route();
    }
  }

  $("#back").addEventListener("click", closeSheet);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && currentId) closeSheet();
  });
  window.addEventListener("hashchange", () => {
    if (!location.hash) openedByClick = false;
    route();
  });

  // ------------------------------------------------------------- início --
  function renderFooter(data) {
    const foot = $("#foot");
    foot.replaceChildren();
    const when = data.generated_at ? new Date(data.generated_at) : null;
    if (when && !Number.isNaN(when.getTime())) {
      foot.append(h("span", { text: `atualizado em ${formatDate(when.toISOString().slice(0, 10))}` }));
    }
    if (isSpotifyUrl(data.site && data.site.profile_url)) {
      foot.append(h("a", { href: data.site.profile_url, target: "_blank", rel: "noopener noreferrer", text: "perfil no spotify" }));
    }
    if (!API) return;
    if (data.editable) {
      const sync = h("button", { class: "link-btn", type: "button", text: "atualizar do spotify" });
      sync.addEventListener("click", async () => {
        sync.disabled = true;
        const response = await fetch("/api/sync", { method: "POST", headers: { "X-Requested-With": "albuns" } });
        if (response.ok) init();
        else { sync.textContent = "espere um minuto e tente de novo"; }
      });
      foot.append(sync);
      if (data.can_export) {
        const publish = h("button", { class: "link-btn", type: "button", text: "publicar no github pages" });
        const note = h("span", { role: "status" });
        publish.addEventListener("click", async () => {
          publish.disabled = true;
          note.textContent = "Salvando a vitrine e baixando as capas…";
          try {
            const response = await fetch("/api/export", { method: "POST", headers: { "X-Requested-With": "albuns" } });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || "falhou");
            note.textContent = `Pronto: ${plural(result.count, "álbum salvo", "álbuns salvos")} na pasta docs. Agora envie ao GitHub (passo 5 do README).`;
          } catch (err) {
            note.textContent = `Não consegui publicar: ${err.message}`;
          }
          publish.disabled = false;
        });
        foot.append(publish, note);
      }
      foot.append(h("a", { href: "/logout", text: "sair" }));
    } else if (meInfo) {
      foot.append(h("a", { href: `/u/${encodeURIComponent(meInfo.slug)}`, text: "minha vitrine" }));
    } else {
      foot.append(h("a", { href: "/", text: "entrar / criar a minha vitrine" }));
    }
  }

  async function init() {
    const status = $("#status");
    clearTimeout(pollTimer);
    let data;
    try {
      const response = await fetch(API || "data/playlists.json", { cache: "no-store" });
      if (response.status === 404 && API) {
        status.textContent = "Não encontrei essa vitrine.";
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      data = await response.json();
    } catch {
      status.textContent = API
        ? "Não consegui carregar a vitrine. Tente de novo em instantes."
        : "Não consegui carregar as playlists. Se abriu o arquivo direto do computador, rode `python -m http.server -d docs` e abra localhost:8000.";
      return;
    }

    const site = data.site || {};
    siteTitle = site.title || "álbuns";
    albums = data.albums || [];
    editable = !!data.editable;
    ownerName = (site.owner || "").trim();
    meInfo = data.me || null;
    document.title = API && site.owner ? `álbuns de ${site.owner}` : siteTitle;
    // A logo "álbuns" é um desenho (SVG); só trocamos por texto se a pessoa escolheu outro título.
    if (siteTitle.trim().toLowerCase() !== "álbuns") $("#site-title").textContent = siteTitle;
    renderOwner(site);
    $("#sample-note").hidden = !data.sample;
    renderFooter(data);

    if (data.syncing) {
      status.textContent = "Buscando as playlists no Spotify. Leva um minutinho…";
      pollTimer = setTimeout(init, 3000);
      if (!albums.length) return;
    } else if (data.sync_error) {
      status.textContent = data.sync_error === "403"
        ? "O Spotify não liberou o acesso a esta conta. O beta é fechado: o dono precisa te adicionar na lista do app."
        : "A última busca no Spotify falhou. Use \"atualizar do spotify\" lá embaixo para tentar de novo.";
    } else {
      status.textContent = "";
    }

    if (!albums.length) {
      if (!data.syncing && !data.sync_error) {
        status.textContent = API
          ? "Ainda não há álbuns por aqui."
          : "Ainda não há álbuns por aqui. Rode fetch_playlists.py para trazer as playlists.";
      }
      gallery.replaceChildren();
      return;
    }
    renderGallery();
    route(); // abre direto o álbum se o link tiver #id
  }

  init();
})();
