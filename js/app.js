
const API_BASE = "/api";

function money(value, currency = "USD") {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "No disponible";
  }

  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency,
    maximumFractionDigits: 2
  }).format(value);
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

  target.innerHTML = companies.length
    ? companies.map(companyCard).join("")
    : '<div class="empty-state">No se encontraron empresas.</div>';
}

async function getQuote(symbol) {
  const response = await fetch(
    `${API_BASE}/quote/${encodeURIComponent(symbol)}`
  );

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || `Error en cotización (${response.status})`);
  }

  return data;
}

async function renderHomeQuotes() {
  const target = document.querySelector("#homeQuotes");
  if (!target) return;

  target.innerHTML = COMPANIES.slice(0, 3).map(company => `
    <div class="quote-row">
      <div class="quote-symbol">${company.symbol}</div>
      <div class="quote-company">${company.name}</div>
      <div class="quote-value">Consultando…</div>
    </div>
  `).join("");

  const rows = await Promise.all(
    COMPANIES.slice(0, 3).map(async company => {
      try {
        const quote = await getQuote(company.symbol);

        return `
          <div class="quote-row">
            <div class="quote-symbol">${company.symbol}</div>
            <div class="quote-company">${company.name}</div>
            <div class="quote-value">${money(quote.price)}</div>
          </div>
        `;
      } catch {
        return `
          <div class="quote-row">
            <div class="quote-symbol">${company.symbol}</div>
            <div class="quote-company">${company.name}</div>
            <div class="quote-value">Cotización no disponible</div>
          </div>
        `;
      }
    })
  );

  target.innerHTML = rows.join("");
}

function setupCompaniesPage() {
  const grid = document.querySelector("#companiesGrid");
  if (!grid) return;

  const search = document.querySelector("#companySearch");
  const count = document.querySelector("#companyCount");

  if (!search || !count) return;

  const render = () => {
    const term = search.value.trim().toLowerCase();

    const filtered = COMPANIES.filter(company =>
      `${company.name} ${company.symbol} ${company.sector}`
        .toLowerCase()
        .includes(term)
    );

    count.textContent =
      `${filtered.length} empresa${filtered.length === 1 ? "" : "s"}`;

    renderCompanyCards(grid, filtered);
  };

  search.addEventListener("input", render);
  render();
}

let priceChart;

async function setupQuotesPage() {
  const select = document.querySelector("#symbolSelect");
  if (!select) return;

  select.innerHTML = COMPANIES.map(company => `
    <option value="${company.symbol}">
      ${company.name} (${company.symbol})
    </option>
  `).join("");

  const params = new URLSearchParams(location.search);
  const requestedSymbol = params.get("symbol");

  if (COMPANIES.some(company => company.symbol === requestedSymbol)) {
    select.value = requestedSymbol;
  }

  select.addEventListener("change", () => loadChart(select.value));

  await loadChart(select.value);
}

async function loadChart(symbol) {
  const title = document.querySelector("#chartTitle");
  const status = document.querySelector("#chartStatus");
  const message = document.querySelector("#chartMessage");
  const selectedQuote = document.querySelector("#selectedQuote");
  const canvas = document.querySelector("#priceChart");

  if (!status || !message || !selectedQuote || !canvas) {
    console.error("Faltan elementos HTML necesarios para el gráfico.");
    return;
  }

  const company = COMPANIES.find(item => item.symbol === symbol);

  if (title) {
    title.textContent = company
      ? `${company.name} (${symbol})`
      : symbol;
  }

  status.textContent = "Consultando API…";
  message.textContent = "Buscando cotización e historial…";

  try {
    const results = await Promise.allSettled([
      fetch(`${API_BASE}/quote/${encodeURIComponent(symbol)}`),
      fetch(`${API_BASE}/history/${encodeURIComponent(symbol)}`)
    ]);

    let quote = null;
    let history = null;
    let quoteError = null;
    let historyError = null;

    if (results[0].status === "fulfilled") {
      const response = results[0].value;
      const data = await response.json().catch(() => ({}));

      if (response.ok) {
        quote = data;
      } else {
        quoteError = data.error || `Error en cotización (${response.status})`;
      }
    } else {
      quoteError = results[0].reason?.message || "No se pudo conectar con la cotización.";
    }

    if (results[1].status === "fulfilled") {
      const response = results[1].value;
      const data = await response.json().catch(() => ({}));

      if (response.ok) {
        history = data;
      } else {
        historyError = data.detalle || data.error ||
          `Error en historial (${response.status})`;
      }
    } else {
      historyError = results[1].reason?.message || "No se pudo conectar con el historial.";
    }

    if (quote && typeof quote.price === "number") {
      selectedQuote.innerHTML = `
        <span class="muted-label">PRECIO MÁS RECIENTE</span>
        <strong>${money(quote.price)}</strong>
        <small>
          ${quote.timestamp
            ? "Última actualización: " +
              new Date(quote.timestamp * 1000).toLocaleString("es-AR")
            : "Último dato disponible"}
        </small>
      `;
    } else {
      selectedQuote.innerHTML = `
        <span class="muted-label">PRECIO MÁS RECIENTE</span>
        <strong>—</strong>
        <small>${quoteError || "Cotización no disponible."}</small>
      `;
    }

    if (
      !history ||
      !Array.isArray(history.labels) ||
      !Array.isArray(history.values) ||
      history.labels.length === 0 ||
      history.labels.length !== history.values.length ||
      !history.values.every(value =>
        typeof value === "number" && Number.isFinite(value)
      )
    ) {
      throw new Error(
        historyError || "El historial no contiene fechas y precios válidos."
      );
    }

    if (typeof Chart === "undefined") {
      throw new Error("No se pudo cargar Chart.js para dibujar el gráfico.");
    }

    if (priceChart) {
      priceChart.destroy();
      priceChart = null;
    }

    priceChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: history.labels,
        datasets: [{
          label: "Precio (USD)",
          data: history.values,
          borderWidth: 2,
          borderColor: "#3269e8",
          backgroundColor: "rgba(50,105,232,.10)",
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 4
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          intersect: false,
          mode: "index"
        },
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              maxTicksLimit: 7,
              color: "#8793a3"
            }
          },
          y: {
            grid: { color: "#edf0f5" },
            ticks: {
              color: "#8793a3",
              callback: value => "$" + value
            }
          }
        }
      }
    });

    status.textContent = quote
      ? "Datos recibidos"
      : "Historial recibido";

    message.textContent = history.cache_notice
      ? history.cache_notice
      : quoteError
        ? `El historial está disponible, pero falló la cotización: ${quoteError}`
        : "Historial recibido correctamente.";

  } catch (error) {
    console.error("Error al cargar el gráfico:", error);

    status.textContent = "Error al cargar";
    message.textContent = error.message || "No se pudieron cargar los datos.";

    if (priceChart) {
      priceChart.destroy();
      priceChart = null;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderCompanyCards(
    document.querySelector("#featuredCompanies"),
    COMPANIES.slice(0, 3)
  );

  renderHomeQuotes();
  setupCompaniesPage();
  setupQuotesPage();
});
