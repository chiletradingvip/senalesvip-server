from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import hashlib
import hmac
import requests
import json
import os
from datetime import datetime, timedelta

# ============================================
# CONFIGURACIÓN
# ============================================
import os
FLOW_API_KEY    = os.environ.get("FLOW_API_KEY", "")
FLOW_SECRET_KEY = os.environ.get("FLOW_SECRET_KEY", "")
FLOW_URL        = os.environ.get("FLOW_URL", "https://www.flow.cl/api")

BOT_TOKEN      = "8978728978:AAFRX_2NFTNlSnaY0bjoJyO8mm_DZKFwIjU"
CHAT_ID_ADMIN  = "1258182910"
GRUPO_ID       = "-1003897570737"
ARCHIVO        = "suscriptores.json"
PAGOS_PROC     = "pagos_procesados.json"
PAGINA_URL     = "https://chiletradingvip.github.io/Senalesvip"
NGROK_URL      = os.environ.get("NGROK_URL", "https://senalesvip-server.onrender.com")

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    return response

# ============================================
# FUNCIONES FLOW
# ============================================
def firmar_parametros(params):
    keys = sorted(params.keys())
    to_sign = ""
    for key in keys:
        to_sign += key + str(params[key])
    firma = hmac.new(
        FLOW_SECRET_KEY.encode('utf-8'),
        to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return firma

def crear_orden_flow(nombre, email, telegram, telefono, monto, order_id):
    params = {
        "apiKey":           FLOW_API_KEY,
        "amount":           str(monto),
        "commerceOrder":    str(order_id),
        "currency":         "CLP",
        "email":            email,
        "subject":          "Suscripcion VIP Senales BTC XAU Chile",
        "urlConfirmation":  f"{NGROK_URL}/flow/confirmar",
        "urlReturn":        f"{PAGINA_URL}?pago=exitoso",
        "notifyUrl":        f"{NGROK_URL}/flow/confirmar",
        "optional":         json.dumps({"telegram": telegram, "telefono": telefono, "nombre": nombre})
    }
    params["s"] = firmar_parametros(params)
    resp = requests.post(f"{FLOW_URL}/payment/create", data=params)
    data = resp.json()
    print(f"Flow respuesta: {data}")
    if data.get("url") and data.get("token"):
        return f"{data['url']}?token={data['token']}"
    return None

# ============================================
# FUNCIONES TELEGRAM
# ============================================
def enviar_mensaje(chat_id, texto):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
    )

def crear_link_invitacion():
    expira = int((datetime.now() + timedelta(hours=24)).timestamp())
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink",
        json={"chat_id": GRUPO_ID, "expire_date": expira, "member_limit": 1}
    )
    data = resp.json()
    if data.get("ok"):
        return data["result"]["invite_link"]
    return None

# ============================================
# FUNCIONES SUSCRIPTORES
# ============================================
def cargar_procesados():
    if os.path.exists(PAGOS_PROC):
        with open(PAGOS_PROC, 'r') as f:
            return json.load(f)
    return []

def guardar_procesado(order_id):
    pagos = cargar_procesados()
    pagos.append(str(order_id))
    with open(PAGOS_PROC, 'w') as f:
        json.dump(pagos, f)

def cargar_suscriptores():
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def guardar_suscriptores(s):
    with open(ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def registrar_suscriptor(nombre, telegram, email, telefono, monto, order_id):
    if str(order_id) in cargar_procesados():
        print(f"Pago {order_id} ya procesado")
        return
    hoy = datetime.now()
    vencimiento = hoy + timedelta(days=30)
    link = crear_link_invitacion()
    suscriptores = cargar_suscriptores()
    suscriptores.append({
        "nombre": nombre, "usuario": telegram,
        "email": email, "telefono": telefono,
        "fecha_pago": hoy.strftime('%d/%m/%Y'),
        "fecha_vencimiento": vencimiento.strftime('%d/%m/%Y'),
        "monto": monto, "activo": True, "order_id": str(order_id)
    })
    guardar_suscriptores(suscriptores)
    guardar_procesado(order_id)

    msg  = f"✅ *Nuevo pago Flow recibido*\n\n"
    msg += f"👤 {nombre}\n📱 Telegram: {telegram}\n"
    msg += f"📞 Teléfono: {telefono}\n📧 Email: {email}\n"
    msg += f"💰 Monto: ${monto:,} CLP\n📅 Vence: {vencimiento.strftime('%d/%m/%Y')}\n"
    if link:
        msg += f"\n🔗 *Link de acceso:*\n{link}\n⚠️ Un solo uso, 24 horas"
    enviar_mensaje(CHAT_ID_ADMIN, msg)
    print(f"✅ Suscriptor registrado: {nombre}")

# ============================================
# ENDPOINTS
# ============================================
@app.route('/flow/iniciar', methods=['GET'])
def iniciar_pago():
    try:
        nombre   = request.args.get('nombre', 'Cliente')
        email    = request.args.get('email', '')
        telegram = request.args.get('telegram', '')
        telefono = request.args.get('telefono', '')
        order_id = int(datetime.now().timestamp())
        url_pago = crear_orden_flow(nombre, email, telegram, telefono, 25000, order_id)
        if url_pago:
            return redirect(url_pago)
        return "Error al crear el pago. Vuelve e intenta nuevamente.", 500
    except Exception as e:
        print(f"Error iniciar: {e}")
        return f"Error: {str(e)}", 500

@app.route('/flow/confirmar', methods=['POST', 'GET'])
def confirmar_pago():
    try:
        token = request.form.get('token') or request.args.get('token')
        
        # Si no hay token, redirigir a página de éxito
        if not token:
            return redirect("https://chiletradingvip.github.io/Senalesvip?pago=exitoso")
        
        params = {"apiKey": FLOW_API_KEY, "token": token}
        params["s"] = firmar_parametros(params)
        resp = requests.get(f"{FLOW_URL}/payment/getStatus", params=params)
        pago = resp.json()
        print(f"Estado Flow: {pago}")
        
        if pago.get('status') == 2:
            order_id = pago.get('commerceOrder')
            monto    = int(float(pago.get('amount', 25000)))
            email    = pago.get('payer', '')
            opcional = pago.get('optional', {})
            if isinstance(opcional, str):
                opcional = json.loads(opcional)
            nombre   = opcional.get('nombre', 'Nuevo Suscriptor')
            telegram = opcional.get('telegram', 'Sin usuario')
            telefono = opcional.get('telefono', 'Sin teléfono')
            registrar_suscriptor(nombre, telegram, email, telefono, monto, order_id)
        
        # Si llegó por GET (cliente siendo redirigido), ir a página de éxito
        if request.method == 'GET':
            return redirect("https://chiletradingvip.github.io/Senalesvip?pago=exitoso")
        
        return "ok", 200
    except Exception as e:
        print(f"Error confirmar: {e}")
        # Siempre redirigir al cliente si es GET
        if request.method == 'GET':
            return redirect("https://chiletradingvip.github.io/Senalesvip?pago=exitoso")
        return "ok", 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "running", "endpoints": ["/flow/iniciar", "/flow/confirmar"]}), 200

if __name__ == '__main__':
    print("✅ Servidor Flow iniciado en puerto 5000")
    print(f"🔗 Endpoints disponibles:")
    print(f"   GET  {NGROK_URL}/flow/iniciar")
    print(f"   POST {NGROK_URL}/flow/confirmar")
    app.run(host='0.0.0.0', port=5000, debug=True)
