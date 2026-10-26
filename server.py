
import os
import time
import json
import sqlite3
import tempfile
import requests

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS


# =========================
# CONFIGURACION
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=BASE_DIR,
    static_url_path=""
)

CORS(app)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

FINNHUB_URL = "https://finnhub.io/api/v1"
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

# La informacion historica se conserva durante 24 horas.
HISTORY_CACHE_SECONDS = 24 * 60 * 60

# Se puede configurar una ruta persistente mediante una variable
# de entorno de Render llamada HISTORY_CACHE_DB.
CACHE_DB_PATH = os.getenv(
    "HISTORY_CACHE_DB",
    os.path.join(
        tempfile.gettempdir(),
        "compra_y_reza_history_cache.db"
    )
)


# =========================
# BASE DE DATOS DE CACHE
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
        app.logger.warning("Error leyendo cache: %s", error)
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

        app.logger.info("Historial guardado en cache: %s", symbol)

    except sqlite3.Error as error:
        app.logger.error("No se pudo guardar el cache: %s", error)


def cached_response(cached, message=None):
    response = dict(cached["data"])

    if message:
        response["cache_notice"] = message

    return jsonify(response)


init_cache_db()


# =========================
# PAGINAS HTML
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
# FINNHUB: COTIZACION ACTUAL
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
                "error": "Finnhub rechazo la consulta",
                "status": status
            }),
            502
        )

    except (requests.RequestException, ValueError) as error:
        app.logger.error("Error consultando Finnhub: %s", error)

        return None, (
            jsonify({
                "error": "No se pudo consultar la cotizacion"
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
            "error": "No hay cotizacion para ese simbolo"
        }), 404

    return jsonify({
        "symbol": symbol,
        "price": data["c"],
        "change": data.get("d"),
        "percent_change": data.get("dp"),
        "timestamp": data.get("t")
    })


# =========================
# TWELVE DATA: HISTORIAL
# =========================

@app.get("/api/history/<symbol>")
def history(symbol):
    symbol = symbol.upper().strip()

    # Prefijo propio para separar la cache de Twelve Data
    # de los historiales guardados anteriormente con Alpha Vantage.
    cache_key = "TWELVE_DATA_" + symbol

    cached = load_history_cache(cache_key)
    now = time.time()

    # 1. Si la cache tiene menos de 24 horas, reutilizarla.
    if (
        cached
        and now - cached["timestamp"] < HISTORY_CACHE_SECONDS
    ):
        app.logger.info("Usando historial guardado de %s", symbol)
        return cached_response(cached)

    # 2. Si no hay clave, intentar usar datos guardados.
    if not TWELVE_DATA_API_KEY:
        if cached:
            return cached_response(
                cached,
                "No hay clave de Twelve Data. Se muestra el ultimo historial guardado."
            )

        return jsonify({
            "error": "Falta configurar TWELVE_DATA_API_KEY"
        }), 503

    # 3. Solicitar hasta 100 registros diarios a Twelve Data.
    try:
        response = requests.get(
            TWELVE_DATA_URL,
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": 100,
                "apikey": TWELVE_DATA_API_KEY
            },
            timeout=20
        )

        response.raise_for_status()
        data = response.json()

        # Twelve Data puede responder con un error en formato JSON.
        if data.get("status") == "error" or data.get("code"):
            message = data.get("message", "Error de Twelve Data")

            app.logger.warning(
                "Twelve Data no devolvio el historial de %s: %s",
                symbol,
                message
            )

            if cached:
                return cached_response(
                    cached,
                    "No se pudo actualizar. Se muestra el ultimo historial guardado."
                )

            return jsonify({
                "error": "Twelve Data no pudo obtener el historial",
                "detalle": message
            }), 502

        records = data.get("values")

        if not records:
            if cached:
                return cached_response(
                    cached,
                    "No hay datos nuevos. Se muestra el ultimo historial guardado."
                )

            return jsonify({
                "error": "Twelve Data no devolvio datos historicos"
            }), 502

        # Twelve Data normalmente devuelve los registros mas recientes
        # primero. Ordenarlos cronologicamente para el grafico.
        records = sorted(
            records,
            key=lambda item: item.get("datetime", "")
        )

        labels = []
        values = []

        for record in records:
            date = record.get("datetime")
            close = record.get("close")

            if date is None or close is None:
                continue

            try:
                price = float(close)
            except (ValueError, TypeError):
                continue

            labels.append(date)
            values.append(price)

        if not labels or len(labels) != len(values):
            if cached:
                return cached_response(
                    cached,
                    "Los datos nuevos no son validos. Se muestra el ultimo historial guardado."
                )

            return jsonify({
                "error": "El historial recibido no contiene precios validos"
            }), 502

        result = {
            "symbol": symbol,
            "labels": labels,
            "values": values
        }

        # 4. Guardar el historial valido en SQLite.
        save_history_cache(cache_key, result)

        return jsonify(result)

    except requests.HTTPError as error:
        status = (
            error.response.status_code
            if error.response is not None
            else 502
        )

        app.logger.error("Error HTTP de Twelve Data: %s", status)

        if cached:
            return cached_response(
                cached,
                "No se pudo actualizar. Se muestra el ultimo historial guardado."
            )

        return jsonify({
            "error": "Twelve Data rechazo la consulta",
            "status": status
        }), 502

    except (requests.RequestException, ValueError, TypeError) as error:
        app.logger.error("Error consultando Twelve Data: %s", error)

        if cached:
            return cached_response(
                cached,
                "Error de conexion. Se muestra el ultimo historial guardado."
            )

        return jsonify({
            "error": "No se pudo obtener el historial",
            "detalle": str(error)
        }), 502


# =========================
# ESTADO DEL SERVIDOR
# =========================

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "finnhub_key_configured": bool(FINNHUB_API_KEY),
        "twelve_data_key_configured": bool(TWELVE_DATA_API_KEY)
    })


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
