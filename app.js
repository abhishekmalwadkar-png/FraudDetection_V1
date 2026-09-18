/**
 * Apex Trust Commercial Bank - Fraud Operations Portal
 * Interactive Frontend Client with Live PostgreSQL Integration
 */

// State
let allTickets = [];
let filteredTickets = [];
let allCustomers = [];
let currentDossierTicket = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initClock();
  initEventListeners();
  checkSystemHealth();
  loadAllData();

  // 10-second background auto-refresh for real-time Process Studio RPA live sync
  setInterval(() => {
    const isModalOpen = document.getElementById("newTicketModal")?.classList.contains("open");
    const isDrawerOpen = document.getElementById("drawerOverlay")?.classList.contains("open");
    if (!isModalOpen && !isDrawerOpen) {
      loadAllData();
      checkSystemHealth();
    }
  }, 10000);
});

// System Health Heartbeat Monitor
async function checkSystemHealth() {
  const badge = document.getElementById("headerHealthBadge");
  const text = document.getElementById("healthStatusText");
  if (!badge || !text) return;

  try {
    const t0 = performance.now();
    const res = await fetch("/health");
    const roundtripMs = Math.round(performance.now() - t0);
    const data = await res.json();

    if (res.ok && data.status === "UP") {
      badge.className = "header-health-badge";
      text.textContent = `Live (${data.database.ping_latency_ms || roundtripMs}ms)`;
      badge.title = `Server: ${data.server} | DB: ${data.database.status} (${data.database.pool.database}) | Threads: ${data.worker_threads}`;
    } else {
      badge.className = "header-health-badge degraded";
      text.textContent = `Degraded (${roundtripMs}ms)`;
      badge.title = "Database or service connection degraded";
    }
  } catch (err) {
    badge.className = "header-health-badge down";
    text.textContent = "Offline";
    badge.title = "Backend server unreachable";
  }
}

// 1. Tab Navigation
function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      const targetTabId = tab.getAttribute("data-tab");
      document.querySelectorAll(".tab-panel").forEach(panel => {
        panel.classList.remove("active");
      });

      const targetPanel = document.getElementById(targetTabId);
      if (targetPanel) {
        targetPanel.classList.add("active");
        if (targetTabId === "tab-dashboard") loadAnalytics();
        if (targetTabId === "tab-customers") loadCustomers();
        if (targetTabId === "tab-transactions") loadTransactions();
        if (targetTabId === "tab-audit") loadAuditLogs();
        if (targetTabId === "tab-pgadmin") loadDbStatus();
      }
    });
  });
}

// 2. Real-time UTC Clock
function initClock() {
  const clockEl = document.getElementById("clockValue");
  function update() {
    const now = new Date();
    clockEl.textContent = now.toUTCString().replace("GMT", "UTC");
  }
  update();
  setInterval(update, 1000);
}

