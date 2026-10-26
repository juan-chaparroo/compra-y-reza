
import os
import time
import json
import sqlite3
import tempfile
import requests

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS


# =========================
# CONFIGURACIÓN
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=BASE_DIR,
    static_url_path=""
)

CORS(app)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()

FINNHUB_URL = "https://finnhub.io/api/v1"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

# Caché del historial: 24 horas
HISTORY_CACHE_SECONDS = 24 * 60 * 60

# SQLite guarda los datos fuera de la carpeta pública del sitio.
# HISTORY_CACHE_DB permite cambiar la ubicación si hace falta.
CACHE_DB_PATH = os.getenv(
    "HISTORY_CACHE_DB",
    os.path.join(
        tempfile.gettempdir(),
        "compra_y_reza_history_cache.db"
    )
)


# =========================
# BASE DE DATOS DE CACHÉ
# =========================

def get_db():
    connection = sqlite3.connect(CACHE_DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_cache_db():
    folder = os.path.dirname(CACHE_DB_PATH)

    if folder:
        os.makedirs(folder, exist_ok=True)

    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS history_cache (
                symbol TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL
            )
        """)


def load_history_cache(symbol):
    try:
        with get_db() as db:
            row = db.execute(
                """
                SELECT timestamp, data
                FROM history_cache
                WHERE symbol = ?
                """,
                (symbol,)
            ).fetchone()

        if row is None:
            return None

        return {
            "timestamp": row["timestamp"],
            "data": json.loads(row["data"])
        }

    except (sqlite3.Error, ValueError, TypeError) as error:
        app.logger.warning("Error leyendo caché: %s", error)
        return None


def save_history_cache(symbol, data):
    try:
        with get_db() as db:
            db.execute(
                """
                INSERT INTO history_cache (symbol, timestamp, data)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    data = excluded.data
                """,
                (
                    symbol,
                    time.time(),
                    json.dumps(data)
                )
            )

        app.logger.info("Historial guardado: %s", symbol)

    except sqlite3.Error as error:
        app.logger.error("No se pudo guardar la caché: %s", error)


def cached_response(cached, message=None):
    response = dict(cached["data"])

    if message:
        response["cache_notice"] = message

    return jsonify(response)


init_cache_db()


# =========================
# PÁGINAS HTML
# =========================

@app.get("/")
def inicio():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/empresas.html")
def empresas():
    return send_from_directory(BASE_DIR, "empresas.html")


@app.get("/cotizaciones.html")
def cotizaciones():
    return send_from_directory(BASE_DIR, "cotizaciones.html")


# =========================
# FINNHUB: COTIZACIÓN ACTUAL
# =========================

def fetch_finnhub(endpoint, params):
    if not FINNHUB_API_KEY:
        return None, (
            jsonify({
                "error": "Falta configurar FINNHUB_API_KEY"
            }),
            503
        )

    request_params = dict(params)
    request_params["token"] = FINNHUB_API_KEY

    try:
        response = requests.get(
            f"{FINNHUB_URL}/{endpoint}",
            params=request_params,
            timeout=15
        )
        response.raise_for_status()
        return response.json(), None

    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        app.logger.error("Error HTTP de Finnhub: %s", status)

        return None, (
            jsonify({
                "error": "Finnhub rechazó la consulta",
                "status": status
            }),
            502
        )

    except (requests.RequestException, ValueError) as error:
        app.logger.error("Error consultando Finnhub: %s", error)

        return None, (
            jsonify({
                "error": "No se pudo consultar la cotización"
            }),
            502
        )


@app.get("/api/quote/<symbol>")
def quote(symbol):
    symbol = symbol.upper().strip()

    data, error = fetch_finnhub(
        "quote",
        {"symbol": symbol}
    )

    if error:
        return error

    if not data or not data.get("c"):
        return jsonify({
            "error": "No hay cotización para ese símbolo"
        }), 404

    return jsonify({
        "symbol": symbol,
        "price": data["c"],
        "change": data.get("d"),
        "percent_change": data.get("dp"),
        "timestamp": data.get("t")
    })


# =========================
# ALPHA VANTAGE: HISTORIAL
# =========================

@app.get("/api/history/<symbol>")
def history(symbol):
    symbol = symbol.upper().strip()

    cached = load_history_cache(symbol)
    now = time.time()

    # 1. Si la caché tiene menos de 24 horas, usarla.
    if (
        cached
        and now - cached["timestamp"] < HISTORY_CACHE_SECONDS
    ):
        app.logger.info(
            "Usando historial vigente de %s",
            symbol
        )
        return cached_response(cached)

    # 2. Sin clave: intentar utilizar datos anteriores.
    if not ALPHA_VANTAGE_API_KEY:
        if cached:
            return cached_response(
                cached,
                "Se muestra el último historial guardado."
            )

        return jsonify({
            "error": "Falta configurar ALPHA_VANTAGE_API_KEY"
        }), 503

    # 3. Consultar Alpha Vantage cuando no hay caché vigente.
    try:
        response = requests.get(
            ALPHA_VANTAGE_URL,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": ALPHA_VANTAGE_API_KEY
            },
            timeout=20
        )

        response.raise_for_status()
        data = response.json()

        # Alpha Vantage puede informar límites en el JSON.
        restriction = (
            data.get("Note")
            or data.get("Information")
        )

        if restriction:
            app.logger.warning(
                "Restricción de Alpha Vantage: %s",
                restriction
            )

            if cached:
                return cached_response(
                    cached,
                    "Límite de consultas alcanzado. "
                    "Se muestra el último historial guardado."
                )

            return jsonify({
                "error": "Alpha Vantage informó un límite o restricción",
                "detalle": restriction
            }), 429

        if data.get("Error Message"):
            if cached:
                return cached_response(
                    cached,
                    "No se pudo actualizar. "
                    "Se muestra el último historial guardado."
                )

            return jsonify({
                "error": "Alpha Vantage rechazó el símbolo",
                "detalle": data["Error Message"]
            }), 400

        series = data.get("Time Series (Daily)")

        if not series:
            if cached:
                return cached_response(
                    cached,
                    "No se pudo actualizar el historial guardado."
                )

            return jsonify({
                "error": "No se recibieron datos históricos"
            }), 502

        # Orden cronológico: fechas antiguas primero.
        dates = sorted(series.keys())

        result = {
            "symbol": symbol,
            "labels": dates,
            "values": [
                float(series[date]["4. close"])
                for date in dates
            ]
        }

        # 4. Guardar únicamente respuestas válidas.
        save_history_cache(symbol, result)

        return jsonify(result)

    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        app.logger.error(
            "Error HTTP de Alpha Vantage: %s",
            status
        )

        if cached:
            return cached_response(
                cached,
                "No se pudo actualizar. "
                "Se muestra el último historial guardado."
            )

        return jsonify({
            "error": "Alpha Vantage rechazó la consulta",
            "status": status
        }), 502

    except (requests.RequestException, ValueError, KeyError) as error:
        app.logger.error(
            "Error consultando el historial: %s",
            error
        )

        if cached:
            return cached_response(
                cached,
                "Error de conexión. "
                "Se muestra el último historial guardado."
            )

        return jsonify({
            "error": "No se pudo obtener el historial"
        }), 502


# =========================
# ESTADO DEL SERVIDOR
# =========================

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "finnhub_key_configured": bool(FINNHUB_API_KEY),
        "alphavantage_key_configured": bool(
            ALPHA_VANTAGE_API_KEY
        )
    })


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
