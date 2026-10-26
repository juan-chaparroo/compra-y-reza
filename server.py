
import os
import json
import time
import requests

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

# Carpeta principal del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Flask sirve CSS, JavaScript e imágenes desde la carpeta del proyecto.
app = Flask(
    __name__,
    static_folder=BASE_DIR,
    static_url_path=""
)

CORS(app)

# Configuración de Finnhub
API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
BASE_URL = "https://finnhub.io/api/v1"

# Configuración de la caché del historial
HISTORY_CACHE_SECONDS = 24 * 60 * 60
HISTORY_CACHE_DIR = os.path.join(BASE_DIR, "cache", "history")

os.makedirs(HISTORY_CACHE_DIR, exist_ok=True)


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
# CACHÉ DEL HISTORIAL
# =========================

def history_cache_path(symbol):
    return os.path.join(HISTORY_CACHE_DIR, f"{symbol}.json")


def load_history_cache(symbol):
    path = history_cache_path(symbol)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as file:
            cached = json.load(file)

        if "timestamp" in cached and "data" in cached:
            return cached

    except (OSError, json.JSONDecodeError) as e:
        print(f"Error leyendo caché de {symbol}: {e}")

    return None


def save_history_cache(symbol, data):
    path = history_cache_path(symbol)

    cached = {
        "timestamp": time.time(),
        "data": data
    }

    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(cached, file, ensure_ascii=False)

    except OSError as e:
        print(f"Error guardando caché de {symbol}: {e}")


# =========================
# CONSULTAS A FINNHUB
# =========================

def fetch_finnhub(endpoint, params):
    if not API_KEY:
        return None, (
            jsonify({"error": "Falta configurar FINNHUB_API_KEY"}),
            503
        )

    params = params.copy()
    params["token"] = API_KEY

    try:
        response = requests.get(
            f"{BASE_URL}/{endpoint}",
            params=params,
            timeout=15
        )
        response.raise_for_status()
        return response.json(), None

    except requests.HTTPError as e:
        status = (
            e.response.status_code
            if e.response is not None
            else None
        )

        detalle = (
            e.response.text[:500]
            if e.response is not None
            else str(e)
        )

        print(f"Error HTTP de Finnhub ({status}): {detalle}")

        return None, (
            jsonify({
                "error": "Finnhub rechazó la consulta",
                "status": status,
                "detalle": detalle
            }),
            502
        )

    except requests.RequestException as e:
        print(f"Error de conexión con Finnhub: {e}")

        return None, (
            jsonify({
                "error": "No se pudo conectar con el proveedor de datos"
            }),
            502
        )


# =========================
# COTIZACIÓN ACTUAL
# =========================

@app.get("/api/quote/<symbol>")
def quote(symbol):
    symbol = symbol.upper()

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
# HISTORIAL CON ALPHA VANTAGE
# =========================

@app.get("/api/history/<symbol>")
def history(symbol):
    symbol = symbol.upper()
    cached = load_history_cache(symbol)

    # Usar la caché si tiene menos de 24 horas.
    if (
        cached
        and time.time() - cached["timestamp"] < HISTORY_CACHE_SECONDS
    ):
        return jsonify(cached["data"])

    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()

    if not api_key:
        if cached:
            return jsonify(cached["data"])

        return jsonify({
            "error": "Falta configurar ALPHA_VANTAGE_API_KEY"
        }), 503

    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": api_key
            },
            timeout=20
        )

        response.raise_for_status()
        data = response.json()

        if "Error Message" in data:
            if cached:
                return jsonify(cached["data"])

            return jsonify({
                "error": "Alpha Vantage rechazó el símbolo",
                "detalle": data["Error Message"]
            }), 400

        if "Note" in data or "Information" in data:
            if cached:
                print(f"Usando historial guardado de {symbol}")
                return jsonify(cached["data"])

            return jsonify({
                "error": "Alpha Vantage informó un límite o restricción",
                "detalle": data.get("Note") or data.get("Information")
            }), 429

        series = data.get("Time Series (Daily)")

        if not series:
            if cached:
                return jsonify(cached["data"])

            return jsonify({
                "error": "No se recibieron datos históricos",
                "detalle": "Revisá la clave y la disponibilidad del símbolo."
            }), 502

        fechas = sorted(series.keys())

        resultado = {
            "symbol": symbol,
            "labels": fechas,
            "values": [
                float(series[fecha]["4. close"])
                for fecha in fechas
            ]
        }

        save_history_cache(symbol, resultado)

        return jsonify(resultado)

    except requests.RequestException as e:
        print(f"Error consultando Alpha Vantage: {e}")

        if cached:
            return jsonify(cached["data"])

        return jsonify({
            "error": "No se pudo conectar con Alpha Vantage"
        }), 502


# =========================
# ESTADO DEL SERVIDOR
# =========================

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "finnhub_key_configured": bool(API_KEY),
        "alphavantage_key_configured": bool(
            os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
        )
    })


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