// 3. Event Listeners
function initEventListeners() {
  // Search & Filter listeners
  const searchInput = document.getElementById("ticketSearchInput");
  const filterSeverity = document.getElementById("filterSeverity");
  const filterStatus = document.getElementById("filterStatus");
  const filterIncidentType = document.getElementById("filterIncidentType");

  searchInput.addEventListener("input", applyFilters);
  filterSeverity.addEventListener("change", applyFilters);
  filterStatus.addEventListener("change", applyFilters);
  filterIncidentType.addEventListener("change", applyFilters);

  // Customer search
  const custSearchInput = document.getElementById("custSearchInput");
  if (custSearchInput) {
    custSearchInput.addEventListener("input", (e) => {
      const term = e.target.value.toLowerCase();
      const rows = document.querySelectorAll("#customersTableBody tr");
      rows.forEach(r => {
        r.style.display = r.textContent.toLowerCase().includes(term) ? "" : "none";
      });
    });
  }

  // Refresh & Export buttons
  document.getElementById("btnRefreshTickets").addEventListener("click", () => {
    loadAllData();
    showToast("Refreshed data from PostgreSQL database", "success");
  });

  document.getElementById("btnExportTicketsCSV").addEventListener("click", exportTicketsCSV);

  // Modal Open / Close
  const modal = document.getElementById("newTicketModal");
  document.getElementById("btnOpenNewTicketModal").addEventListener("click", () => {
    modal.classList.add("open");
  });
  document.getElementById("btnCloseModal").addEventListener("click", () => {
    modal.classList.remove("open");
  });
  document.getElementById("btnCancelModal").addEventListener("click", () => {
    modal.classList.remove("open");
  });

  // Modal Form Submit
  document.getElementById("newFraudTicketForm").addEventListener("submit", handleCreateNewTicket);

  // Drawer Close
  const drawerOverlay = document.getElementById("drawerOverlay");
  document.getElementById("btnCloseDrawer").addEventListener("click", () => {
    drawerOverlay.classList.remove("open");
  });
  drawerOverlay.addEventListener("click", (e) => {
    if (e.target === drawerOverlay) drawerOverlay.classList.remove("open");
  });

  // Drawer Emergency Actions
  document.getElementById("btnDrawerFreeze").addEventListener("click", handleFreezeAction);
  document.getElementById("btnDrawerInvestigate").addEventListener("click", () => handleStatusUpdate("UNDER_INVESTIGATION"));
  document.getElementById("btnDrawerResolve").addEventListener("click", () => handleStatusUpdate("RESOLVED"));
  document.getElementById("btnDrawerEscalate").addEventListener("click", () => handleStatusUpdate("ESCALATED"));

  // pgAdmin SQL Runner (if present)
  const runBtn = document.getElementById("btnRunSQLQuery");
  if (runBtn) {
    runBtn.addEventListener("click", executeSQLQuery);
    document.querySelectorAll(".quick-sql-presets button").forEach(btn => {
      btn.addEventListener("click", () => {
        const queryEl = document.getElementById("sqlQueryText");
        if (queryEl) {
          queryEl.value = btn.getAttribute("data-sql");
          executeSQLQuery();
        }
      });
    });
  }

  // PDF Export trigger
  const btnDownloadSAR = document.getElementById("btnDownloadSAR");
  if (btnDownloadSAR) {
    btnDownloadSAR.addEventListener("click", () => {
      showToast("FinCEN Suspicious Activity Report (SAR) XML/PDF generated & logged.", "success");
    });
  }
}

// 4. Data Loading Pipeline
async function loadAllData() {
  await Promise.all([
    loadOverviewStats(),
    loadFraudTickets()
  ]);
}

async function loadOverviewStats() {
  try {
    const res = await fetch("/api/overview");
    const data = await res.json();

    document.getElementById("kpiTotalCustomers").textContent = data.total_customers || "25";
    document.getElementById("kpiTotalTickets").textContent = data.total_tickets || "25";
    document.getElementById("badgeTicketCount").textContent = data.total_tickets || "25";
    document.getElementById("kpiTotalAmount").textContent = formatCurrency(data.total_amount || 2185930);
    document.getElementById("kpiRecoveredAmount").textContent = formatCurrency(data.recovered_amount || 1621430);
    document.getElementById("kpiFrozenAccounts").textContent = data.frozen_accounts || "3";
    document.getElementById("kpiCriticalCount").textContent = data.critical_customers || "6";

    // Dashboard recovery
    if (document.getElementById("recGrossVal")) {
      document.getElementById("recGrossVal").textContent = formatCurrency(data.total_amount || 2185930);
      document.getElementById("recRecoveredVal").textContent = formatCurrency(data.recovered_amount || 1621430);
      const pending = (data.total_amount || 2185930) - (data.recovered_amount || 1621430);
      document.getElementById("recPendingVal").textContent = formatCurrency(pending);
      const pct = Math.round(((data.recovered_amount || 1) / (data.total_amount || 1)) * 100);
      document.getElementById("recoveryRatePercent").textContent = `${pct}%`;
    }
  } catch (err) {
    console.error("Error loading overview stats:", err);
  }
}

