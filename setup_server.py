import socket
import machine
import utime
import gc
import network
import os


def guarded_reset(reason=""):
    try:
        if "no_reset.flag" in os.listdir():
            try:
                print("RESET SKIPPED (no_reset.flag): {}".format(reason))
            except:
                pass
            return False
    except:
        pass

    machine.reset()
    return True

# --- Helpers ---
def log(msg):
    timestamp = utime.ticks_ms()
    print("[{:>8}ms] SETUP: {}".format(timestamp, msg))

def url_decode(s):
    # Convert + to space and decode %xx hex values
    s = s.replace('+', ' ')
    parts = s.split('%')
    res = parts[0]
    for part in parts[1:]:
        try:
            res += chr(int(part[:2], 16)) + part[2:]
        except:
            res += '%' + part
    return res.strip()

def parse_params(path):
    params = {}
    try:
        if '?' in path:
            query = path.split('?')[1].split(' ')[0]
            pairs = query.split('&')
            for pair in pairs:
                if '=' in pair:
                    key, val = pair.split('=')
                    params[key] = url_decode(val)
    except Exception as e:
        log("Parse Error: {}".format(e))
    return params

# --- HTML Templates ---
CONFIG_FORM_HTML = """HTTP/1.1 200 OK
Content-Type: text/html

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Iris Setup</title>
    <style>
        :root { --primary-color: #005A9C; --light-bg: #f7f9fc; --border-color: #e0e6ed; }
        body { font-family: sans-serif; background-color: var(--light-bg); padding: 15px; margin: 0; display: flex; justify-content: center; }
        .form-card { max-width: 500px; width: 100%; background: #fff; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-top: 6px solid var(--primary-color); }
        h1 { color: var(--primary-color); font-size: 1.5em; margin-top: 0; }
        fieldset { border: 1px solid var(--border-color); border-radius: 8px; margin-bottom: 15px; padding: 10px 15px; }
        legend { font-weight: bold; color: var(--primary-color); px: 5px; }
        .form-group { margin-bottom: 12px; }
        label { display: block; font-size: 0.85em; margin-bottom: 4px; font-weight: 600; }
        input, select { width: 100%; padding: 10px; border: 1px solid var(--border-color); border-radius: 6px; box-sizing: border-box; font-size: 16px; }
        .checkbox-group { display: flex; align-items: center; background: #f0f4f8; padding: 10px; border-radius: 6px; margin-bottom: 10px; }
        .checkbox-group input { width: auto; margin-right: 12px; transform: scale(1.4); }
        .checkbox-group label { margin-bottom: 0; font-size: 0.9em; cursor: pointer; }
        .submit-btn { background: var(--primary-color); color: white; padding: 14px; border: none; border-radius: 8px; width: 100%; font-weight: bold; font-size: 1em; cursor: pointer; margin-top: 10px; }
    </style>
</head>
<body>
<div class="form-card">
    <h1>Iris Setup Portal</h1>
    <form action="/save" method="GET">
        <fieldset>
            <legend>📡 Wi-Fi</legend>
            <div class="form-group"><label>SSID</label><input type="text" name="ssid" required></div>
            <div class="form-group"><label>Password</label><input type="password" name="pwd" required></div>
        </fieldset>
        <fieldset>
            <legend>☁️ Nightscout</legend>
            <div class="form-group"><label>URL</label><input type="url" name="ns_url" placeholder="https://..." required></div>
            <div class="form-group"><label>API Secret</label><input type="text" name="token" required></div>
            <div class="form-group"><label>Endpoint</label><input type="text" name="endpoint" value="/api/v1/entries/sgv.json?count=2"></div>
        </fieldset>
        <fieldset>
            <legend>📈 Alerts & Units</legend>
            <div class="form-group"><label>Units</label><select name="units"><option value="mmol">mmol/L</option><option value="mgdl">mg/dL</option></select></div>
            <div class="form-group"><label>High Line</label><input type="number" name="high" value="11.0" step="0.1"></div>
            <div class="form-group"><label>Low Line</label><input type="number" name="low" value="4.0" step="0.1"></div>
            <div class="form-group"><label>Stale (min)</label><input type="number" name="stale" value="7"></div>
            <div class="checkbox-group">
                <input type="checkbox" id="up" name="alert_up" value="True" checked>
                <label for="up">Yellow Arrow on Double Up</label>
            </div>
            <div class="checkbox-group">
                <input type="checkbox" id="down" name="alert_down" value="True" checked>
                <label for="down">Red Arrow on Double Down</label>
            </div>
        </fieldset>
        <button type="submit" class="submit-btn">Save & Reboot</button>
    </form>
</div>
</body>
</html>
"""

