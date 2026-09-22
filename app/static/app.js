/* AI Engineering OS — web app client */
const $ = (s) => document.querySelector(s);
let project = null;
let tree = [];
let poll = null;
let pendingCopy = null;
let currentLang = "english";

function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 4200);
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

/* ---------- projects ---------- */
async function loadProjects() {
  try {
    const { projects } = await api("/api/projects");
    const ul = $("#project-list");
    ul.innerHTML = "";
    if (!projects.length) {
      ul.innerHTML = `<li class="muted">Add a project using +</li>`;
      return;
    }
    projects.forEach((p) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="dot"></span>${escape(p.name)} <span class="muted">${shortPath(
        p.path
      )}</span>`;
      li.title = p.path;
      if (project && p.path === project.path) li.classList.add("active");
      li.onclick = () => selectProject(p.path, p.name);
      ul.appendChild(li);
    });
  } catch (e) {
    console.error(e);
  }
}

function shortPath(p) {
  const parts = p.replace(/\\/g, "/").split("/");
  return parts.slice(-2).join("/") + (parts.length > 2 ? "..." : "");
}

function escape(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function selectProject(path, name) {
  try {
    const r = await api("/api/project/select", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    project = r.project;
    renderTree(path);
    loadProjects();
    $("#chat-input").focus();
    toast(`Project open: ${project.name}`);
  } catch (e) {
    toast(e.message, true);
  }
}

function askPath() {
  const p = prompt("Paste the full project folder path:", "C:\\Users\\Aum\\Documents\\Default Project\\unit-converter");
  if (p) selectProject(p.trim(), null);
}

/* ---------- file tree ---------- */
async function renderTree(path) {
  try {
    const r = await api(`/api/project/tree?path=${encodeURIComponent(path)}`);
    tree = r.tree || [];
    const el = $("#file-tree");
    el.innerHTML = "";
    if (!tree.length) {
      el.innerHTML = `<div class="muted">empty folder</div>`;
      return;
    }
    el.appendChild(renderNodes(tree));
  } catch (e) {
    $("#file-tree").innerHTML = `<div class="muted">${escape(e.message)}</div>`;
  }
}

function renderNodes(list) {
  const frag = document.createDocumentFragment();
  list.forEach((node) => {
    if (node.is_dir) {
      const det = document.createElement("details");
      det.open = false;
      const sum = document.createElement("summary");
      sum.textContent = node.name;
      det.appendChild(sum);
      det.appendChild(renderNodes(node.children || []));
      frag.appendChild(det);
    } else {
      const div = document.createElement("div");
      div.className = "file";
      div.textContent = node.name;
      div.title = node.path + (node.size ? `  (${fmtSize(node.size)})` : "");
      div.onclick = () => openFile(node.path, div);
      frag.appendChild(div);
    }
  });
  return frag;
}

function fmtSize(b) {
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}

async function openFile(path, el) {
  try {
    const r = await api(`/api/project/file?path=${encodeURIComponent(path)}`);
    let panel = $("#file-view");
    if (!panel) {
      panel = document.createElement("section");
      panel.id = "file-view";
      panel.className = "card";
      $("#main").appendChild(panel);
    }
    panel.classList.remove("hidden");
    panel.innerHTML = `<button class="close" onclick="document.getElementById('file-view').classList.add('hidden')">&times;</button>
      <h3>${escape(path.split("/").pop())} <span class="muted" style="font-weight:400;font-size:11px">${escape(
      shortPath(path)
    )}</span></h3>
      <div class="diff">${escape(r.content)}</div>`;
    panel.scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- primer ---------- */
async function showPrimer() {
  try {
    const { primer } = await api("/api/primer");
    const p = primer || {};
    let html = "";
    if (p.last_decision?.length)
      html += `<span class="k">Last decision</span><div>${escape(p.last_decision[0].text)}</div>`;
    if (p.recent_lessons?.length) {
      html += `<span class="k">Recent lessons</span><ul>`;
      p.recent_lessons.forEach((l) => (html += `<li>${escape(l.text)}</li>`));
      html += `</ul>`;
    }
    if (p.open_plans?.length) {
      html += `<span class="k">Open plans</span><ul>`;
      p.open_plans.forEach((o) => (html += `<li>${escape(o.id)} — ${o.remaining} task(s) left</li>`));
      html += `</ul>`;
    }
    if (p.eval)
      html += `<span class="k">Eval</span><div>${p.eval.total_runs || 0} runs · pass ${
        p.eval.pass_rate ?? "?"
      } · $${p.eval.total_cost_usd ?? "0.00"}</div>`;
    $("#primer-body").innerHTML = html || `<div class="muted">memory is empty</div>`;
    $("#primer-panel").classList.remove("hidden");
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- chat / run ---------- */
function addMsg(cls, html) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.innerHTML = html;
  $("#chat-log").appendChild(d);
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  return d;
}

async function runJob(instruction, apply, actLabel) {
  if (!project) {
    toast("Select a project first (+)", true);
    return;
  }
  const send = $("#chat-send");
  send.disabled = true;
  addMsg("me", escape(instruction));
  const busy = addMsg(
    "busy",
    `🧠 ${escape(actLabel)} in progress… (plan → worker → test → diff)`
  );
  try {
    const r = await api("/api/agent/run", {
      method: "POST",
      body: JSON.stringify({ project: project.path, instruction, apply }),
    });
    currentLang = r.lang || "english";
    busy.remove();
    $("#job-panel").classList.remove("hidden");
    $("#job-title").textContent = `Agent — ${project.name}`;
    $("#job-events").innerHTML = "";
    $("#job-result").innerHTML = "";
    poll = r.job_id;
    tick(r.job_id, instruction, apply, actLabel);
  } catch (e) {
    busy.remove();
    addMsg("sys", "⚠ " + escape(e.message));
    send.disabled = false;
  }
}

async function tick(jobId, instruction, apply, actLabel) {
  try {
    const st = await api(`/api/agent/status?job_id=${jobId}`);
    $("#job-stage").textContent = st.stage || "…";
    const ul = $("#job-events");
    ul.innerHTML = "";
    (st.events || []).forEach((e) => {
      const li = document.createElement("li");
      if (e.stage === "error") li.classList.add("error");
      if (e.stage === "done") li.classList.add("ok");
      li.innerHTML = `<span class="t">${e.t}</span><span class="stage">${escape(
        e.stage
      )}</span>${escape(e.msg)}`;
      ul.appendChild(li);
    });
    ul.scrollTop = ul.scrollHeight;
    if (st.done) {
      clearInterval(poll);
      $("#chat-send").disabled = false;
      finishJob(st, instruction, apply, actLabel);
    }
  } catch (e) {
    clearInterval(poll);
    $("#chat-send").disabled = false;
    addMsg("sys", "⚠ " + escape(e.message));
  }
}

function finishJob(st, instruction, apply, actLabel) {
  const r = st.result;
  if (st.error || !r) {
    addMsg("sys", "⚠ job fail: " + escape(st.error || "koi result nahi"));
    return;
  }
  pendingCopy = r.copy_dir || null;
  const parts = [];
  parts.push(`<b>${escape(actLabel)}</b> — ${r.green ? "✅ tests green" : "❌ tests red"}`);
  if (r.iterations) parts.push(`iterations: ${r.iterations}`);
  const files = r.patch?.changed_files || [];
  parts.push(files.length ? `files: ${escape(files.join(", "))}` : "no files changed");
  addMsg("ai", parts.join("<br>"));

  if (r.worker_reply) {
    addMsg("ai", `<b>Worker ne likha:</b><br>${escape(r.worker_reply.slice(0, 700))}`);
  }

  const res = $("#job-result");
  let html = "";
  if (files.length) {
    html += `<div class="review-actions">
      <button class="btn btn-view" id="btn-diff">&#128196; View Diff (${files.length})</button>
      <button class="btn btn-apply" id="btn-apply">&#10003; Apply Changes</button>
      <button class="btn btn-view" id="btn-dismiss">&#10005; Dismiss</button>
    </div>
    <div id="diff-box" class="diff hidden"></div>`;
  } else {
    html = `<div class="muted">nothing to apply</div>`;
  }
  res.innerHTML = html;

  const db = $("#diff-box");
  if (db && r.patch) {
    $("#btn-diff").onclick = () => {
      db.classList.toggle("hidden");
      if (!db.dataset.done) {
        db.innerHTML = renderDiff(r.patch);
        db.dataset.done = "1";
      }
    };
  }
  const ba = $("#btn-apply");
  if (ba)
    ba.onclick = async () => {
      ba.disabled = true;
      try {
        const out = await api("/api/agent/apply", {
          method: "POST",
          body: JSON.stringify({ project: project.path, copy_dir: r.copy_dir }),
        });
        const ok = out.applied?.ok;
        toast(ok ? "Apply ho gaya ✅" : "Apply fail", !ok);
        addMsg("sys", ok ? `applied ${out.applied.applied?.length || 0} file(s)` : "apply fail");
        if (ok) renderTree(project.path);
      } catch (e) {
        toast(e.message, true);
      }
      ba.disabled = false;
    };
  const bd = $("#btn-dismiss");
  if (bd)
    bd.onclick = () => {
      $("#job-panel").classList.add("hidden");
      addMsg("sys", "dismissed (copy is safe in .os/sandbox)");
    };
}

function renderDiff(patch) {
  let out = "";
  (patch.files || []).forEach((f) => {
    out += `<span class="file">--- ${escape(f.path)}</span>\n`;
    (f.diff || []).forEach((h) => {
      (h.lines || h || []).forEach((ln) => {
        const s = typeof ln === "string" ? ln : String(ln);
        if (s.startsWith("+")) out += `<span class="add">${escape(s)}</span>\n`;
        else if (s.startsWith("-")) out += `<span class="del">${escape(s)}</span>\n`;
        else out += escape(s) + "\n";
      });
    });
    out += "\n";
  });
  return out || "(empty)";
}

/* ---------- wire up ---------- */
$("#btn-add-project").onclick = askPath;
$("#btn-primer").onclick = showPrimer;
$("#btn-refresh").onclick = () => {
  loadProjects();
  if (project) renderTree(project.path);
  api("/api/status")
    .then((s) => {
      $("#f-model").textContent = "brain: " + (s.free_model || "?");
      $("#conn").textContent = "connected";
      $("#conn").className = "badge ok";
    })
    .catch(() => {
      $("#conn").textContent = "offline";
      $("#conn").className = "badge off";
    });
};
document.querySelectorAll(".close").forEach((b) => {
  if (b.dataset.close) b.onclick = () => $("#" + b.dataset.close).classList.add("hidden");
});

$("#chat-form").onsubmit = (e) => {
  e.preventDefault();
  const inp = $("#chat-input");
  const act = $("#act").value;
  const val = inp.value.trim();
  if (!val) return;
  const labels = {
    implement: "Implement",
    fix: "Fix failing tests",
    review: "Review & explain",
  };
  let instruction = val;
  if (act === "fix" && !/test|fail|fix/i.test(val))
    instruction = `Fix the failing tests in this repository. Task: ${val}`;
  if (act === "review" && !/review|explain/i.test(val))
    instruction = `Review and explain this without changing behavior: ${val}`;
  runJob(instruction, act !== "review", labels[act]);
  inp.value = "";
};

(async function init() {
  await loadProjects();
  const projects = await api("/api/projects").catch(() => ({ projects: [] }));
  if (projects.projects?.length) {
    project = projects.projects[0];
    renderTree(project.path);
    loadProjects();
  }
  $("#btn-refresh").click();
  $("#chat-input").focus();
})();