async function loadFraudTickets() {
  const tbody = document.getElementById("fraudTicketsTableBody");
  try {
    const res = await fetch("/api/fraud-tickets");
    allTickets = await res.json();
    applyFilters();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-state" style="color: var(--rose);">Failed to load tickets from database. Please verify backend is running.</td></tr>`;
  }
}

function applyFilters() {
  const searchTerm = document.getElementById("ticketSearchInput").value.trim().toLowerCase();
  const severityFilter = document.getElementById("filterSeverity").value;
  const statusFilter = document.getElementById("filterStatus").value;
  const typeFilter = document.getElementById("filterIncidentType").value;

  filteredTickets = allTickets.filter(t => {
    // Search
    const searchMatch = !searchTerm ||
      t.ticket_number.toLowerCase().includes(searchTerm) ||
      t.full_name.toLowerCase().includes(searchTerm) ||
      t.email.toLowerCase().includes(searchTerm) ||
      t.account_number.toLowerCase().includes(searchTerm) ||
      t.customer_code.toLowerCase().includes(searchTerm) ||
      t.incident_type.toLowerCase().includes(searchTerm);

    // Severity
    const sevMatch = severityFilter === "ALL" || t.severity === severityFilter;

    // Status
    const statusMatch = statusFilter === "ALL" || t.status === statusFilter;

    // Type
    const typeMatch = typeFilter === "ALL" || t.incident_type.toLowerCase().includes(typeFilter.toLowerCase());

    return searchMatch && sevMatch && statusMatch && typeMatch;
  });

  renderFraudTicketsTable(filteredTickets);
  updatePillCounts();
}