CONFIG_SAVED_HTML = """HTTP/1.1 200 OK
Content-Type: text/html

<html>
<head>
    <meta charset="UTF-8">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align:center; padding-top:100px; background-color:#f0f2f5; margin:0;">
    <div style="background:white; padding:40px; border-radius:16px; display:inline-block; box-shadow:0 10px 25px rgba(0,0,0,0.05); max-width: 320px; width: 90%;">
        
        <div style="width:60px; height:60px; background:#e8f5e9; color:#2e7d32; border-radius:50%; line-height:60px; font-size:30px; margin: 0 auto 20px auto;">
            &#10004;
        </div>

        <h1 style="color:#111827; margin:0 0 10px 0; font-size: 24px;">Success!</h1>
        
        <div style="height:2px; background:#e5e7eb; width:100%; margin: 20px 0;"></div>
        
        <p style="color:#4b5563; font-size:16px; line-height:1.5; margin:0 0 12px 0;">
            Your Iris Classic is now syncing your data and connecting to your network.
        </p>
        
        <p style="color:#1A936F; font-weight:600; font-size:15px; margin:0;">
            You may now close this window.
        </p>

    </div>
</body>
</html>
"""

# --- Server Logic ---
def run():
    # Clear radio state
    sta = network.WLAN(network.STA_IF)
    ap = network.WLAN(network.AP_IF)
    sta.active(False)
    ap.active(False)
    utime.sleep_ms(200)

    # Start Access Point
    ap.active(True)
    try:
        ap.config(essid="Iris Classic", security=0)
    except:
        ap.config(essid="Iris Classic")

    log("AP Active: {}".format(ap.ifconfig()))

    # Setup Socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(('0.0.0.0', 80))
        s.listen(1)
    except Exception as e:
        log("Bind Error: {}".format(e))
        guarded_reset("setup_server bind failed")
        return


    while True:
        gc.collect()
        cl = None
        try:
            cl, addr = s.accept()
            request = cl.recv(2048).decode('utf-8')
            if not request:
                cl.close()
                continue
            
            path = request.split(' ')[1]

            # 1. Kill Favicon requests to save memory
            if path == '/favicon.ico':
                cl.send("HTTP/1.1 404 Not Found\r\n\r\n")
                cl.close()
                continue

            # 2. Handle Save
            if path.startswith('/save'):
                params = parse_params(path)
                
                up = "True" if "alert_up" in params else "False"
                dn = "True" if "alert_down" in params else "False"
                
                with open("config.py", "w") as f:
                    f.write("WIFI_SSID = '{}'\n".format(params.get('ssid', '')))
                    f.write("WIFI_PASSWORD = '{}'\n".format(params.get('pwd', '')))
                    f.write("NS_URL = '{}'\n".format(params.get('ns_url', '').rstrip('/')))
                    f.write("API_SECRET = '{}'\n".format(params.get('token', '')))
                    f.write("API_ENDPOINT = '{}'\n".format(params.get('endpoint', '')))
                    f.write("UNITS = '{}'\n".format(params.get('units', 'mmol')))
                    f.write("THRESHOLD_LOW = {}\n".format(params.get('low', '4.0')))
                    f.write("THRESHOLD_HIGH = {}\n".format(params.get('high', '11.0')))
                    f.write("STALE_MINS = {}\n".format(params.get('stale', '7')))
                    f.write("ALERT_DOUBLE_UP = {}\n".format(up))
                    f.write("ALERT_DOUBLE_DOWN = {}\n".format(dn))
                
                cl.send(CONFIG_SAVED_HTML)
                cl.close()
                
                # Hard Reset via Watchdog
                utime.sleep(2)
                log("Rebooting...")
                guarded_reset("setup_server save")
                return

            
            # 3. Serve Form
            else:
                cl.send(CONFIG_FORM_HTML)
                cl.close()
                
        except Exception as e:
            log("Server Error: {}".format(e))
            if cl:
                try: cl.close()
                except: pass






