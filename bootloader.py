from machine import Pin
import utime

# 1. Start as an INPUT with a PULL_UP. 
# This "tugs" the pin to 3.3V (OFF) without the Pico actively driving it yet.
BUZ = Pin(17, Pin.IN, Pin.PULL_UP)
utime.sleep_ms(10) 

# 2. Now switch to OUTPUT and immediately set the value to 1 (OFF).
# Because of the pull-up, the buzzer shouldn't have seen a "Low" signal.
BUZ.init(Pin.OUT, value=1)

import utime as time
import network
import ujson as json
import os
import gc
import machine

# ---------- Reset helper ---------

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

def log(msg):
    timestamp = time.ticks_ms()
    print("[{:>8}ms] {}".format(timestamp, msg))

def log_exc(tag, e):
    import sys
    log("{}: {}".format(tag, e))
    try:
        sys.print_exception(e)
    except:
        pass

def log_kv(k, v):
    try:
        log("{}: {}".format(k, v))
    except:
        pass


# ---------- GitHub & Paths ----------
GITHUB_USER   = "SLWRTHNU"
GITHUB_REPO   = "Iris-Classic"
GITHUB_BRANCH = "main"
API_BASE = "https://api.github.com/repos/{}/{}/contents/".format(GITHUB_USER, GITHUB_REPO)

VERSIONS_PATH = "versions.json"
LOCAL_VERSION_FILE = "local_version.txt"
DEVICE_ID_FILE     = "device_id.txt"

# ---------- Display driver ----------

YELLOW = 0xFFE0
RED    = 0xF800
GREEN  = 0x07E0
BLUE   = 0x001F
BLACK  = 0x0000
WHITE  = 0xFFFF

LOGO_FILE   = "logo.bin"
LOGO_W = 480
LOGO_H = 320
BAR_HEIGHT  = 12
Y_POS       = 229
STATUS_X    = 3

# ---------- LCD hard reset/backlight ----------
LCD_BL_PIN = 15
LCD_RST_PIN = 13
_BL_PWM = None

def _lcd_backlight_set(pct):
    # pct: 0-100
    global _BL_PWM
    from machine import Pin, PWM
    if _BL_PWM is None:
        _BL_PWM = PWM(Pin(LCD_BL_PIN))
        _BL_PWM.freq(1000)
    pct = 0 if pct < 0 else (100 if pct > 100 else pct)
    _BL_PWM.duty_u16(int(pct * 655.35))

def _lcd_hard_reset():
    from machine import Pin
    rst = Pin(LCD_RST_PIN, Pin.OUT)
    rst.value(1)
    time.sleep_ms(50)
    rst.value(0)
    time.sleep_ms(150)
    rst.value(1)
    time.sleep_ms(150)

_LCD_INSTANCE = None

