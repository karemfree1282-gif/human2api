(() => {
  const state = {
    lang: "ar",
    theme: "dark",
    activeRunId: null,
    editorSteps: [
      { action: "goto", url: "/demo", selector: null },
      { action: "type", selector: "#customer-name", text: "${input:customer}", role: "textbox", name: "اسم العميل" },
      { action: "type", selector: "#invoice-amount", text: "${input:amount}", role: "textbox", name: "قيمة الفاتورة" },
      { action: "click", selector: "#submit-invoice-btn", role: "button", name: "إصدار الفاتورة" },
      { action: "assert_text", selector: "#invoice-result", expected: "${input:customer}", match: "contains" }
    ],
    editorInputs: {
      customer: { type: "string", required: true, sensitive: false, default: "شركة النور" },
      amount: { type: "string", required: true, sensitive: false, default: "450" }
    }
  };

  const i18n = {
    ar: {
      appTitle: "Human2API Studio",
      appSubtitle: "علّم الكمبيوتر أو المتصفح أو الهاتف مهمة مرة واحدة، وحوّلها إلى API وأداة MCP",
      recordNewTask: "تسجيل مهمة جديدة",
      tabDashboard: "لوحة التحكم (Dashboard)",
      tabEditor: "محرر المهام البصري (Workflow Editor)",
      tabSchedules: "المهام المجدولة (Schedules)",
      tabHistory: "سجل التشغيل (History)",
      tabMarketplace: "متجر الأدوات (Marketplace)",
      tabSettings: "الخصوصية والصلاحيات (Privacy & Security)"
    },
    en: {
      appTitle: "Human2API Studio",
      appSubtitle: "Teach your browser, desktop, or Android phone once — reuse via REST API & MCP",
      recordNewTask: "Record New Task",
      tabDashboard: "Dashboard",
      tabEditor: "Visual Workflow Editor",
      tabSchedules: "Scheduled Tasks",
      tabHistory: "Run History",
      tabMarketplace: "Marketplace",
      tabSettings: "Privacy & Permissions"
    }
  };

  async function apiCall(path, method = "GET", body = null) {
    const headers = {
      "X-H2A-Token": window.__H2A_TOKEN__ || "",
      "Content-Type": "application/json"
    };
    const opts = { method, headers };
    if (body !== null) opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    const data = await resp.json().catch(() => ({}));
    return { status: resp.status, data };
  }

  function renderEditorSteps() {
    const ul = document.getElementById("editor-steps-list");
    if (!ul) return;
    ul.innerHTML = "";
    state.editorSteps.forEach((st, idx) => {
      const li = document.createElement("li");
      const desc = `${idx + 1}. [${st.action}] ${st.selector || st.url || ""} ${st.text || st.expected || ""}`;
      const span = document.createElement("span");
      span.textContent = desc;
      const controls = document.createElement("div");

      const upBtn = document.createElement("button");
      upBtn.className = "btn btn-outline";
      upBtn.textContent = "↑";
      upBtn.onclick = () => {
        if (idx > 0) {
          const tmp = state.editorSteps[idx - 1];
          state.editorSteps[idx - 1] = state.editorSteps[idx];
          state.editorSteps[idx] = tmp;
          renderEditorSteps();
        }
      };

      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger";
      delBtn.textContent = "✕";
      delBtn.onclick = () => {
        if (state.editorSteps.length > 1) {
          state.editorSteps.splice(idx, 1);
          renderEditorSteps();
        }
      };

      controls.appendChild(upBtn);
      controls.appendChild(delBtn);
      li.appendChild(span);
      li.appendChild(controls);
      ul.appendChild(li);
    });
  }

  function renderEditorInputs() {
    const ul = document.getElementById("editor-inputs-list");
    if (!ul) return;
    ul.innerHTML = "";
    Object.entries(state.editorInputs).forEach(([k, spec]) => {
      const li = document.createElement("li");
      li.textContent = `${k} (${spec.type}) ${spec.sensitive ? "[SECRET]" : `= ${spec.default || ""}`}`;
      ul.appendChild(li);
    });
  }

  async function refreshDashboard() {
    const { status, data } = await apiCall("/api/v1/status");
    if (status === 200) {
      document.getElementById("stat-workflows-count").textContent = String(data.workflows_count || 0);
      document.getElementById("stat-schedules-count").textContent = String(data.schedules_count || 0);
      document.getElementById("stat-packages-count").textContent = String(data.installed_packages_count || 0);
      document.getElementById("stat-vault-state").textContent = data.vault_unlocked ? "مفتوحة (Unlocked)" : "مقفلة (Locked)";
    }
    const wfRes = await apiCall("/api/v1/workflows");
    const sel = document.getElementById("dashboard-workflow-select");
    if (sel && wfRes.status === 200) {
      sel.innerHTML = "";
      (wfRes.data.workflows || []).forEach(wf => {
        const opt = document.createElement("option");
        opt.value = wf.filename || wf.name;
        opt.textContent = `${wf.name} (${wf.target})`;
        sel.appendChild(opt);
      });
    }
  }

  async function refreshHistory() {
    const { status, data } = await apiCall("/api/v1/history");
    const ul = document.getElementById("history-list");
    if (!ul || status !== 200) return;
    ul.innerHTML = "";
    (data.history || []).forEach(h => {
      const li = document.createElement("li");
      li.textContent = `${h.workflow_name} [${h.target}] — ${h.status.toUpperCase()} (${h.duration_ms} ms) ${h.error ? " | سبب الخطأ: " + h.error : ""}`;
      ul.appendChild(li);
    });
  }

  async function refreshSchedules() {
    const { status, data } = await apiCall("/api/v1/schedules");
    const ul = document.getElementById("schedules-list");
    if (!ul || status !== 200) return;
    ul.innerHTML = "";
    (data.schedules || []).forEach(job => {
      const li = document.createElement("li");
      const span = document.createElement("span");
      span.textContent = `${job.workflow_name} — كل ${job.interval_seconds} ثانية (${job.enabled ? "نشط" : "متوقف"})`;
      const del = document.createElement("button");
      del.className = "btn btn-danger";
      del.textContent = "حذف";
      del.onclick = async () => {
        await apiCall(`/api/v1/schedules/${job.job_id}`, "DELETE");
        refreshSchedules();
        refreshDashboard();
      };
      li.appendChild(span);
      li.appendChild(del);
      ul.appendChild(li);
    });
  }

  async function refreshMarketplace() {
    const q = (document.getElementById("mp-search-input")?.value || "").trim();
    const { status, data } = await apiCall(`/api/v1/marketplace/packages?q=${encodeURIComponent(q)}`);
    const ul = document.getElementById("marketplace-catalog-list");
    if (ul && status === 200) {
      ul.innerHTML = "";
      (data.packages || []).forEach(pkg => {
        const li = document.createElement("li");
        const span = document.createElement("span");
        span.textContent = `${pkg.tool_id}@${pkg.version} [${pkg.target}] ★${pkg.avg_rating} — الناشر: ${pkg.publisher_id}`;
        const instBtn = document.createElement("button");
        instBtn.className = "btn btn-primary";
        instBtn.textContent = "تثبيت موثق";
        instBtn.onclick = async () => {
          await apiCall("/api/v1/marketplace/install", "POST", { tool_id: pkg.tool_id, version: pkg.version, allowPrivilegeExpansion: true });
          refreshMarketplace();
          refreshDashboard();
        };
        li.appendChild(span);
        li.appendChild(instBtn);
        ul.appendChild(li);
      });
    }
    const instRes = await apiCall("/api/v1/marketplace/installed");
    const instUl = document.getElementById("marketplace-installed-list");
    if (instUl && instRes.status === 200) {
      instUl.innerHTML = "";
      (instRes.data.installed || []).forEach(item => {
        const li = document.createElement("li");
        li.textContent = `${item.tool_id}@${item.version} (SHA256: ${String(item.workflow_sha256).slice(0, 12)}...)`;
        instUl.appendChild(li);
      });
    }
  }

  // Wire up navigation tabs
  document.querySelectorAll(".nav-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.getAttribute("data-tab");
      document.getElementById(`panel-${tab}`)?.classList.add("active");
    });
  });

  // Theme & Language toggles
  document.getElementById("btn-toggle-theme")?.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
  });

  document.getElementById("btn-toggle-lang")?.addEventListener("click", () => {
    state.lang = state.lang === "ar" ? "en" : "ar";
    document.documentElement.setAttribute("lang", state.lang);
    document.documentElement.setAttribute("dir", state.lang === "ar" ? "rtl" : "ltr");
    const dict = i18n[state.lang];
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const k = el.getAttribute("data-i18n");
      if (dict[k]) el.textContent = dict[k];
    });
  });

  // Record Modal
  document.getElementById("btn-record-new")?.addEventListener("click", () => {
    document.getElementById("record-modal")?.classList.remove("hidden");
  });
  document.getElementById("btn-close-record-modal")?.addEventListener("click", () => {
    document.getElementById("record-modal")?.classList.add("hidden");
  });
  document.getElementById("btn-confirm-record")?.addEventListener("click", async () => {
    const name = document.getElementById("rec-task-name").value || "Recorded Workflow";
    const target = document.getElementById("rec-task-target").value || "browser";
    const res = await apiCall("/api/v1/record/compile", "POST", {
      name,
      target,
      save: true,
      events: [
        { action: "goto", url: window.location.origin + "/demo" },
        { action: "type", id: "customer-name", name_attr: "customer_name", value: "عميل مسجل" },
        { action: "type", id: "api-password", name_attr: "api_password", input_type: "password", is_password: true, value: "SuperSecret" },
        { action: "click", id: "submit-invoice-btn", accessible_name: "إصدار الفاتورة" }
      ]
    });
    document.getElementById("record-modal")?.classList.add("hidden");
    if (res.status === 201) {
      document.getElementById("live-status-text").textContent = `تم تسجيل وحفظ المهمة بنجاح: ${res.data.workflow.name}`;
      await refreshDashboard();
    }
  });

  // Editor actions
  document.getElementById("btn-add-step")?.addEventListener("click", () => {
    const action = document.getElementById("new-step-action").value;
    const selOrUrl = document.getElementById("new-step-selector").value.trim();
    const val = document.getElementById("new-step-value").value.trim();
    const step = { action };
    if (action === "goto") step.url = selOrUrl || "/demo";
    else step.selector = selOrUrl || "#submit-invoice-btn";
    if (action === "assert_text") step.expected = val || "تم";
    else if (val) step.text = val;
    state.editorSteps.push(step);
    renderEditorSteps();
  });

  document.getElementById("btn-add-input")?.addEventListener("click", () => {
    const name = document.getElementById("new-input-name").value.trim();
    const type = document.getElementById("new-input-type").value;
    const def = document.getElementById("new-input-default").value;
    if (!name) return;
    state.editorInputs[name] = {
      type,
      required: true,
      sensitive: type === "secret",
      default: type === "secret" ? null : def
    };
    renderEditorInputs();
  });

  document.getElementById("btn-save-workflow")?.addEventListener("click", async () => {
    const name = document.getElementById("wf-name-input").value.trim() || "مهمة جديدة";
    const target = document.getElementById("wf-target-select").value;
    const hosts = document.getElementById("wf-hosts-input").value.split(",").map(s => s.trim()).filter(Boolean);
    const res = await apiCall("/api/v1/workflows", "POST", {
      name,
      target,
      mode: "write",
      allowedHosts: hosts,
      inputs: state.editorInputs,
      steps: state.editorSteps
    });
    if (res.status === 201) {
      document.getElementById("live-status-text").textContent = `تم حفظ المهمة ${name} بنجاح.`;
      await refreshDashboard();
    }
  });

  // Run & Stop
  document.getElementById("btn-run-selected")?.addEventListener("click", async () => {
    const sel = document.getElementById("dashboard-workflow-select");
    const wfName = sel?.value;
    if (!wfName) return;
    const allowWrite = document.getElementById("chk-allow-write").checked;
    document.getElementById("live-status-text").textContent = "جاري تشغيل المهمة...";
    const res = await apiCall("/api/v1/run", "POST", { workflowName: wfName, allowWrite });
    state.activeRunId = res.data.run_id || null;
    if (res.data.report) {
      const rep = res.data.report;
      document.getElementById("live-status-text").textContent =
        rep.status === "passed"
          ? `اكتملت المهمة بنجاح (${rep.steps.length} خطوات، ${rep.assertions_passed} تحققات)`
          : `توقفت المهمة (${rep.status}): ${rep.error || ""}`;
      await refreshHistory();
    }
  });

  document.getElementById("btn-stop-run")?.addEventListener("click", async () => {
    if (state.activeRunId) {
      await apiCall(`/api/v1/runs/${state.activeRunId}/cancel`, "POST", {});
    }
    document.getElementById("live-status-text").textContent = "تم إرسال إشارة الإيقاف الفوري.";
  });

  // Schedules, History, Marketplace, Settings
  document.getElementById("btn-create-schedule")?.addEventListener("click", async () => {
    const wfName = document.getElementById("sched-wf-name").value.trim() || "Scheduled Task";
    const interval = parseInt(document.getElementById("sched-interval").value || "60", 10);
    await apiCall("/api/v1/schedules", "POST", {
      workflowPath: `workflows/${wfName}.json`,
      workflowName: wfName,
      intervalSeconds: interval
    });
    await refreshSchedules();
    await refreshDashboard();
  });

  document.getElementById("btn-refresh-history")?.addEventListener("click", refreshHistory);
  document.getElementById("btn-mp-search")?.addEventListener("click", refreshMarketplace);

  document.getElementById("btn-vault-unlock")?.addEventListener("click", async () => {
    const passphrase = document.getElementById("vault-passphrase").value || "default-pass";
    await apiCall("/api/v1/vault/unlock", "POST", { passphrase });
    await refreshDashboard();
  });

  document.getElementById("btn-vault-lock")?.addEventListener("click", async () => {
    await apiCall("/api/v1/vault/lock", "POST", {});
    await refreshDashboard();
  });

  document.getElementById("btn-save-secret")?.addEventListener("click", async () => {
    const name = document.getElementById("secret-key-input").value.trim();
    const value = document.getElementById("secret-val-input").value;
    if (name && value) {
      await apiCall("/api/v1/vault/secrets", "POST", { name, value });
      document.getElementById("secret-val-input").value = "";
    }
  });

  document.getElementById("btn-save-settings")?.addEventListener("click", async () => {
    const aiHealingConsent = document.getElementById("chk-ai-healing-consent").checked;
    const networkPolicy = document.getElementById("sel-network-policy").value;
    await apiCall("/api/v1/settings", "POST", { aiHealingConsent, networkPolicy });
  });

  renderEditorSteps();
  renderEditorInputs();
  refreshDashboard();
  refreshSchedules();
  refreshHistory();
  refreshMarketplace();
})();
