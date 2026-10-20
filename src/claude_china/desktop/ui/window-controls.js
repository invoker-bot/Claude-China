let windowActionPending = false;
let windowStateTimer;

function renderWindowState(state) {
  document.body.classList.toggle("custom-titlebar", !!state.custom_titlebar);
  document.body.classList.toggle("is-maximized", !!state.maximized);
  document.getElementById("window-controls").hidden = !state.custom_titlebar;
  const button = document.getElementById("window-maximize");
  button.setAttribute("aria-label", state.maximized ? "还原" : "最大化");
  button.title = state.maximized ? "还原" : "最大化";
  button.innerHTML = icon(state.maximized ? "restore" : "maximize");
}

async function windowAction(action) {
  if (windowActionPending) return;
  windowActionPending = true;
  try {
    const result = await api().window_action(action);
    if (result.ok) renderWindowState(result);
    else toast("暂时无法操作窗口，请重试。");
  } catch (_) { toast("暂时无法操作窗口，请重试。"); }
  finally { windowActionPending = false; }
}

async function initWindowControls() {
  if (!api().get_window_state) return;
  const state = await api().get_window_state();
  renderWindowState(state);
  if (!state.custom_titlebar) return;
  document.querySelectorAll("[data-window-action]").forEach(button => {
    button.onclick = () => windowAction(button.dataset.windowAction);
  });
  const header = document.getElementById("app-header");
  header.ondblclick = event => {
    if (!event.target.closest("button, nav")) windowAction("maximize");
  };
  // Use logical-coordinate deltas and serialize moves. A click must never move
  // an inset/DPI-scaled window or it can no longer recognize a double click.
  let drag;
  async function moveDrag(session) {
    if (session.moving) return;
    session.moving = true;
    try {
      while (session.dirty) {
        session.dirty = false;
        const first = session.first;
        session.first = false;
        await api().move_window(session.dx, session.dy, first);
      }
    } catch (_) { /* A closing window can interrupt a drag. */ }
    finally { session.moving = false; }
  }
  header.onpointerdown = event => {
    if (event.button === 0 && !event.target.closest("button, nav") && !document.body.classList.contains("is-maximized")) {
      drag = { x: event.screenX, y: event.screenY, first: true, moving: false, dirty: false };
      header.setPointerCapture(event.pointerId);
    }
  };
  header.onpointermove = event => {
    if (!drag || !(event.buttons & 1)) return;
    drag.dx = event.screenX - drag.x;
    drag.dy = event.screenY - drag.y;
    if (drag.first && Math.hypot(drag.dx, drag.dy) < 4) return;
    drag.dirty = true;
    moveDrag(drag);
  };
  header.onpointerup = header.onpointercancel = () => { drag = null; };
  // Windows has a native sizing inset; GTK uses its native resize-drag API.
  const edges = window.pywebview.platform === "edgechromium" ? [] : ["n", "s", "w", "e", "nw", "ne", "sw", "se"];
  for (const edge of edges) {
    const grip = document.createElement("div");
    grip.className = `window-resize window-resize--${edge}`;
    grip.setAttribute("aria-hidden", "true");
    grip.onpointerdown = event => {
      if (event.button !== 0 || !api().begin_window_resize) return;
      event.preventDefault();
      api().begin_window_resize(edge).catch(() => {});
    };
    document.body.appendChild(grip);
  }
  const refreshWindowState = () => {
    clearTimeout(windowStateTimer);
    windowStateTimer = setTimeout(async () => {
      try { renderWindowState(await api().get_window_state()); } catch (_) { /* Window may be closing. */ }
    }, 120);
  };
  window.addEventListener("resize", refreshWindowState);
  window.addEventListener("focus", refreshWindowState);
}