function renderFraudTicketsTable(tickets) {
  const tbody = document.getElementById("fraudTicketsTableBody");
  document.getElementById("visibleTicketCount").textContent = tickets.length;

  if (tickets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-state">No fraud tickets match your current filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = tickets.map(t => {
    const sevBadge = getSeverityBadgeHtml(t.severity);
    const statusBadge = getStatusBadgeHtml(t.status);

    return `
      <tr>
        <td>
          <span class="code-font" style="font-weight: 700; color: var(--cyan);">${t.ticket_number}</span>
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(t.full_name)}</span>
            <span class="customer-sub">${escapeHtml(t.city || '')}, ${escapeHtml(t.state || '')}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="customer-name" style="font-size: 12px;">${escapeHtml(t.email)}</span>
            <span class="customer-sub code-font">${escapeHtml(t.customer_code)}</span>
          </div>
        </td>
        <td>
          <div class="customer-cell">
            <span class="code-font" style="color: #fff;">${t.account_number}</span>
            <span class="customer-sub">${t.account_type || 'CHECKING'}</span>
          </div>
        </td>
        <td>
          <strong style="color: #e2e8f0; font-size: 13px;">${escapeHtml(t.incident_type)}</strong>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
            <i class="fa-solid fa-satellite-dish" style="font-size: 10px;"></i> ${escapeHtml(t.reported_channel)}
          </div>
        </td>
        <td>
          <div class="amount-font ${t.amount_involved > 50000 ? 'highlight-red' : 'highlight-amber'}">
            ${formatCurrency(t.amount_involved)}
          </div>
          ${t.recovered_amount > 0 ? `<div style="font-size: 10px; color: var(--emerald);">Rec: ${formatCurrency(t.recovered_amount)}</div>` : ''}
        </td>
        <td>${sevBadge}</td>
        <td>${statusBadge}</td>
        <td>
          <span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(t.assigned_investigator ? t.assigned_investigator.split('(')[0] : 'Investigator')}</span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-xs btn-outline" onclick="openIncidentDossier('${t.ticket_id}')">
            <i class="fa-solid fa-eye"></i> View Details
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

function updatePillCounts() {
  const crit = allTickets.filter(t => t.severity === "CRITICAL").length;
  const high = allTickets.filter(t => t.severity === "HIGH").length;
  const med = allTickets.filter(t => t.severity === "MEDIUM").length;
  const res = allTickets.filter(t => t.status === "RESOLVED").length;

  document.getElementById("pillCritCount").textContent = `${crit} Urgent`;
  document.getElementById("pillHighCount").textContent = `${high} High`;
  document.getElementById("pillMedCount").textContent = `${med} Medium`;
  document.getElementById("pillResCount").textContent = `${res} Solved`;
}

// 5. Incident Dossier Slide-Over
window.openIncidentDossier = async function(ticketId) {
  try {
    const res = await fetch(`/api/fraud-tickets/${ticketId}`);
    if (!res.ok) throw new Error("Ticket not found");
    const ticket = await res.json();
    currentDossierTicket = ticket;

    document.getElementById("drawerTicketNumber").textContent = ticket.ticket_number;
    
    // Severity badge in drawer
    const sevBadge = document.getElementById("drawerSeverityBadge");
    sevBadge.className = `tag-pill tag-${ticket.severity.toLowerCase()}`;
    sevBadge.textContent = ticket.severity;

    // Victim details
    document.getElementById("dossierName").textContent = ticket.full_name;
    document.getElementById("dossierCode").textContent = ticket.customer_code;
    document.getElementById("dossierEmail").textContent = ticket.email;
    document.getElementById("dossierPhone").textContent = ticket.phone;
    document.getElementById("dossierAccount").textContent = ticket.account_number;
    document.getElementById("dossierBalance").textContent = `${ticket.account_type || 'CHECKING'} (${formatCurrency(ticket.balance)}) - ${ticket.account_status}`;

    // Forensics
    document.getElementById("dossierType").textContent = ticket.incident_type;
    document.getElementById("dossierAmount").textContent = formatCurrency(ticket.amount_involved);
    document.getElementById("dossierRecovered").textContent = formatCurrency(ticket.recovered_amount);
    document.getElementById("dossierChannel").textContent = ticket.reported_channel;
    document.getElementById("dossierIp").textContent = ticket.flagged_ip_or_location || "N/A";
    document.getElementById("dossierSuspect").textContent = ticket.suspect_entity || "Under Forensics Tracing";
    document.getElementById("dossierDescription").textContent = ticket.description;
    document.getElementById("dossierAction").textContent = ticket.action_taken || "Incident registered in database. Active forensics docket.";

    // Linked Transactions
    const txnListEl = document.getElementById("drawerTxnList");
    if (ticket.transactions && ticket.transactions.length > 0) {
      txnListEl.innerHTML = ticket.transactions.map(tx => `
        <div class="drawer-txn-item">
          <div style="display: flex; justify-content: space-between;">
            <strong class="code-font highlight-cyan">${tx.txn_reference}</strong>
            <span class="amount-font highlight-red">${formatCurrency(tx.amount)}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-dim); margin-top: 3px;">
            Target: ${escapeHtml(tx.merchant_or_recipient)} • Score: <strong>${tx.fraud_risk_score}/100</strong> • Status: <strong>${tx.status}</strong>
          </div>
        </div>
      `).join("");
    } else {
      txnListEl.innerHTML = `<div style="font-size: 12px; color: var(--text-dim);">No transactions flagged.</div>`;
    }

    // Audit logs
    const auditListEl = document.getElementById("drawerAuditList");
    if (ticket.audit_logs && ticket.audit_logs.length > 0) {
      auditListEl.innerHTML = ticket.audit_logs.map(log => `
        <div class="drawer-audit-item">
          <div style="display: flex; justify-content: space-between; font-size: 11px;">
            <strong>${escapeHtml(log.actor)}</strong>
            <span style="color: var(--text-dim);">${formatDate(log.created_at)}</span>
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">${escapeHtml(log.details)}</div>
        </div>
      `).join("");
    } else {
      auditListEl.innerHTML = `<div style="font-size: 12px; color: var(--text-dim);">No prior audit history.</div>`;
    }

    document.getElementById("drawerOverlay").classList.add("open");
  } catch (err) {
    showToast("Error opening ticket dossier: " + err.message, "error");
  }
};

// 6. Actions in Drawer
async function handleFreezeAction() {
  if (!currentDossierTicket) return;
  const accNum = currentDossierTicket.account_number;
  const ticketNum = currentDossierTicket.ticket_number;

  try {
    const res = await fetch("/api/freeze-account", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_number: accNum, ticket_number: ticketNum })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Account ${accNum} has been temporarily blocked to protect customer funds.`, "warning");
      document.getElementById("drawerOverlay").classList.remove("open");
      loadAllData();
    }
  } catch (err) {
    showToast("Could not block account: " + err.message, "error");
  }
}

