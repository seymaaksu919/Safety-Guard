const API = "/api/dashboard/users";
const PPE_STREAM = "/api/ppe/stream";
const POLL_MS = 5000;

const els = {
  loading: document.getElementById("loading"),
  error: document.getElementById("error"),
  userList: document.getElementById("userList"),
  setupHint: document.getElementById("setupHint"),
  liveStatus: document.getElementById("liveStatus"),
  dashboardPanel: document.getElementById("dashboardPanel"),
  statActive: document.getElementById("statActive"),
  statActiveSub: document.getElementById("statActiveSub"),
  statActiveHint: document.getElementById("statActiveHint"),
  statRisky: document.getElementById("statRisky"),
  statPpe: document.getElementById("statPpe"),
  statPpeHint: document.getElementById("statPpeHint"),
  statPpeCard: document.getElementById("statPpeCard"),
  ppePanel: document.getElementById("ppePanel"),
  ppeBackBtn: document.getElementById("ppeBackBtn"),
  ppeCamera: document.getElementById("ppeCamera"),
  ppeCameraStatus: document.getElementById("ppeCameraStatus"),
  ppeSummary: document.getElementById("ppeSummary"),
  ppeStatusGrid: document.getElementById("ppeStatusGrid"),
};

const chartStore = new Map();
let currentView = "dashboard";
let lastStats = null;

function statusClass(status) {
  const s = (status || "SAFE").toUpperCase();
  if (s === "WARNING") return "warn";
  if (s === "CRITICAL" || s === "FIRE DETECTED") return "crit";
  return "safe";
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("tr-TR");
  } catch {
    return iso;
  }
}

