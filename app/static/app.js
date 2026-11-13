/* Awaaz frontend — vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const TOKEN_KEY = "awaaz.token";

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    file: null,
    pollTimer: null,
    openId: null,
  };

  // ── Helpers ──────────────────────────────────────────────────────────
  function toast(msg, ms = 2600) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("is-on");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("is-on"), ms);
  }

  function showError(el, msg) {
    if (!msg) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.textContent = msg;
    el.hidden = false;
  }

  function fmtBytes(n) {
    if (!n) return "0 B";
    const u = ["B", "KB", "MB", "GB"];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < u.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
  }

  function fmtClock(sec) {
    if (sec == null || Number.isNaN(sec)) return "—";
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (opts.body && !(opts.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    const res = await fetch(path, Object.assign({}, opts, { headers }));

    if (res.status === 401) {
      signOut();
      throw new Error("Your session expired. Please sign in again.");
    }

    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const data = await res.json();
        if (typeof data.detail === "string") detail = data.detail;
        else if (Array.isArray(data.detail) && data.detail[0]?.msg) {
          detail = data.detail[0].msg;
        }
      } catch {
        /* non-JSON error body */
      }
      throw new Error(detail);
    }

    if (res.status === 204) return null;
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res.text();
  }

  // ── Auth ─────────────────────────────────────────────────────────────
  function setToken(token) {
    state.token = token || "";
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  }

  function signOut() {
    setToken("");
    stopPolling();
    $("#app").classList.add("is-hidden");
    $("#gate").classList.remove("is-hidden");
    closeDrawer();
  }

  function enterApp() {
    $("#gate").classList.add("is-hidden");
    $("#app").classList.remove("is-hidden");
    loadHistory();
    checkEngine();
  }

  async function checkEngine() {
    const pill = $("#engine-pill");
    try {
      const h = await api("/api/health");
      if (h.engine_ready) {
        pill.textContent = h.model;
        pill.className = "pill is-ready";
        pill.title = "Speech model loaded";
      } else {
        pill.textContent = "loading";
        pill.className = "pill is-loading";
        pill.title = "Model loads on first transcription";
      }
    } catch {
      pill.textContent = "offline";
      pill.className = "pill";
    }
  }

  // ── Tabs ─────────────────────────────────────────────────────────────
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.remove("is-active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("is-active");
      tab.setAttribute("aria-selected", "true");

      const which = tab.dataset.tab;
      $("#login-form").classList.toggle("is-hidden", which !== "login");
      $("#register-form").classList.toggle("is-hidden", which !== "register");
      showError($("#gate-error"), "");
    });
  });

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const btn = form.querySelector("button[type=submit]");
    showError($("#gate-error"), "");
    btn.disabled = true;
    btn.textContent = "Signing in…";
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: form.email.value.trim(),
          password: form.password.value,
        }),
      });
      setToken(data.access_token);
      form.reset();
      enterApp();
    } catch (err) {
      showError($("#gate-error"), err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Sign in";
    }
  });

  $("#register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.currentTarget;
    const btn = form.querySelector("button[type=submit]");
    showError($("#gate-error"), "");
    btn.disabled = true;
    btn.textContent = "Creating…";
    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          email: form.email.value.trim(),
          password: form.password.value,
          display_name: form.display_name.value.trim(),
        }),
      });
      setToken(data.access_token);
      form.reset();
      enterApp();
    } catch (err) {
      showError($("#gate-error"), err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Create account";
    }
  });

  $("#logout").addEventListener("click", signOut);

  // ── File selection ───────────────────────────────────────────────────
  const dropzone = $("#dropzone");
  const fileInput = $("#file-input");

  function pickFile(file) {
    if (!file) return;
    const MAX = 25 * 1024 * 1024;
    if (file.size > MAX) {
      showError($("#upload-error"), `That file is ${fmtBytes(file.size)}. The limit is 25 MB.`);
      return;
    }
    showError($("#upload-error"), "");
    state.file = file;

    $("#fp-name").textContent = `${file.name} · ${fmtBytes(file.size)}`;
    $("#file-preview").classList.remove("is-hidden");
    $("#upload-btn").disabled = false;

    const audio = $("#fp-audio");
    audio.src = URL.createObjectURL(file);
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => pickFile(fileInput.files[0]));

  ["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add("is-drag");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("is-drag");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f) pickFile(f);
  });

  $("#fp-clear").addEventListener("click", () => {
    state.file = null;
    fileInput.value = "";
    $("#file-preview").classList.add("is-hidden");
    $("#upload-btn").disabled = true;
    $("#fp-audio").removeAttribute("src");
  });

  // ── Upload ───────────────────────────────────────────────────────────
  $("#upload-btn").addEventListener("click", async () => {
    if (!state.file) return;
    const btn = $("#upload-btn");
    showError($("#upload-error"), "");
    btn.disabled = true;
    btn.textContent = "Uploading…";

    try {
      const fd = new FormData();
      fd.append("file", state.file);
      const lang = $("#lang-select").value;
      const qs = lang ? `?language=${encodeURIComponent(lang)}` : "";

      const row = await api(`/api/transcriptions${qs}`, { method: "POST", body: fd });

      state.file = null;
      fileInput.value = "";
      $("#file-preview").classList.add("is-hidden");
      $("#fp-audio").removeAttribute("src");

      toast("Queued. Transcribing now…");
      await loadHistory();
      startPolling();
      openDetail(row.id);
    } catch (err) {
      showError($("#upload-error"), err.message);
    } finally {
      btn.disabled = !state.file;
      btn.textContent = "Transcribe";
    }
  });

  // ── History ──────────────────────────────────────────────────────────
  async function loadHistory() {
    const box = $("#history");
    try {
      const data = await api("/api/transcriptions?limit=50");
      if (!data.items.length) {
        box.innerHTML = '<p class="empty">Nothing here yet. Upload something.</p>';
        return;
      }
      box.innerHTML = "";
      data.items.forEach((row) => box.appendChild(renderItem(row)));
    } catch (err) {
      box.innerHTML = `<p class="empty">${err.message}</p>`;
    }
  }

  function renderItem(row) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "item";
    el.dataset.id = row.id;

    const badge = document.createElement("span");
    badge.className = `badge badge-${row.status}`;
    badge.textContent = row.status;

    const body = document.createElement("div");
    body.className = "item-body";

    const name = document.createElement("div");
    name.className = "item-name";
    name.textContent = row.original_name;

    const snippet = document.createElement("div");
    snippet.className = "item-snippet";
    if (row.status === "completed") {
      snippet.textContent = row.text || "(no speech detected)";
    } else if (row.status === "failed") {
      snippet.textContent = row.error || "Transcription failed.";
    } else {
      snippet.textContent = "Working on it…";
    }

    const meta = document.createElement("div");
    meta.className = "item-meta";
    const bits = [fmtDate(row.created_at), fmtBytes(row.size_bytes)];
    if (row.duration_seconds) bits.push(fmtClock(row.duration_seconds));
    if (row.language) bits.push(row.language.toUpperCase());
    meta.textContent = bits.filter(Boolean).join(" · ");

    body.append(name, snippet, meta);

    if (row.status === "processing" || row.status === "queued") {
      const sp = document.createElement("div");
      sp.className = "spinner";
      el.append(sp, body);
    } else {
      el.append(badge, body);
    }

    el.addEventListener("click", () => openDetail(row.id));
    return el;
  }

  // ── Polling ──────────────────────────────────────────────────────────
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(async () => {
      try {
        const data = await api("/api/transcriptions?limit=50");
        const active = data.items.some(
          (r) => r.status === "queued" || r.status === "processing"
        );
        await loadHistory();
        if (state.openId) await refreshDrawer(state.openId);
        if (!active) {
          stopPolling();
          checkEngine();
        }
      } catch {
        stopPolling();
      }
    }, 2500);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  // ── Drawer ───────────────────────────────────────────────────────────
  const drawer = $("#drawer");

  function openDrawer() {
    drawer.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    drawer.hidden = true;
    document.body.style.overflow = "";
    state.openId = null;
  }

  drawer.querySelectorAll("[data-close]").forEach((el) =>
    el.addEventListener("click", closeDrawer)
  );
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !drawer.hidden) closeDrawer();
  });

  async function openDetail(id) {
    state.openId = id;
    openDrawer();
    $("#drawer-title").textContent = "Loading…";
    $("#drawer-meta").textContent = "";
    $("#drawer-body").innerHTML = "";
    await refreshDrawer(id);
  }

  async function refreshDrawer(id) {
    let row;
    try {
      row = await api(`/api/transcriptions/${id}`);
    } catch (err) {
      $("#drawer-title").textContent = "Not available";
      $("#drawer-body").innerHTML = `<p class="empty">${err.message}</p>`;
      return;
    }

    $("#drawer-title").textContent = row.original_name;

    const meta = [fmtDate(row.created_at), fmtBytes(row.size_bytes)];
    if (row.duration_seconds) meta.push(fmtClock(row.duration_seconds));
    if (row.language) {
      const p = row.language_probability
        ? ` (${Math.round(row.language_probability * 100)}%)`
        : "";
      meta.push(`${row.language.toUpperCase()}${p}`);
    }
    if (row.processing_ms) meta.push(`${(row.processing_ms / 1000).toFixed(1)}s`);
    $("#drawer-meta").textContent = meta.filter(Boolean).join(" · ");

    const body = $("#drawer-body");

    if (row.status === "queued" || row.status === "processing") {
      body.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;color:var(--text-dim);font-size:14px">
          <div class="spinner"></div>
          <span>Transcribing… this updates on its own.</span>
        </div>`;
      setDownloads(row.id, false);
      return;
    }

    if (row.status === "failed") {
      body.innerHTML = `<p class="error">${escapeHtml(row.error || "Transcription failed.")}</p>`;
      setDownloads(row.id, false);
      return;
    }

    setDownloads(row.id, true);

    if (!row.segments || !row.segments.length) {
      body.innerHTML = '<p class="empty">No speech was detected in this file.</p>';
      return;
    }

    body.innerHTML = "";
    row.segments.forEach((seg) => {
      const wrap = document.createElement("div");
      wrap.className = "seg";

      const time = document.createElement("div");
      time.className = "seg-time";
      time.textContent = fmtClock(seg.start);

      const text = document.createElement("div");
      text.className = "seg-text";
      text.textContent = seg.text;

      wrap.append(time, text);
      body.appendChild(wrap);
    });
  }

  function setDownloads(id, enabled) {
    ["txt", "srt", "vtt", "md"].forEach((fmt) => {
      const a = $(`#dl-${fmt}`);
      if (enabled) {
        a.href = `/api/transcriptions/${id}/export?fmt=${fmt}`;
        a.removeAttribute("aria-disabled");
        a.style.pointerEvents = "";
        a.style.opacity = "";
      } else {
        a.href = "#";
        a.setAttribute("aria-disabled", "true");
        a.style.pointerEvents = "none";
        a.style.opacity = ".4";
      }
    });
  }

  // Downloads need the bearer token, so fetch then save as a blob.
  ["txt", "srt", "vtt", "md"].forEach((fmt) => {
    $(`#dl-${fmt}`).addEventListener("click", async (e) => {
      e.preventDefault();
      if (!state.openId) return;
      try {
        const res = await fetch(
          `/api/transcriptions/${state.openId}/export?fmt=${fmt}`,
          { headers: { Authorization: `Bearer ${state.token}` } }
        );
        if (!res.ok) throw new Error(`Export failed (${res.status})`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `transcript.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
      } catch (err) {
        toast(err.message);
      }
    });
  });

  $("#copy-btn").addEventListener("click", async () => {
    if (!state.openId) return;
    try {
      const row = await api(`/api/transcriptions/${state.openId}`);
      await navigator.clipboard.writeText(row.text || "");
      toast("Copied to clipboard");
    } catch {
      toast("Could not copy");
    }
  });

  $("#delete-btn").addEventListener("click", async () => {
    if (!state.openId) return;
    if (!confirm("Delete this transcript and its audio file? This cannot be undone.")) return;
    try {
      await api(`/api/transcriptions/${state.openId}`, { method: "DELETE" });
      closeDrawer();
      await loadHistory();
      toast("Deleted");
    } catch (err) {
      toast(err.message);
    }
  });

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  $("#refresh").addEventListener("click", () => {
    loadHistory();
    checkEngine();
  });

  // ── Boot ─────────────────────────────────────────────────────────────
  (async function boot() {
    if (!state.token) return;
    try {
      await api("/api/auth/me");
      enterApp();
    } catch {
      signOut();
    }
  })();
})();