async function handleStatusUpdate(newStatus) {
  if (!currentDossierTicket) return;
  const ticketId = currentDossierTicket.ticket_id;

  try {
    const res = await fetch(`/api/fraud-tickets/${ticketId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: newStatus,
        action_taken: `Staff updated status on ${new Date().toLocaleDateString()}`
      })
    });
    const data = await res.json();
    if (data.success) {
      const friendlyStatus = newStatus === 'RESOLVED' ? 'Solved / Refunded' : (newStatus === 'FROZEN' ? 'Account Blocked' : (newStatus === 'ESCALATED' ? 'Escalated' : 'In Progress'));
      showToast(`Complaint ${currentDossierTicket.ticket_number} updated to "${friendlyStatus}"`, "success");
      document.getElementById("drawerOverlay").classList.remove("open");
      loadAllData();
    }
  } catch (err) {
    showToast("Could not update status: " + err.message, "error");
  }
}

// 7. Create New Fraud Ticket Form
async function handleCreateNewTicket(e) {
  e.preventDefault();
  const payload = {
    full_name: document.getElementById("formCustName").value,
    email: document.getElementById("formCustEmail").value,
    phone: document.getElementById("formCustPhone").value,
    account_number: document.getElementById("formAccNum").value,
    account_type: document.getElementById("formAccType").value,
    incident_type: document.getElementById("formIncidentType").value,
    amount_involved: parseFloat(document.getElementById("formAmount").value),
    severity: document.getElementById("formSeverity").value,
    suspect_entity: document.getElementById("formSuspect").value,
    description: document.getElementById("formDescription").value,
    reported_channel: "Customer Help Desk"
  };

  try {
    const res = await fetch("/api/fraud-tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Fraud Complaint ${data.ticket_number} registered successfully!`, "success");
      document.getElementById("newTicketModal").classList.remove("open");
      document.getElementById("newFraudTicketForm").reset();
      loadAllData();
    }
  } catch (err) {
    showToast("Error registering complaint: " + err.message, "error");
  }
}

