const API_BASE = "http://127.0.0.1:5000/api";

function money(value, currency = "USD") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "No disponible";
  return new Intl.NumberFormat("es-AR", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}
function companyCard(company) {
  return `
    <div class="col-sm-6 col-lg-4">
      <article class="company-card">
        <div class="company-card-top">
          <div class="company-logo">${company.initials}</div>
          <div class="company-info">
            <h3>${company.name}</h3>
            <div class="sector">${company.sector}</div>
          </div>
        </div>

        <div class="company-symbol">
          <span>SÍMBOLO BURSÁTIL</span>
          <strong>${company.symbol}</strong>
        </div>

        <p>${company.description}</p>

        <a
          class="company-link"
          href="cotizaciones.html?symbol=${encodeURIComponent(company.symbol)}"
        >
          Consultar cotización
          <span aria-hidden="true">→</span>
        </a>
      </article>
    </div>
  `;
}
function renderCompanyCards(target, companies) {
  if (!target) return;
  target.innerHTML = companies.length ? companies.map(companyCard).join("") : '<div class="empty-state">No se encontraron empresas.</div>';
}
async function getQuote(symbol) {
  const response = await fetch(`${API_BASE}/quote/${encodeURIComponent(symbol)}`);
  if (!response.ok) throw new Error("No se pudo obtener la cotización");
  return response.json();
}
async function renderHomeQuotes() {
  const target = document.querySelector("#homeQuotes");
  if (!target) return;
  target.innerHTML = COMPANIES.slice(0, 3).map(c => `<div class="quote-row"><div class="quote-symbol">${c.symbol}</div><div class="quote-company">${c.name}</div><div class="quote-value">Consultando…</div></div>`).join("");
  const rows = await Promise.all(COMPANIES.slice(0, 3).map(async (company) => {
    try {
      const q = await getQuote(company.symbol);
      return `<div class="quote-row"><div class="quote-symbol">${company.symbol}</div><div class="quote-company">${company.name}</div><div class="quote-value">${money(q.price)}</div></div>`;
    } catch {
      return `<div class="quote-row"><div class="quote-symbol">${company.symbol}</div><div class="quote-company">${company.name}</div><div class="quote-value">API sin configurar</div></div>`;
    }
  }));
  target.innerHTML = rows.join("");
}
function setupCompaniesPage() {
  const grid = document.querySelector("#companiesGrid");
  if (!grid) return;
  const search = document.querySelector("#companySearch");
  const count = document.querySelector("#companyCount");
  const render = () => {
    const term = search.value.trim().toLowerCase();
    const filtered = COMPANIES.filter(c => `${c.name} ${c.symbol} ${c.sector}`.toLowerCase().includes(term));
    count.textContent = `${filtered.length} empresa${filtered.length === 1 ? "" : "s"}`;
    renderCompanyCards(grid, filtered);
  };
  search.addEventListener("input", render);
  render();
}
let priceChart;
async function setupQuotesPage() {
  const select = document.querySelector("#symbolSelect");
  if (!select) return;
  select.innerHTML = COMPANIES.map(c => `<option value="${c.symbol}">${c.name} (${c.symbol})</option>`).join("");
  const params = new URLSearchParams(location.search);
  if (COMPANIES.some(c => c.symbol === params.get("symbol"))) select.value = params.get("symbol");
  select.addEventListener("change", () => loadChart(select.value));
  await loadChart(select.value);
}
async function loadChart(symbol) {
  const company = COMPANIES.find(c => c.symbol === symbol);
  document.querySelector("#chartTitle").textContent = company ? `${company.name} (${symbol})` : symbol;
  document.querySelector("#chartStatus").textContent = "Consultando API…";
  document.querySelector("#chartMessage").textContent = "Buscando cotización e historial…";
  try {
    const [quoteResponse, historyResponse] = await Promise.all([
      fetch(`${API_BASE}/quote/${encodeURIComponent(symbol)}`),
      fetch(`${API_BASE}/history/${encodeURIComponent(symbol)}`)
    ]);
    if (!quoteResponse.ok || !historyResponse.ok) throw new Error("La API no respondió correctamente.");
    const quote = await quoteResponse.json();
    const history = await historyResponse.json();
    document.querySelector("#selectedQuote").innerHTML = `<span class="muted-label">PRECIO MÁS RECIENTE</span><strong>${money(quote.price)}</strong><small>${quote.timestamp ? "Última actualización: " + new Date(quote.timestamp * 1000).toLocaleString("es-AR") : "Último dato disponible"}</small>`;
    const ctx = document.querySelector("#priceChart");
    if (priceChart) priceChart.destroy();
    priceChart = new Chart(ctx, {
      type: "line",
      data: { labels: history.labels, datasets: [{ label: "Precio (USD)", data: history.values, borderWidth: 2, borderColor: "#3269e8", backgroundColor: "rgba(50,105,232,.10)", fill: true, tension: .25, pointRadius: 0, pointHoverRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: "index" }, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 7, color: "#8793a3" } }, y: { grid: { color: "#edf0f5" }, ticks: { color: "#8793a3", callback: v => "$" + v } } } }
    });
    document.querySelector("#chartStatus").textContent = "Datos recibidos";
    document.querySelector("#chartMessage").textContent = "Historial provisto por la API configurada. Puede haber demoras o límites de consulta.";
  } catch (error) {
    document.querySelector("#selectedQuote").innerHTML = `<span class="muted-label">PRECIO MÁS RECIENTE</span><strong>—</strong><small>No hay datos disponibles.</small>`;
    document.querySelector("#chartStatus").textContent = "Sin conexión";
    document.querySelector("#chartMessage").textContent = "No se pudieron cargar datos reales. Revisá que el servidor esté activo y que FINNHUB_API_KEY esté configurada. Detalle: " + error.message;
    if (priceChart) { priceChart.destroy(); priceChart = null; }
  }
}
document.addEventListener("DOMContentLoaded", () => {
  renderCompanyCards(document.querySelector("#featuredCompanies"), COMPANIES.slice(0, 3));
  renderHomeQuotes();
  setupCompaniesPage();
  setupQuotesPage();
});