function fmtChartLabel(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function metric(label, value, unit = "") {
  return `
    <div class="metric">
      <label>${label}</label>
      <span class="metric-value">${value}${unit}</span>
    </div>`;
}

function displayName(user) {
  const name = (user.display_name || "").trim();
  if (name && !name.toLowerCase().startsWith("kayitli kullanici")) {
    return name;
  }
  const email = (user.email || "").trim();
  if (email) return email.split("@")[0];
  return "İsimsiz hesap";
}

function initials(name) {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** API history veya son sensör okumasından grafik verisi */
function chartHistory(user) {
  const h = user.history || [];
  if (h.length) return h;
  const s = user.sensor;
  if (!s) return [];
  return [
    {
      created_at: s.created_at,
      heart_rate: Number(s.heart_rate) || 0,
      body_temp: Number(s.body_temp) || 0,
      ambient_temp: Number(s.ambient_temp) || 0,
      humidity: Number(s.humidity) || 0,
      gas_percent: Number(s.gas_percent ?? s.gas_level ?? 0),
      gas_percent2: Number(s.gas_percent2 ?? s.gas_level2 ?? 0),
    },
  ];
}

function renderUserCard(user) {
  const title = escapeHtml(displayName(user));
  const email = (user.email || "").trim();
  const uid = escapeHtml(user.user_id || "");
  const has = user.has_sensor_data && user.sensor;
  const s = user.sensor || {};
  const history = chartHistory(user);
  const histLen = history.length;

  let body = "";
  if (has) {
    const status = s.status || "SAFE";
    const flame = s.flame === true || s.flame === "true";
    body = `
      <div class="fire ${flame ? "alert" : "ok"}">
        ${flame ? "⚠ Yangın / alev algılandı" : "✓ Yangın riski yok"}
      </div>
      <div class="status-bar ${statusClass(status)}">DURUM: ${status}</div>
      <div class="metrics">
        ${metric("Nabız", Math.round(Number(s.heart_rate) || 0), " BPM")}
        ${metric("Vücut", Number(s.body_temp || 0).toFixed(1), " °C")}
        ${metric("Ortam", Number(s.ambient_temp || 0).toFixed(1), " °C")}
        ${metric("Nem", Math.round(Number(s.humidity) || 0), " %")}
        ${metric("Hava", Number(s.gas_percent ?? s.gas_level ?? 0).toFixed(1), " %")}
        ${metric("Gaz", Number(s.gas_percent2 ?? s.gas_level2 ?? 0).toFixed(1), " %")}
      </div>
      <p class="chart-title">Sensör grafiği (${histLen} ölçüm)</p>
      <div class="chart-panel">
        <canvas class="sensor-chart" data-user-id="${uid}" width="800" height="280" aria-label="${title} sensör grafiği"></canvas>
      </div>
      <p class="update-time">Son ölçüm: ${fmtTime(s.created_at)}</p>`;
  } else {
    body = `
      <p class="no-data">Henüz sensör verisi yok — ESP32 bağlandığında grafik burada görünür.</p>
      <div class="chart-panel chart-panel-empty">
        <p class="chart-empty-msg">Veri bekleniyor</p>
      </div>`;
  }

  return `
    <article class="user-card" data-user-id="${uid}">
      <header class="user-card-head">
        <span class="avatar">${escapeHtml(initials(displayName(user)))}</span>
        <div class="user-info">
          <h2>${title}</h2>
          ${email ? `<p>${escapeHtml(email)}</p>` : ""}
        </div>
        <span class="badge ${has ? "badge-on" : "badge-off"}">${has ? "Aktif" : "Pasif"}</span>
      </header>
      <div class="user-body">${body}</div>
    </article>`;
}

function destroyCharts() {
  chartStore.forEach((chart) => chart.destroy());
  chartStore.clear();
}

function buildChartForUser(user) {
  if (typeof Chart === "undefined") return;

  const uid = user.user_id;
  const history = chartHistory(user);
  if (!history.length) return;

  const canvas = els.userList.querySelector(
    `canvas.sensor-chart[data-user-id="${CSS.escape(uid)}"]`
  );
  if (!canvas) return;

  const labels = history.map((p) => fmtChartLabel(p.created_at));
  const datasets = [
    {
      label: "Nabız",
      data: history.map((p) => Number(p.heart_rate) || 0),
      borderColor: "#e53935",
      backgroundColor: "rgba(229, 57, 53, 0.12)",
      tension: 0.35,
      fill: true,
      pointRadius: history.length < 3 ? 5 : 2,
      yAxisID: "y",
    },
    {
      label: "Vücut °C",
      data: history.map((p) => Number(p.body_temp) || 0),
      borderColor: "#fb8c00",
      tension: 0.35,
      pointRadius: history.length < 3 ? 5 : 2,
      yAxisID: "y1",
    },
    {
      label: "Ortam °C",
      data: history.map((p) => Number(p.ambient_temp) || 0),
      borderColor: "#1e88e5",
      tension: 0.35,
      pointRadius: history.length < 3 ? 5 : 2,
      yAxisID: "y1",
    },
    {
      label: "Hava %",
      data: history.map((p) => Number(p.gas_percent) || 0),
      borderColor: "#43a047",
      tension: 0.35,
      pointRadius: history.length < 3 ? 5 : 2,
      yAxisID: "y2",
    },
  ];

  const existing = chartStore.get(uid);
  if (existing) {
    existing.data.labels = labels;
    existing.data.datasets.forEach((ds, i) => {
      ds.data = datasets[i].data;
      ds.pointRadius = history.length < 3 ? 5 : 2;
    });
    existing.update("none");
    existing.resize();
    return;
  }

  const chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 12, padding: 14, color: "#334155" },
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 10, color: "#64748b", font: { size: 11 } },
          grid: { color: "#e2e8f0" },
        },
        y: {
          type: "linear",
          position: "left",
          title: { display: true, text: "BPM", color: "#64748b" },
          ticks: { color: "#64748b" },
          grid: { color: "#e2e8f0" },
        },
        y1: {
          type: "linear",
          position: "right",
          grid: { drawOnChartArea: false },
          title: { display: true, text: "°C", color: "#64748b" },
          ticks: { color: "#64748b" },
        },
        y2: {
          type: "linear",
          position: "right",
          offset: true,
          grid: { drawOnChartArea: false },
          min: 0,
          max: 100,
          title: { display: true, text: "%", color: "#64748b" },
          ticks: { color: "#64748b" },
        },
      },
    },
  });
  chartStore.set(uid, chart);
}