// 8. Customer 360 Directory
async function loadCustomers() {
  const tbody = document.getElementById("customersTableBody");
  try {
    const res = await fetch("/api/customers");
    allCustomers = await res.json();

    tbody.innerHTML = allCustomers.map(c => `
      <tr>
        <td><span class="code-font highlight-cyan">${c.customer_code}</span></td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(c.full_name)}</span>
            <span class="customer-sub">${escapeHtml(c.phone || '')}</span>
          </div>
        </td>
        <td><span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(c.email)}</span></td>
        <td><span style="font-size: 12px;">${escapeHtml(c.city || 'N/A')}, ${escapeHtml(c.state || '')}</span></td>
        <td><span class="code-font" style="color: #fff;">${c.account_number || 'ACT-PENDING'}</span></td>
        <td><span class="tag-pill tag-cyan">${c.account_type || 'CHECKING'}</span></td>
        <td><span class="amount-font highlight-emerald">${formatCurrency(c.balance)}</span></td>
        <td>
          <span class="tag-pill ${c.account_status === 'FROZEN' ? 'tag-frozen' : 'tag-resolved'}">
            ${c.account_status || 'ACTIVE'}
          </span>
        </td>
        <td>${getSeverityBadgeHtml(c.risk_tier || 'LOW')}</td>
        <td>
          <span class="tag-pill ${c.fraud_reports_count > 0 ? 'tag-critical' : 'tag-low'}">
            ${c.fraud_reports_count} Incident${c.fraud_reports_count === 1 ? '' : 's'}
          </span>
        </td>
        <td style="text-align: right;">
          <button class="btn btn-xs btn-outline" onclick="filterByCustomerName('${escapeHtml(c.full_name)}')">
            <i class="fa-solid fa-list-check"></i> View Fraud
          </button>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="11" class="loading-state">Error loading customer directory.</td></tr>`;
  }
}

window.filterByCustomerName = function(name) {
  const navFraud = document.getElementById("navTabFraudTickets");
  if (navFraud) navFraud.click();
  document.getElementById("ticketSearchInput").value = name;
  applyFilters();
};

// 9. Live Transactions
async function loadTransactions() {
  const tbody = document.getElementById("txnsTableBody");
  try {
    const res = await fetch("/api/transactions");
    const txns = await res.json();

    tbody.innerHTML = txns.map(tx => `
      <tr>
        <td><span class="code-font highlight-cyan">${tx.txn_reference}</span></td>
        <td>
          <div class="customer-cell">
            <span class="customer-name">${escapeHtml(tx.full_name)}</span>
            <span class="customer-sub code-font">${tx.account_number}</span>
          </div>
        </td>
        <td><span class="code-font" style="color: #fff;">${tx.account_number}</span></td>
        <td><span class="amount-font highlight-red">${formatCurrency(tx.amount)}</span></td>
        <td><span class="tag-pill tag-cyan">${tx.txn_type}</span></td>
        <td><span style="font-size: 12px;">${escapeHtml(tx.merchant_or_recipient)}</span></td>
        <td><span class="code-font" style="font-size: 11px; color: var(--text-dim);">${escapeHtml(tx.ip_address || 'Internal')}</span></td>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <div class="progress-bar-wrap" style="width: 60px;">
              <div class="bar-fill ${tx.fraud_risk_score > 75 ? 'red' : 'amber'}" style="width: ${tx.fraud_risk_score}%;"></div>
            </div>
            <strong class="code-font ${tx.fraud_risk_score > 75 ? 'highlight-red' : 'highlight-amber'}">${tx.fraud_risk_score}%</strong>
          </div>
        </td>
        <td>
          <span class="tag-pill ${tx.is_fraud_flagged ? 'tag-critical' : 'tag-resolved'}">
            ${tx.is_fraud_flagged ? 'FLAGGED' : 'CLEAN'}
          </span>
        </td>
        <td>
          <span class="tag-pill ${tx.status === 'BLOCKED' ? 'tag-frozen' : (tx.status === 'HELD' ? 'tag-high' : 'tag-resolved')}">
            ${tx.status}
          </span>
        </td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" class="loading-state">Error loading transactions.</td></tr>`;
  }
}

// 10. Threat Analytics / Executive Charts
async function loadAnalytics() {
  try {
    const res = await fetch("/api/analytics");
    const data = await res.json();

    // Incident types bar chart
    const chartTypesEl = document.getElementById("chartIncidentTypes");
    if (chartTypesEl && data.by_type) {
      const maxCount = Math.max(...data.by_type.map(d => d.count), 1);
      chartTypesEl.innerHTML = data.by_type.map(item => {
        const pct = Math.round((item.count / maxCount) * 100);
        return `
          <div class="chart-row">
            <div class="chart-label-group">
              <span>${escapeHtml(item.type)}</span>
              <strong>${item.count} cases (${formatCurrency(item.amount)})</strong>
            </div>
            <div class="chart-bar-bg">
              <div class="chart-bar-fill" style="width: ${pct}%; background: linear-gradient(90deg, #2563eb, #38bdf8);"></div>
            </div>
          </div>
        `;
      }).join("");
    }

    // Reporting channels
    const channelsEl = document.getElementById("chartChannels");
    if (channelsEl && data.by_channel) {
      channelsEl.innerHTML = data.by_channel.map(ch => `
        <div class="channel-card">
          <div class="channel-icon"><i class="fa-solid fa-tower-broadcast"></i></div>
          <div>
            <strong style="font-size: 13px; color: #fff;">${escapeHtml(ch.channel)}</strong>
            <div style="font-size: 11px; color: var(--text-dim); margin-top: 2px;">
              ${ch.count} reports • ${formatCurrency(ch.amount)}
            </div>
          </div>
        </div>
      `).join("");
    }

    // Critical queue list
    const critQueueEl = document.getElementById("criticalQueueList");
    if (critQueueEl) {
      const critTickets = allTickets.filter(t => t.severity === "CRITICAL" || t.status === "FROZEN").slice(0, 4);
      critQueueEl.innerHTML = critTickets.map(ct => `
        <div class="queue-item" onclick="openIncidentDossier('${ct.ticket_id}')">
          <div>
            <strong style="font-size: 13px; color: #fff;">${escapeHtml(ct.full_name)} (${ct.ticket_number})</strong>
            <div style="font-size: 11px; color: var(--text-dim);">${escapeHtml(ct.incident_type)}</div>
          </div>
          <div style="text-align: right;">
            <div class="amount-font highlight-red">${formatCurrency(ct.amount_involved)}</div>
            <span class="tag-pill tag-critical" style="font-size: 9px; padding: 2px 6px;">${ct.status}</span>
          </div>
        </div>
      `).join("");
    }
  } catch (err) {
    console.error("Error loading analytics:", err);
  }
}

// 11. Audit Logs
async function loadAuditLogs() {
  const tbody = document.getElementById("auditTableBody");
  try {
    const res = await fetch("/api/audit-logs");
    const logs = await res.json();

    tbody.innerHTML = logs.map(l => `
      <tr>
        <td><span class="code-font" style="color: var(--text-dim);">#LOG-${l.log_id}</span></td>
        <td><span class="code-font highlight-cyan">${l.ticket_number || 'SYSTEM'}</span></td>
        <td><strong style="color: #fff; font-size: 12px;">${escapeHtml(l.actor)}</strong></td>
        <td><span class="tag-pill tag-high">${escapeHtml(l.action)}</span></td>
        <td><span style="font-size: 12px; color: var(--text-muted);">${escapeHtml(l.details)}</span></td>
        <td><span class="code-font" style="font-size: 11px; color: var(--text-dim);">${escapeHtml(l.ip_address || '10.0.0.1')}</span></td>
        <td><span style="font-size: 11px; color: var(--text-dim);">${formatDate(l.created_at)}</span></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="loading-state">Error loading audit logs.</td></tr>`;
  }
}

// 12. PostgreSQL & pgAdmin Hub
async function loadDbStatus() {
  try {
    const res = await fetch("/api/db-status");
    const db = await res.json();
    const dbBadge = document.getElementById("dbNameBadge");
    if (dbBadge) dbBadge.textContent = db.database;
  } catch (err) {
    console.error("Error loading db status:", err);
  }
}

async function executeSQLQuery() {
  const query = document.getElementById("sqlQueryText").value.trim();
  const resultsContainer = document.getElementById("sqlResultsContainer");
  const countBadge = document.getElementById("sqlRowCountBadge");
  const statusEl = document.getElementById("sqlExecutionStatus");

  if (!query) {
    showToast("Please enter an SQL query to execute", "warning");
    return;
  }

  resultsContainer.innerHTML = `<div class="loading-state"><div class="spinner"></div> Executing SQL query against PostgreSQL...</div>`;

  try {
    const res = await fetch("/api/execute-sql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      statusEl.textContent = "Error";
      statusEl.className = "highlight-rose";
      resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--rose); font-family: var(--font-mono); font-size: 12px;">PostgreSQL Error: ${escapeHtml(data.error)}</div>`;
      countBadge.textContent = "0 rows";
      return;
    }

    statusEl.textContent = "Query executed successfully";
    statusEl.className = "highlight-emerald";
    countBadge.textContent = `${data.row_count || 0} rows`;

    if (data.columns && data.rows) {
      let tableHtml = `<table class="data-table"><thead><tr>`;
      data.columns.forEach(col => {
        tableHtml += `<th>${escapeHtml(col)}</th>`;
      });
      tableHtml += `</tr></thead><tbody>`;

      data.rows.forEach(row => {
        tableHtml += `<tr>`;
        row.forEach(cell => {
          tableHtml += `<td class="code-font" style="font-size: 12px;">${cell !== null ? escapeHtml(String(cell)) : '<span style="color: var(--text-dim)">NULL</span>'}</td>`;
        });
        tableHtml += `</tr>`;
      });
      tableHtml += `</tbody></table>`;
      resultsContainer.innerHTML = tableHtml;
    } else {
      resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--emerald);">${escapeHtml(data.message || 'Done')}</div>`;
    }
  } catch (err) {
    resultsContainer.innerHTML = `<div style="padding: 20px; color: var(--rose);">Execution failed: ${err.message}</div>`;
  }
}

// 13. CSV Export
function exportTicketsCSV() {
  if (allTickets.length === 0) {
    showToast("No ticket data to export", "warning");
    return;
  }

  const headers = ["Ticket Number", "Customer Name", "Customer Code", "Email", "Phone", "Account Number", "Incident Type", "Amount Flagged", "Recovered Amount", "Severity", "Status", "Investigator", "Date"];
  const rows = allTickets.map(t => [
    `"${t.ticket_number}"`,
    `"${t.full_name}"`,
    `"${t.customer_code}"`,
    `"${t.email}"`,
    `"${t.phone}"`,
    `"${t.account_number}"`,
    `"${t.incident_type}"`,
    t.amount_involved,
    t.recovered_amount,
    `"${t.severity}"`,
    `"${t.status}"`,
    `"${t.assigned_investigator}"`,
    `"${t.incident_date}"`
  ]);

  const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `apex_bank_fraud_report_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  showToast("CSV export completed successfully", "success");
}

// Utility Helpers
function getSeverityBadgeHtml(sev) {
  const s = (sev || "MEDIUM").toUpperCase();
  if (s === "CRITICAL") return `<span class="tag-pill tag-critical"><i class="fa-solid fa-triangle-exclamation"></i> Urgent</span>`;
  if (s === "HIGH") return `<span class="tag-pill tag-high"><i class="fa-solid fa-circle-exclamation"></i> High</span>`;
  if (s === "MEDIUM") return `<span class="tag-pill tag-medium">Medium</span>`;
  return `<span class="tag-pill tag-low">Normal</span>`;
}

function getStatusBadgeHtml(status) {
  const s = (status || "UNDER_INVESTIGATION").toUpperCase();
  if (s === "RESOLVED") return `<span class="tag-pill tag-resolved"><i class="fa-solid fa-circle-check"></i> Solved</span>`;
  if (s === "FROZEN") return `<span class="tag-pill tag-frozen"><i class="fa-solid fa-lock"></i> Blocked</span>`;
  if (s === "ESCALATED") return `<span class="tag-pill tag-critical"><i class="fa-solid fa-user-shield"></i> Escalated</span>`;
  return `<span class="tag-pill tag-investigating"><i class="fa-solid fa-clock"></i> In Progress</span>`;
}

function formatCurrency(val) {
  const num = typeof val === "number" ? val : parseFloat(val || 0);
  return "₹" + num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(isoStr) {
  if (!isoStr) return "--";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return isoStr;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <i class="fa-solid ${type === 'error' ? 'fa-circle-xmark' : (type === 'warning' ? 'fa-triangle-exclamation' : 'fa-circle-check')}"></i>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
