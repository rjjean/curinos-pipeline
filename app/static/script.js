// Renders the paginated/sortable table by calling /api/records.
//
// Test hooks (the contract Playwright tests rely on):
//   - Every row has a data-record-id attribute equal to record.id
//   - Every cell has a data-field attribute equal to the column key
//   - Cell text content equals the raw stringified value from the API
//     (no formatting, no rounding) — this keeps reconciliation cheap and
//     deterministic. Display formatting belongs in a separate UI; here the
//     raw value is the source of truth for the reconciler.
//   - data-loading="true" is set on tbody while a fetch is in flight, and
//     data-loaded="true" is set when render is complete. Tests wait on these
//     instead of arbitrary timeouts.

const COLUMNS = [
  { key: "id", label: "ID" },
  { key: "account_id", label: "Account ID" },
  { key: "tier", label: "Tier" },
  { key: "region", label: "Region" },
  { key: "product_line", label: "Product" },
  { key: "balance", label: "Balance" },
  { key: "transaction_count", label: "Txns" },
  { key: "last_activity_date", label: "Last Activity" },
  { key: "is_active", label: "Active" },
];

const state = {
  page: 1,
  limit: 10,
  sortField: null,
  sortDir: "asc",
  totalPages: 1,
};

function buildHeader() {
  const row = document.getElementById("header-row");
  row.innerHTML = "";
  for (const col of COLUMNS) {
    const th = document.createElement("th");
    th.textContent = col.label;
    th.dataset.sort = col.key;
    th.setAttribute("data-testid", `header-${col.key}`);
    th.addEventListener("click", () => onHeaderClick(col.key));
    row.appendChild(th);
  }
}

function onHeaderClick(field) {
  if (state.sortField === field) {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    state.sortField = field;
    state.sortDir = "asc";
  }
  state.page = 1;
  refresh();
}

async function refresh() {
  const tbody = document.getElementById("records-tbody");
  tbody.dataset.loading = "true";
  tbody.dataset.loaded = "false";

  const params = new URLSearchParams({
    page: state.page,
    limit: state.limit,
  });
  if (state.sortField) {
    params.set("sort", `${state.sortField}:${state.sortDir}`);
  }

  const resp = await fetch(`/api/records?${params}`);
  if (!resp.ok) {
    tbody.innerHTML = `<tr><td colspan="${COLUMNS.length}">Error ${resp.status}</td></tr>`;
    tbody.dataset.loading = "false";
    return;
  }
  const payload = await resp.json();
  renderRows(payload.data);
  renderPagination(payload.pagination);
  renderSortIndicator();

  tbody.dataset.loading = "false";
  tbody.dataset.loaded = "true";
}

function renderRows(records) {
  const tbody = document.getElementById("records-tbody");
  tbody.innerHTML = "";
  for (const rec of records) {
    const tr = document.createElement("tr");
    tr.dataset.recordId = rec.id;
    for (const col of COLUMNS) {
      const td = document.createElement("td");
      td.dataset.field = col.key;
      // Use String() so the raw value (numbers, bools, strings) is preserved
      // exactly. Reconciler casts back from this text — keeping it raw means
      // no formatting drift between UI and API.
      td.textContent = String(rec[col.key]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderPagination(pagination) {
  state.totalPages = pagination.total_pages;
  document.getElementById("page-info").textContent =
    `Page ${pagination.page} of ${pagination.total_pages} (${pagination.total} records)`;
  document.getElementById("prev-btn").disabled = pagination.page <= 1;
  document.getElementById("next-btn").disabled = pagination.page >= pagination.total_pages;
}

function renderSortIndicator() {
  document.querySelectorAll("#header-row th").forEach((th) => {
    th.classList.remove("sorted-asc", "sorted-desc");
    if (th.dataset.sort === state.sortField) {
      th.classList.add(state.sortDir === "asc" ? "sorted-asc" : "sorted-desc");
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  buildHeader();
  document.getElementById("limit-select").addEventListener("change", (e) => {
    state.limit = parseInt(e.target.value, 10);
    state.page = 1;
    refresh();
  });
  document.getElementById("prev-btn").addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      refresh();
    }
  });
  document.getElementById("next-btn").addEventListener("click", () => {
    if (state.page < state.totalPages) {
      state.page += 1;
      refresh();
    }
  });
  refresh();
});