function buildAllCharts(users) {
  users
    .filter((u) => u.has_sensor_data && chartHistory(u).length > 0)
    .forEach((u) => buildChartForUser(u));
}

function renderStats(stats) {
  lastStats = stats;
  const active = stats?.active_workers;
  const total = stats?.registered_users;

  if (active === undefined || active === null) {
    els.statActive.textContent = "—";
    if (els.statActiveSub) els.statActiveSub.textContent = "";
  } else {
    els.statActive.textContent = String(active);
    if (els.statActiveSub) {
      els.statActiveSub.textContent =
        total != null ? ` / ${total} kayıtlı` : "";
    }
    if (els.statActiveHint) {
      els.statActiveHint.textContent =
        total != null
          ? `${active} kullanıcı sensör gönderiyor (toplam ${total} kayıtlı)`
          : "Sensör verisi gönderen kullanıcı";
    }
  }

  els.statRisky.textContent = String(stats?.risky_count ?? "—");

  if (els.statPpe) {
    if (stats?.ppe_online) {
      const n = stats.ppe_violations ?? 0;
      els.statPpe.textContent = n > 0 ? `${n} uyarı` : "Canlı";
      if (els.statPpeHint) {
        els.statPpeHint.textContent = "Ortam izleme — tıklayın";
      }
    } else {
      els.statPpe.textContent = "Kapalı";
      if (els.statPpeHint) {
        els.statPpeHint.textContent = "run_ppe_flask.py gerekli";
      }
    }
  }

  if (currentView === "ppe") {
    renderPpePanel(stats);
  }
}

function ppeItemCard(title, icon, stateClass, value, sub) {
  return `
    <div class="ppe-item-card ppe-item-${stateClass}">
      <span class="ppe-item-icon">${icon}</span>
      <div class="ppe-item-body">
        <span class="ppe-item-title">${escapeHtml(title)}</span>
        <span class="ppe-item-value">${escapeHtml(value)}</span>
        ${sub ? `<span class="ppe-item-sub">${escapeHtml(sub)}</span>` : ""}
      </div>
    </div>`;
}

function renderPpePanel(stats) {
  if (!els.ppePanel) return;

  const online = Boolean(stats?.ppe_online);
  const p = stats?.ppe || {};
  const person = Boolean(p.person_detected);
  const summary = stats?.ppe_summary || "";

  if (els.ppeSummary) {
    els.ppeSummary.textContent = summary;
  }

  if (els.ppeCameraStatus) {
    els.ppeCameraStatus.textContent = online
      ? summary || "YOLO işaretlemeli canlı görüntü"
      : "Kamera kapalı — python run_ppe_flask.py çalıştırın (port 5002)";
  }

  if (els.ppeCamera) {
    if (online && currentView === "ppe") {
      if (!els.ppeCamera.getAttribute("src")) {
        els.ppeCamera.src = `${PPE_STREAM}?_=${Date.now()}`;
      }
      els.ppeCamera.classList.remove("offline");
    } else if (!online) {
      els.ppeCamera.removeAttribute("src");
      els.ppeCamera.classList.add("offline");
    }
  }

  if (!els.ppeStatusGrid) return;

  if (!online) {
    els.ppeStatusGrid.innerHTML = ppeItemCard(
      "Kamera",
      "📷",
      "offline",
      "Bağlantı yok",
      "Port 5002"
    );
    return;
  }

  const items = [
    ppeItemCard(
      "İşçi algılama",
      "👷",
      person ? "ok" : "waiting",
      person ? "Kişi kamerada" : "Kişi yok",
      person ? "Sahne izleniyor" : "Ortam boş"
    ),
    ppeItemCard(
      "Kask",
      "⛑️",
      !person ? "waiting" : p.hardhat_warning ? "bad" : "ok",
      !person
        ? "Kontrol bekleniyor"
        : p.hardhat_warning
          ? "Eksik / uyarı"
          : "Tamam",
      !person ? "" : p.hardhat_warning ? "Baret takılmalı" : "Tespit edildi"
    ),
    ppeItemCard(
      "Yelek",
      "🦺",
      !person ? "waiting" : p.safety_vest_warning ? "bad" : "ok",
      !person
        ? "Kontrol bekleniyor"
        : p.safety_vest_warning
          ? "Eksik / uyarı"
          : "Tamam",
      !person ? "" : p.safety_vest_warning ? "Yelek takılmalı" : "Tespit edildi"
    ),
    ppeItemCard(
      "Maske",
      "😷",
      !person ? "waiting" : p.mask_warning ? "bad" : "ok",
      !person
        ? "Kontrol bekleniyor"
        : p.mask_warning
          ? "Eksik / uyarı"
          : "Tamam",
      !person ? "" : p.mask_warning ? "Maske takılmalı" : "Tespit edildi"
    ),
  ];

  els.ppeStatusGrid.innerHTML = items.join("");
}