def init_lcd():
    global _LCD_INSTANCE
    if _LCD_INSTANCE is not None:
        return _LCD_INSTANCE
    try:
        from display_3_5 import lcd_st7796 as LCD_Driver
        from machine import ADC, Pin
        import utime
        log("Performing Gentle Driver Init...")
        
        # Give the power rail a moment to settle
        utime.sleep_ms(100) 
        
        # Read potentiometer and set backlight to user's preference
        pot = ADC(Pin(26))
        raw = pot.read_u16()
        # Map potentiometer value to 1-100% (same formula as app_main)
        MIN_BL = 1
        MAX_BL = 100
        brightness = MIN_BL + (raw * (MAX_BL - MIN_BL) // 65535)
        _lcd_backlight_set(brightness)
        utime.sleep_ms(100)
        
        # Initialize the driver (but it won't call lcd_init yet)
        lcd = LCD_Driver()
        
        # DON'T call lcd_init() yet - we'll load the logo first
        # Then draw_boot_logo() will call show() which will display it
        
        # Give the driver a moment
        utime.sleep_ms(200)
        lcd.display_update = lcd.show
        
        _LCD_INSTANCE = lcd
        gc.collect()
        return _LCD_INSTANCE
        
    except Exception as e:
        log("LCD Init Error: {}".format(e))
        return None
    
    
def backlight_dim_early(pct=10):
    # Runs before LCD_Driver() to prevent initial full-bright flash
    global _BL_PWM
    from machine import Pin, PWM
    if _BL_PWM is None:
        _BL_PWM = PWM(Pin(LCD_BL_PIN))
        _BL_PWM.freq(1000)
    pct = 0 if pct < 0 else (100 if pct > 100 else pct)
    _BL_PWM.duty_u16(int(pct * 655.35))


# ---------- GitHub token/headers ----------
def _get_token():
    try:
        import github_token
        t = getattr(github_token, "GITHUB_TOKEN", "")
        if t:
            return t.strip()
        return ""
    except:
        return ""

def gh_api_headers_raw():
    h = {
        "User-Agent": "Pico",
        "Accept": "application/vnd.github.v3.raw",
        "X-GitHub-Api-Version": "2022-11-28",
        "Connection": "close",
    }
    token = _get_token()
    if token:
        h["Authorization"] = "Bearer " + token
    return h

def gh_contents_url(path):
    return API_BASE + path.lstrip("/") + "?ref=" + GITHUB_BRANCH

# ---------- UI helpers ----------
def draw_bottom_status(lcd, status_msg, show_id=None):
    if lcd is None:
        return

    if show_id is None:
        show_id = any(status_msg.startswith(x) for x in ["Connecting", "Connected", "ERR:", "Updating", "Saving"])

    lcd.fill_rect(0, Y_POS - 1, lcd.width, BAR_HEIGHT, WHITE)
    lcd.text(status_msg, STATUS_X, Y_POS, BLACK)

    if show_id:
        device_id = "N/A"
        try:
            if DEVICE_ID_FILE in os.listdir():
                with open(DEVICE_ID_FILE, "r") as f:
                    device_id = f.read().strip()
        except:
            pass

        id_text = "ID:{}".format(device_id)
        id_x = lcd.width - (len(id_text) * 8) - 3
        lcd.text(id_text, id_x, Y_POS, BLACK)

    # fast partial update if supported
    if hasattr(lcd, "show_rect"):
        lcd.show_rect(0, Y_POS - 1, lcd.width, BAR_HEIGHT)
    else:
        lcd.show()

def draw_boot_logo(lcd):
    if lcd is None:
        log("draw_boot_logo: lcd is None!")
        return

    # Initialize display hardware BEFORE loading logo
    log("draw_boot_logo: Calling lcd.lcd_init()...")
    lcd.lcd_init()
    log("draw_boot_logo: lcd.lcd_init() complete")

    expected = LOGO_W * LOGO_H * 2  # 307200
    try:
        st = os.stat(LOGO_FILE)
        log("draw_boot_logo: File size = {}".format(st[6]))
        if st[6] == expected:
            with open(LOGO_FILE, "rb") as f:
                f.readinto(lcd.buffer)
            log("Logo binary loaded.")
        else:
            log("draw_boot_logo: Size mismatch!")
            lcd.fill(BLACK)
    except Exception as e:
        log("Logo error: {}".format(e))
        lcd.fill(BLACK)

    gc.collect()
    log("draw_boot_logo: About to call lcd.show()...")
    lcd.show()
    log("draw_boot_logo: lcd.show() complete")
    draw_bottom_status(lcd, "Starting...")

# ---------- WiFi ----------
def load_config_wifi():
    try:
        import config
        ssid = getattr(config, "WIFI_SSID", None)
        pwd  = getattr(config, "WIFI_PASSWORD", None)
        if ssid: ssid = ssid.strip()
        if pwd:  pwd = str(pwd)
        return ssid, pwd
    except ImportError:
        return None, None
    except Exception:
        return None, None

def _clamp(n, lo, hi):
    return lo if n < lo else (hi if n > hi else n)

def _wifi_progress_pct(start_ms, timeout_sec):
    elapsed_ms = time.ticks_diff(time.ticks_ms(), start_ms)
    pct = int((elapsed_ms * 100) // (timeout_sec * 1000))
    return _clamp(pct, 0, 99)

def connect_wifi(lcd, ssid, pwd, timeout_sec=45, retries=2):
    if not ssid:
        log("WiFi Error: No SSID")
        return False

    draw_bottom_status(lcd, "Connecting")

    ap = network.WLAN(network.AP_IF)
    if ap.active():
        ap.active(False)
        time.sleep_ms(500)

    sta = network.WLAN(network.STA_IF)

    try:
        network.hostname("Iris-Classic")
    except:
        pass

    for attempt in range(1, retries + 1):
        log("WiFi Attempt {}/{}".format(attempt, retries))

        sta.active(False)
        time.sleep_ms(300)
        sta.active(True)

        try:
            sta.config(pm=0xa11140)
        except:
            pass

        sta.disconnect()
        time.sleep_ms(150)
        # REMOVE THIS LINE: if lcd: _lcd_backlight_set(10)

        sta.connect(ssid, pwd)

        t0 = time.ticks_ms()
        last_ui = t0

        while time.ticks_diff(time.ticks_ms(), t0) < timeout_sec * 1000:
            status = sta.status()

            now = time.ticks_ms()
            if time.ticks_diff(now, last_ui) >= 1000:
                last_ui = now
                pct = _wifi_progress_pct(t0, timeout_sec)
                draw_bottom_status(lcd, "Connecting {}%".format(pct), show_id=True)
                log("WiFi Status: {} ({}%)".format(status, pct))

            if sta.isconnected():
                draw_bottom_status(lcd, "Connected 100%", show_id=True)
                log("WiFi Connected! IP: " + sta.ifconfig()[0])
                # REMOVE THIS LINE: if lcd: _lcd_backlight_set(100)
                return True

            if status < 0 or status == 201:
                draw_bottom_status(lcd, "ERR: WiFi {}".format(status), show_id=True)
                log("WiFi Error: ({})".format(status))
                break

            time.sleep_ms(200)

        log("Attempt {} timed out.".format(attempt))
        time.sleep_ms(800)

    return False

# ---------- Update check ----------
def fetch_versions_json(lcd):
    import urequests as requests
    import ubinascii

    url = gh_contents_url(VERSIONS_PATH) + "&nocache={}".format(time.ticks_ms())
    r = None
    try:
        gc.collect()
        r = requests.get(url, headers=gh_api_headers_raw(), timeout=8)
        log("versions.json HTTP: {}".format(r.status_code))

        if r.status_code != 200:
            try:
                log("versions.json body (start): {}".format(r.text[:120]))
            except:
                pass
            return None

        # safest on MicroPython: use r.text (file is tiny)
        txt = r.text
        if not txt:
            log("versions.json empty body")
            return None

        # Case A: raw file content (should be {"version":...})
        try:
            data = json.loads(txt)
        except Exception as e:
            log("versions.json JSON parse failed: {}".format(e))
            log("versions.json text (start): {}".format(txt[:120]))
            return None

        # Case B: contents API metadata (has "content" base64)
        if "content" in data and "encoding" in data:
            if data.get("encoding") == "base64":
                try:
                    decoded = ubinascii.a2b_base64(data["content"])
                    data = json.loads(decoded)
                except Exception as e:
                    log("versions.json base64 decode failed: {}".format(e))
                    return None

        rv = (data.get("version") or "").strip()
        log("versions.json parsed OK. remote version='{}'".format(rv))
        return data

    except Exception as e:
        log("versions.json fetch error: {}".format(e))
        return None
    finally:
        try:
            if r:
                r.close()
        except:
            pass
        r = None
        try:
            txt = None
        except:
            pass
        try:
            data = None
        except:
            pass
        gc.collect()



def gh_download_to_file(path, out_path):
    import urequests as requests

    url = gh_contents_url(path)
    r = None
    gc.collect()
    try:
        gc.collect()
        r = requests.get(url, headers=gh_api_headers_raw(), timeout=10)

        log_kv("dl status {}".format(out_path), r.status_code)
        raw = getattr(r, "raw", None)
        log_kv("dl has raw {}".format(out_path), bool(raw))

        if r.status_code != 200 or not raw:
            return False

        # Ensure folders exist
        if "/" in out_path:
            parts = out_path.split("/")[:-1]
            cur = ""
            for p in parts:
                cur = p if cur == "" else (cur + "/" + p)
                try:
                    os.mkdir(cur)
                except:
                    pass

        with open(out_path, "wb") as f:
            while True:
                chunk = raw.read(1024)
                if not chunk:
                    break
                f.write(chunk)

        try:
            os.sync()
        except:
            pass

        return True

    except Exception as e:
        log_exc("download exception {}".format(out_path), e)
        try:
            os.remove(out_path)
        except:
            pass
        return False

    finally:
        try:
            if r:
                r.close()
        except:
            pass
        r = None
        gc.collect()



def _safe_swap(target):
    tmp = target + ".new"
    bak = target + ".old"

    # nothing to swap
    try:
        os.stat(tmp)
    except:
        return False

    # remove old backup
    try:
        os.remove(bak)
    except:
        pass

    # move current -> .old (if current exists)
    moved_old = False
    try:
        os.rename(target, bak)
        moved_old = True
    except:
        moved_old = False

    # move .new -> target
    try:
        os.rename(tmp, target)
    except:
        # rollback if we moved the old one out of the way
        if moved_old:
            try:
                os.rename(bak, target)
            except:
                pass
        return False

    # success: delete backup
    try:
        os.remove(bak)
    except:
        pass

    return True

def perform_update(vers_data, lcd):
    SKIP_ALWAYS = ("github_token.py", "config.py", "local_version.txt", "main.py")
    STAGE_ONLY  = ("bootloader.py",)

    remote_v = (vers_data.get("version") or "").strip()
    if not remote_v:
        log("versions.json missing 'version' - aborting update")
        return False

    files = vers_data.get("files", [])
    work_swap = []
    work_stage = []

    for f in files:
        p = f.get("path")
        t = f.get("target") or (p.split("/")[-1] if p else None)
        if not p or not t:
            continue
        if t in SKIP_ALWAYS:
            continue
        if t in STAGE_ONLY:
            work_stage.append((p, t))
        else:
            work_swap.append((p, t))

    if not work_swap and not work_stage:
        log("Nothing to update")
        return True

    total = len(work_swap) + len(work_stage)
    done = 0

    # 1) DOWNLOAD everything to .new
    for p, t in (work_swap + work_stage):
        done += 1
        pct = int((done * 100) / total)
        log("Downloading: {} ({}%)".format(t, pct))
        if lcd:
            draw_bottom_status(lcd, "Updating {}%".format(pct), show_id=True)

        if not gh_download_to_file(p, t + ".new"):
            log("Download failed: {}".format(t))
            return False

    try:
        os.sync()
    except:
        pass

    # 2) SWAP normal files (bootloader stays staged)
    log("Swapping files...")
    if lcd:
        draw_bottom_status(lcd, "Saving", show_id=True)

    for p, t in work_swap:
        if not _safe_swap(t):
            log("Swap failed: {}".format(t))
            return False

    # 3) Write local version
    try:
        with open(LOCAL_VERSION_FILE, "w") as f:
            f.write(remote_v)
        try:
            os.sync()
        except:
            pass
    except Exception as e:
        log("Failed writing local_version: {}".format(e))

    # 4) Reboot (bootloader.py.new applies on next boot via apply_staged_bootloader_if_present)
    log("REBOOTING NOW")
    if lcd:
        draw_bottom_status(lcd, "Restarting...", show_id=True)

    try:
        network.WLAN(network.STA_IF).active(False)
    except:
        pass

    time.sleep_ms(400)
    machine.reset()



def apply_staged_bootloader_if_present():
    try:
        if "bootloader.py.new" not in os.listdir():
            return
    except:
        return

    try:
        log("Applying new bootloader...")
        try: os.remove("bootloader.py.old")
        except: pass

        os.rename("bootloader.py", "bootloader.py.old")
        os.rename("bootloader.py.new", "bootloader.py")

        try:
            os.sync()
        except:
            pass

        time.sleep_ms(400)
        machine.reset()
    except Exception as e:
        log("Bootloader swap failed: {}".format(e))

# ---------- Minimal UI that imports fonts only when needed ----------
def show_wifi_failed(lcd):
    if lcd is None:
        return

    # Import only here (saves boot RAM)
    import config_font
    import config_font_title
    from writer import CWriter

    w_body  = CWriter(lcd, config_font, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_title = CWriter(lcd, config_font_title, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_body.set_spacing(2)
    w_title.set_spacing(2)

    lcd.fill(BLACK)

    def center_title(text, y, color=RED):
        tw = w_title.stringlen(text)
        x = max(0, (lcd.width - tw) // 2)
        w_title.setcolor(color, BLACK)
        w_title.set_textpos(lcd, y, x)
        w_title.printstring(text)

    def body_line(text, y, x=10, color=WHITE):
        w_body.setcolor(color, BLACK)
        w_body.set_textpos(lcd, y, x)
        w_body.printstring(text)

    center_title("WiFi Failed", 20, RED)

    x_num = 45
    num_prefix = "1) "
    x_text = x_num + w_body.stringlen(num_prefix)

    y = 65
    line_gap = 30
    wrap_gap = 20

    body_line("1) Power cycle", y, x_num)
    body_line("your Iris", y + wrap_gap, x_text)

    y += line_gap * 2
    body_line("2) Power cycle", y, x_num)
    body_line("your router", y + wrap_gap, x_text)

    y += line_gap * 2
    body_line("3) Factory Reset", y, x_num)
    body_line("to reconfigure", y + wrap_gap, x_text)

    lcd.show()
    gc.collect()

# ---------- Setup mode (imports only when needed) ----------
def run_setup_mode(lcd):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid="Iris Classic", security=0)
    ip = "192.168.4.1"

    import config_font
    from writer import CWriter

    w_setup = CWriter(lcd, config_font, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_setup.set_spacing(2)
    lcd.fill(BLACK)

    def print_safe(text, y, x_val, color):
        tw = w_setup.stringlen(text)
        final_x = max(0, (lcd.width - tw) // 2) if x_val == -1 else x_val
        w_setup.setcolor(color, BLACK)
        w_setup.set_textpos(lcd, y, final_x)
        w_setup.printstring(text)

    print_safe("Iris Setup", 20, -1, YELLOW)
    print_safe("1) Connect to WiFi:", 80, 60, WHITE)
    print_safe("Iris Classic", 110, 90, YELLOW)
    print_safe("2) Visit in browser:", 160, 60, WHITE)
    print_safe("{}".format(ip), 190, 90, YELLOW)

    lcd.show()
    gc.collect()

    import setup_server
    setup_server.run()

# In bootloader.py, add this helper or call it before app_main.main(lcd)
def release_bootloader_resources():
    global _LCD_INSTANCE, _BL_PWM
    if _LCD_INSTANCE is not None:
        for attr in ['buffer', 'img', 'mv', 'framebuf', '_buf']:
            if hasattr(_LCD_INSTANCE, attr):
                setattr(_LCD_INSTANCE, attr, None)
    _LCD_INSTANCE = None
    _BL_PWM = None
    gc.collect()



# ---------- Runner ----------
def main():
    global _LCD_INSTANCE, _BL_PWM

    apply_staged_bootloader_if_present()

    # Show logo immediately on boot
    lcd = init_lcd()
    draw_boot_logo(lcd)

    # Connect WiFi WITH lcd so status bar updates over the logo
    ssid, pwd = load_config_wifi()
    connected = False
    if ssid:
        connected = connect_wifi(lcd, ssid, pwd)

    if not connected:
        show_wifi_failed(lcd)
        return

    # Optional: update check (keep as-is)
    v_data = fetch_versions_json(lcd)

    # --- CLEANUP: hand off framebuffer ONLY ---
    saved_fb = None
    if _LCD_INSTANCE:
        saved_fb = _LCD_INSTANCE.buffer
        _LCD_INSTANCE = None

    _BL_PWM = None
    gc.collect(); gc.collect()

    import app_main
    app_main.main(framebuffer=saved_fb)


        
if __name__ == "__main__":
    main()


