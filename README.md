# Compra y Reza — sitio web inicial

Sitio de tres páginas: Inicio, Empresas y Cotizaciones. Frontend con HTML, CSS, Bootstrap 5 y JavaScript; gráficos con Chart.js; backend pequeño en Flask para no exponer la clave API en el navegador.

## 1. Requisitos
- Python 3.10 o superior
- Navegador moderno
- Una clave de API de Finnhub: https://finnhub.io/

## 2. Preparar el backend (Windows / PowerShell)
Abrí una terminal en la carpeta del proyecto y ejecutá:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si PowerShell bloquea la activación, podés usar Git Bash:
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

## 3. Configurar la clave API
En PowerShell, para la sesión actual:
```powershell
$env:FINNHUB_API_KEY="TU_CLAVE_REAL"
python server.py
```
En Git Bash:
```bash
export FINNHUB_API_KEY="TU_CLAVE_REAL"
python server.py
```

No publiques la clave ni la subas a GitHub. No hace falta crear el archivo `.env` para esta versión: el servidor lee la variable de entorno.

## 4. Abrir el sitio
Con el backend corriendo, abrí `index.html` con la extensión **Live Server** de VS Code. Las páginas llaman al backend en `http://127.0.0.1:5000`.

Podés comprobar el servidor visitando `http://127.0.0.1:5000/api/health`. Si responde `api_key_configured: true`, la clave está cargada.

## 5. Agregar o quitar empresas
Editá `js/companies.js`. Cada objeto tiene:
- `symbol`: símbolo bursátil reconocido por el proveedor
- `name`: nombre mostrado
- `sector`: sector
- `description`: descripción breve
- `initials`: letras del ícono

Ejemplo:
```js
{ symbol: "AAPL", name: "Apple", sector: "Tecnología", description: "Descripción", initials: "A" }
```

## Importante
- La disponibilidad de símbolos y el historial depende del proveedor y del plan de API.
- Algunos símbolos, especialmente los de mercados locales, pueden no estar disponibles con el mismo formato.
- Si no configurás la API, el sitio se muestra igual, pero los precios reales y el gráfico no se cargarán.
- Es una interfaz informativa y no constituye asesoramiento financiero.