function showPpeView() {
  currentView = "ppe";
  if (els.dashboardPanel) {
    els.dashboardPanel.classList.add("hidden");
  }
  if (els.ppePanel) {
    els.ppePanel.classList.remove("hidden");
  }
  if (els.ppeCamera) {
    els.ppeCamera.removeAttribute("src");
  }
  renderPpePanel(lastStats);
}

function showDashboardView() {
  currentView = "dashboard";
  if (els.ppePanel) {
    els.ppePanel.classList.add("hidden");
  }
  if (els.dashboardPanel) {
    els.dashboardPanel.classList.remove("hidden");
  }
  if (els.ppeCamera) {
    els.ppeCamera.removeAttribute("src");
    els.ppeCamera.classList.add("offline");
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadUsers(silent = false) {
  els.error.classList.add("hidden");

  if (!silent) {
    els.loading.classList.remove("hidden");
  }

  try {
    const res = await fetch(API, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const users = data.users || [];
    renderStats(data.stats || null);

    if (els.liveStatus) {
      const chartOk = typeof Chart !== "undefined";
      els.liveStatus.textContent =
        "Canlı güncelleme: " +
        new Date().toLocaleTimeString("tr-TR") +
        ` (${POLL_MS / 1000} sn)` +
        (chartOk ? "" : " — Chart.js yüklenemedi, sayfayı yenileyin");
    }

    if (data.setup_hint) {
      els.setupHint.textContent = data.setup_hint;
      els.setupHint.classList.remove("hidden");
    } else {
      els.setupHint.classList.add("hidden");
    }

    destroyCharts();
    els.userList.innerHTML = users.length
      ? users.map(renderUserCard).join("")
      : '<p class="empty-msg">Kayıtlı kullanıcı bulunamadı.</p>';

    requestAnimationFrame(() => {
      requestAnimationFrame(() => buildAllCharts(users));
    });

    els.loading.classList.add("hidden");
  } catch (e) {
    els.loading.classList.add("hidden");
    renderStats(null);
    els.error.classList.remove("hidden");
    els.error.innerHTML =
      `<strong>Bağlantı hatası</strong><br><br>` +
      `<code>python dashboard_api.py</code> çalışıyor olmalı (port 5003).<br><br>` +
      escapeHtml(String(e.message || e));
  }
}

function startClock() {
  const timeEl = document.getElementById("liveClock");
  const dateEl = document.getElementById("liveDate");
  if (!timeEl || !dateEl) return;

  function tick() {
    const now = new Date();
    timeEl.textContent = now.toLocaleTimeString("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    dateEl.textContent = now.toLocaleDateString("tr-TR", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  }

  tick();
  setInterval(tick, 1000);
}

if (els.statPpeCard) {
  els.statPpeCard.addEventListener("click", showPpeView);
  els.statPpeCard.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      showPpeView();
    }
  });
}

if (els.ppeBackBtn) {
  els.ppeBackBtn.addEventListener("click", showDashboardView);
}

if (els.ppeCamera) {
  els.ppeCamera.addEventListener("error", () => {
    if (currentView !== "ppe") return;
    if (els.ppeCameraStatus) {
      els.ppeCameraStatus.textContent =
        "Görüntü alınamadı — run_ppe_flask.py çalışıyor mu?";
    }
    els.ppeCamera.classList.add("offline");
  });
}

startClock();
loadUsers();
setInterval(() => loadUsers(true), POLL_MS);
