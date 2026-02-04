from machine import Pin
import utime

# 1. Start as an INPUT with a PULL_UP. 
# This "tugs" the pin to 3.3V (OFF) without the Pico actively driving it yet.
BUZ = Pin(17, Pin.IN, Pin.PULL_UP)
utime.sleep_ms(10) 

# 2. Now switch to OUTPUT and immediately set the value to 1 (OFF).
# Because of the pull-up, the buzzer shouldn't have seen a "Low" signal.
BUZ.init(Pin.OUT, value=1)

import gc
import utime
import network
import uasyncio as asyncio

gc.collect()

from machine import WDT, reset, ADC, Pin


DEBUG = False  # set True when debugging

if DEBUG:
    def logf(fmt, *args):
        free = gc.mem_free()
        ts = utime.ticks_ms()
        msg = fmt % args if args else fmt
        print("[{:>8}ms] [RAM Free: {:>5}B] {}".format(ts, free, msg))
else:
    def logf(fmt, *args):
        pass

def log(msg):
    logf("%s", msg)



# ---------- Config ----------
import config

def cfg(name, default):
    return getattr(config, name, default)

WIFI_SSID     = cfg("WIFI_SSID", "")
WIFI_PASSWORD = cfg("WIFI_PASSWORD", "")
NS_URL        = cfg("NS_URL", "")
NS_TOKEN      = cfg("API_SECRET", "")
API_ENDPOINT  = cfg("API_ENDPOINT", "/api/v1/entries/sgv.json?count=2")
DISPLAY_UNITS = cfg("UNITS", "mmol")

LOW_THRESHOLD  = float(cfg("THRESHOLD_LOW", 4.0))
HIGH_THRESHOLD = float(cfg("THRESHOLD_HIGH", 11.0))
STALE_MIN      = int(cfg("STALE_MINS", 7))

ALERT_DOUBLE_UP   = cfg("ALERT_DOUBLE_UP", True)
ALERT_DOUBLE_DOWN = cfg("ALERT_DOUBLE_DOWN", True)

UNIX_2000_OFFSET = 946684800
last = None          # replaces main() local "last"
last_lcd = None      # optional, not required



# ---------- Display driver ----------
from display_3_5 import lcd_st7796 as LCD_Driver

# ---------- Fonts / Writer ----------
from writer import CWriter
import small_font as font_small
import age_small_font as age_font_small
import arrows_font as font_arrows
import heart as font_heart
import delta as font_delta
import battery_font
import big_digits
from big_digits_draw import draw_big_text

# ---------- Colors ----------
YELLOW = 0xFFE0
RED    = 0xF800
GREEN  = 0x07E0
BLACK  = 0x0000
WHITE  = 0xFFFF

hb_state = True
wdt = None

# IMPORTANT: you need sta defined before connect_wifi() uses it
sta = None

# --- Battery Config ---
last_usb = None
power_change_until = 0
POWER_CHANGE_COOLDOWN_MS = 2500


def is_usb_connected():
    try:
        return Pin("WL_GPIO2", Pin.IN).value()
    except:
        return Pin(24, Pin.IN).value()


# --- TEMP: Stop Buzzer Button ---
# Wire: button between GP2 and GND (active-low), using internal pull-up.
BTN_STOP_PIN = 2
BTN_STOP = Pin(BTN_STOP_PIN, Pin.IN, Pin.PULL_UP)

buzzer_stop_requested = False

def request_buzzer_stop():
    global buzzer_mode, buzzer_snooze_until, last_mild_beep_time

    # If no alert is active, button does nothing
    if buzzer_mode == 0:
        return

    # Stop everything
    BUZ.value(1)
    buzzer_mode = 0

    now = utime.ticks_ms()

    # Snooze ALL alerts for 10 minutes
    buzzer_snooze_until = utime.ticks_add(now, BUZZER_SNOOZE_MS)

    # Restart mild timer so it won't fire immediately after snooze ends
    last_mild_beep_time = now




# --- Logo Config ---
LOGO_FILE = "logo.bin"
LOGO_W = 480
LOGO_H = 320

def show_logo(lcd):
    expected = LOGO_W * LOGO_H * 2  # 307200
    try:
        import os
        st = os.stat(LOGO_FILE)
        if st[6] == expected:
            with open(LOGO_FILE, "rb") as f:
                f.readinto(lcd.buffer)
            lcd.show()
            return True
    except:
        pass
    return False


# ---------- Helpers ----------

def _show_rect(lcd, x, y, w, h):
    global _DIRTY
    if _BATCHING:
        _DIRTY = _union_rect(_DIRTY, (x, y, w, h))
        return

    if hasattr(lcd, "show_rect"):
        lcd.show_rect(x, y, w, h)
    else:
        lcd.show()




wifi_ok = False

# ---------- Batched screen flush ----------
_BATCHING = False
_DIRTY = None  # (x, y, w, h)

def _begin_batch():
    global _BATCHING, _DIRTY
    _BATCHING = True
    _DIRTY = None

def _end_batch(lcd):
    global _BATCHING, _DIRTY
    _BATCHING = False
    if not _DIRTY:
        return
    x, y, w, h = _DIRTY
    if hasattr(lcd, "show_rect"):
        lcd.show_rect(x, y, w, h)
    else:
        lcd.show()
    _DIRTY = None


def connect_wifi(ssid, password, max_attempts=2):
    import utime
    import network

    global sta

    # Hard reset the STA interface to avoid EPERM
    if sta is not None:
        try:
            sta.active(False)
            utime.sleep_ms(200)
        except Exception:
            pass

    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    utime.sleep_ms(200)

    for attempt in range(1, max_attempts + 1):
        log("WiFi Attempt {}/{}".format(attempt, max_attempts))

        try:
            if sta.isconnected():
                log("WiFi already connected. IP: {}".format(sta.ifconfig()[0]))
                return True

            sta.connect(ssid, password)

            start = utime.ticks_ms()
            while not sta.isconnected():
                status = sta.status()
                elapsed = utime.ticks_diff(utime.ticks_ms(), start)

                pct = min(99, int((elapsed / 50000) * 100))
                log("WiFi Status: {} ({}%)".format(status, pct))

                if elapsed > 50000:
                    break

                utime.sleep_ms(1000)

            if sta.isconnected():
                log("WiFi Connected! IP: {}".format(sta.ifconfig()[0]))
                return True

        except OSError as e:
            log("WiFi OSError: {}".format(e))

        try:
            sta.disconnect()
        except Exception:
            pass
        utime.sleep_ms(800)

    log("WiFi Failed after {} attempts".format(max_attempts))
    return False

pot = ADC(Pin(26))  # GP26 / ADC0

MIN_BL = 1
MAX_BL = 100

def _map_u16_to_percent(raw):
    return MIN_BL + (raw * (MAX_BL - MIN_BL) // 65535)

async def task_dimmer(lcd):
    # Initial set (no lag on boot)
    raw = pot.read_u16()
    smoothed = raw
    current = _map_u16_to_percent(raw)
    lcd.bl_ctrl(current)

    # Tune these:
    SLOW_ALPHA_NUM = 1
    SLOW_ALPHA_DEN = 12     # smooth when steady
    FAST_ALPHA_NUM = 1
    FAST_ALPHA_DEN = 3      # quick response when knob moves

    SLOW_STEP = 2
    FAST_STEP = 8

    MOVE_THRESHOLD = 900    # u16 delta that counts as "real movement"
    DEAD_BAND = 0           # start immediately (no waiting)
    POLL_MS = 15            # faster polling feels instant

    last_raw = raw

    while True:
        raw = pot.read_u16()
        d = abs(raw - last_raw)
        last_raw = raw

        # If the knob moved, respond faster; otherwise, stay smooth.
        if d > MOVE_THRESHOLD:
            a_num, a_den = FAST_ALPHA_NUM, FAST_ALPHA_DEN
            max_step = FAST_STEP
        else:
            a_num, a_den = SLOW_ALPHA_NUM, SLOW_ALPHA_DEN
            max_step = SLOW_STEP

        # EMA smoothing
        smoothed = smoothed + (raw - smoothed) * a_num // a_den
        target = _map_u16_to_percent(smoothed)

        if abs(target - current) <= DEAD_BAND:
            await asyncio.sleep_ms(POLL_MS)
            continue

        # rate limit
        if target > current:
            current = min(current + max_step, target)
        else:
            current = max(current - max_step, target)

        lcd.bl_ctrl(current)
        await asyncio.sleep_ms(POLL_MS)


def now_unix_s():
    t = utime.time()
    return t + UNIX_2000_OFFSET if t < 1200000000 else t

def ntp_sync():
    try:
        import ntptime
        before = now_unix_s()
        ntptime.settime()
        after = now_unix_s()
        drift = after - before
        log("NTP Sync Successful. Drift: {}s".format(drift))
        return True
    except Exception as e:
        log("NTP Sync Failed: {}".format(e))
        return False


def ensure_count2(endpoint: str) -> str:
    # Force count=2 exactly (Nightscout uses count=)
    if "count=" in endpoint:
        # replace any count=NUMBER with count=2
        import re
        return re.sub(r"count=\d+", "count=2", endpoint)
    joiner = "&" if "?" in endpoint else "?"
    return endpoint + joiner + "count=2"


def fetch_ns_text():
    import usocket
    import network
    import utime
    import ssl

    global wdt
    gc.collect()
    # Must have WiFi before DNS/getaddrinfo, or it can block forever
    try:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active() or not wlan.isconnected():
            log("NS skip: WiFi not connected")
            return None
    except Exception as e:
        log("NS skip: WiFi check error: {}".format(e))
        return None

    if not NS_URL:
        log("NS_URL is blank")
        return None

    # Build URL (may be http or https depending on NS_URL)
    url = NS_URL + ensure_count2(API_ENDPOINT)
    log("NS url: {}".format(url))

    MIN_FREE = 20000 # Reduced slightly to be less aggressive
    free = gc.mem_free()
    if free < MIN_FREE:
        log("NS skip: low RAM (need >= {}, have {})".format(MIN_FREE, free))
        return None
    

    def _parse_url(u):
        # Returns (scheme, host, port, path)
        if u.startswith("http://"):
            scheme = "http"
            rest = u[7:]
            default_port = 80
        elif u.startswith("https://"):
            scheme = "https"
            rest = u[8:]
            default_port = 443
        else:
            raise ValueError("URL must start with http:// or https://")

        # split host[:port] and /path
        if "/" in rest:
            hostport, path = rest.split("/", 1)
            path = "/" + path
        else:
            hostport = rest
            path = "/"

        if ":" in hostport:
            host, port_s = hostport.split(":", 1)
            port = int(port_s)
        else:
            host = hostport
            port = default_port

        return scheme, host, port, path

    def _one_request(u, max_body=2048):
        # Returns (status_code, headers_dict, body_bytes)
        scheme, host, port, path = _parse_url(u)

        s = None
        try:
            if wdt:
                wdt.feed()
            gc.collect()
            log("Before CONNECT | free={}".format(gc.mem_free()))

            addr = usocket.getaddrinfo(host, port)[0][-1]
            s = usocket.socket()
            s.settimeout(2)
            s.connect(addr)

            # TLS if https
            if scheme == "https":
                try:
                    import ssl
                    s = ssl.wrap_socket(s, server_hostname=host)
                except Exception as e:
                    log("TLS wrap error: {}".format(e))
                    try:
                        s.close()
                    except:
                        pass
                    return None, None, None

            if wdt:
                wdt.feed()

            headers = [
                "GET {} HTTP/1.1".format(path),
                "Host: {}".format(host),
                "Accept: application/json",
                "Connection: close",
            ]
            if NS_TOKEN:
                headers.append("api-secret: {}".format(NS_TOKEN))
            req = "\r\n".join(headers) + "\r\n\r\n"
            s.send(req.encode("utf-8"))
            log("After SEND | free={}".format(gc.mem_free()))

            # Read response with a cap (avoid ENOMEM)
            log("Before RECV | free={}".format(gc.mem_free()))
            buf = bytearray()
            CAP = max_body + 1024  # header + body cap
            t_recv0 = utime.ticks_ms()
            RECV_BUDGET_MS = 1200

            while True:
                if wdt:
                    wdt.feed()
                if utime.ticks_diff(utime.ticks_ms(), t_recv0) > RECV_BUDGET_MS:
                    log("RECV budget hit, aborting read")
                    break
                chunk = s.recv(256)
                if not chunk:
                    break
                if (len(buf) + len(chunk)) > CAP:
                    # append only what fits, then stop
                    take = CAP - len(buf)
                    if take > 0:
                        buf.extend(chunk[:take])
                    break
                buf.extend(chunk)

            log("After  RECV | free={} | bytes={}".format(gc.mem_free(), len(buf)))

        except Exception as e:
            log("Fetch error: {}".format(e))
            return None, None, None

        finally:
            try:
                if s:
                    s.close()
            except:
                pass

        # Parse status line + headers/body split
        raw = bytes(buf)
        sep = raw.find(b"\r\n\r\n")
        if sep == -1:
            log("NS bad HTTP response (no header/body split)")
            return None, None, None

        head = raw[:sep].decode("utf-8", "ignore")
        body = raw[sep + 4 : sep + 4 + max_body]

        # status code
        status = None
        try:
            status_line = head.split("\r\n", 1)[0]
            parts = status_line.split(" ")
            if len(parts) >= 2:
                status = int(parts[1])
            log("NS status line: {}".format(status_line))
        except Exception as e:
            log("NS status parse error: {}".format(e))

        # headers dict (lowercased keys)
        hdrs = {}
        try:
            for line in head.split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    hdrs[k.strip().lower()] = v.strip()
        except:
            pass

        # small preview for debugging
        try:
            preview = head[:240].replace("\r", "\\r").replace("\n", "\\n")
            log("NS resp preview: {}".format(preview))
        except:
            pass

        log("After READ | free={} | body_bytes={}".format(gc.mem_free(), len(body)))
        return status, hdrs, body

    try:
        # 1) first request (may redirect)
        status, hdrs, body = _one_request(url, max_body=2048)
        if status is None:
            return None

        # follow one redirect
        if status in (301, 302, 303, 307, 308):
            loc = (hdrs or {}).get("location")
            if not loc:
                log("NS redirect with no Location header")
                return None
            log("NS redirect to: {}".format(loc))
            status, hdrs, body = _one_request(loc, max_body=2048)
            if status is None:
                return None

        if status != 200:
            log("NS HTTP not OK: {}".format(status))
            return None

        if not body:
            return None

        return body.decode("utf-8", "ignore")

    finally:
        gc.collect()
        log("NS fetch end   | free={}".format(gc.mem_free()))



def mgdl_to_units(val_mgdl: float) -> float:
    try:
        if str(DISPLAY_UNITS).lower() == "mgdl":
            return float(val_mgdl)
        return round(float(val_mgdl) / 18.0, 1)
    except:
        return 0.0

def direction_to_arrow(direction: str) -> str:
    return {
        "Flat": "B",
        "SingleUp": "G",
        "DoubleUp": "GG",
        "SingleDown": "H",
        "DoubleDown": "HH",
        "FortyFiveUp": "D",
        "FortyFiveDown": "F",
        "NOT COMPUTABLE": "--",
        "NONE": "--",
    }.get(direction or "NONE", "")

def _find_int_after(s, key, start=0):
    i = s.find(key, start)
    if i < 0:
        return None, -1
    i += len(key)

    # Allow spaces, tabs, CR, LF
    while i < len(s) and s[i] in " \t\r\n":
        i += 1

    j = i

    # Optional minus sign
    if j < len(s) and s[j] == "-":
        j += 1

    while j < len(s) and s[j].isdigit():
        j += 1

    if j == i or (j == i + 1 and s[i] == "-"):
        return None, -1

    return int(s[i:j]), j


def _find_str_after(s, key, start=0):
    i = s.find(key, start)
    if i < 0:
        return None, -1
    i += len(key)

    # Allow spaces, tabs, CR, LF before the quote
    while i < len(s) and s[i] in " \t\r\n":
        i += 1

    q1 = s.find('"', i)
    if q1 < 0:
        return None, -1
    q2 = s.find('"', q1 + 1)
    if q2 < 0:
        return None, -1

    return s[q1 + 1:q2], q2 + 1


def parse_entries_from_text(txt):
    if not txt:
        return None

    cur_sgv, p = _find_int_after(txt, '"sgv":')
    if cur_sgv is None:
        return None

    cur_mills, p2 = _find_int_after(txt, '"mills":', p)
    if cur_mills is None:
        cur_mills, _ = _find_int_after(txt, '"date":', p)

    direction, p3 = _find_str_after(txt, '"direction":', p)

    prev_sgv, _ = _find_int_after(txt, '"sgv":', p)

    delta_units = None
    if prev_sgv is not None:
        diff = float(cur_sgv) - float(prev_sgv)
        if str(DISPLAY_UNITS).lower() == "mgdl":
            delta_units = diff
        else:
            delta_units = diff / 18.0

    return {
        "bg": mgdl_to_units(cur_sgv),
        "time_ms": int(cur_mills or 0),
        "direction": direction or "NONE",
        "arrow": direction_to_arrow(direction),
        "delta": delta_units,
    }

def fmt_bg(bg_val) -> str:
    if bg_val is None:
        return "---"
    try:
        if str(DISPLAY_UNITS).lower() == "mgdl":
            return str(int(round(bg_val)))
        return "{:.1f}".format(float(bg_val))
    except:
        return "ERR"

def fmt_delta(delta_val) -> str:
    if delta_val is None:
        return ""
    return "{:+.0f}".format(delta_val) if str(DISPLAY_UNITS).lower() == "mgdl" else "{:+.1f}".format(delta_val)

# ============================
# PARTIAL UPDATE DRAW SECTION
# ============================

class ScreenState:
    def __init__(self):
        self.age_text = None
        self.age_color = None

        self.bg_text = None
        self.bg_color = None

        self.arrow_text = None
        self.arrow_color = None

        self.delta_text = None
        self.heart_on = None
        self.batt_x = None
        self.batt_pos = None


        self.last_have_data = False



def _clear_rect(lcd, x, y, w, h, color=BLACK):
    if x < 0:
        w += x
        x = 0
    if y < 0:
        h += y
        y = 0
    if x + w > lcd.width:
        w = lcd.width - x
    if y + h > lcd.height:
        h = lcd.height - y
    if w <= 0 or h <= 0:
        return
    lcd.fill_rect(x, y, w, h, color)

def _bbox_text(wr, text, x, y, pad=2):
    tw = wr.stringlen(text)
    th = wr.font.height()
    return (x - pad, y - pad, tw + pad * 2, th + pad * 2)


def _union_rect(r1, r2):
    # rect = (x, y, w, h)
    if not r1:
        return r2
    if not r2:
        return r1
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    ax1, ay1, ax2, ay2 = x1, y1, x1 + w1, y1 + h1
    bx1, by1, bx2, by2 = x2, y2, x2 + w2, y2 + h2
    ux1 = ax1 if ax1 < bx1 else bx1
    uy1 = ay1 if ay1 < by1 else by1
    ux2 = ax2 if ax2 > bx2 else bx2
    uy2 = ay2 if ay2 > by2 else by2
    return (ux1, uy1, ux2 - ux1, uy2 - uy1)



def _draw_age_if_changed(lcd, w_age_small, new_text, new_color, st, y_age):
    W = lcd.width
    new_w = w_age_small.stringlen(new_text)
    x_new = (W - new_w) // 2

    if st.age_text == new_text and st.age_color == new_color:
        return

    old_bbox = None
    if st.age_text is not None:
        old_w = w_age_small.stringlen(st.age_text)
        x_old = (W - old_w) // 2
        old_bbox = _bbox_text(w_age_small, st.age_text, x_old, y_age, pad=3)

    new_bbox = _bbox_text(w_age_small, new_text, x_new, y_age, pad=3)
    dirty = _union_rect(old_bbox, new_bbox)

    # One clear + draw, then ONE flush
    _clear_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3], BLACK)

    w_age_small.setcolor(new_color, BLACK)
    w_age_small.set_textpos(lcd, y_age, x_new)
    w_age_small.printstring(new_text)

    _show_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3])

    st.age_text = new_text
    st.age_color = new_color


def _draw_heart_if_changed(lcd, w_heart, heart_on, st, x_heart, y_heart, pad=2):
    if st.heart_on == heart_on:
        return

    heart_w = w_heart.stringlen("T")
    heart_h = w_heart.font.height()

    dirty = (x_heart - pad, y_heart - pad, heart_w + pad * 2, heart_h + pad * 2)

    _clear_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3], BLACK)

    if heart_on:
        w_heart.setcolor(RED, BLACK)
        w_heart.set_textpos(lcd, y_heart, x_heart)
        w_heart.printstring("T")

    _show_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3])
    st.heart_on = heart_on


def _big_text_width(s, spacing=2):
    w = 0
    for ch in s:
        g = big_digits.GLYPHS.get(ch)
        if g:
            w += g[0] + spacing
    return max(0, w - spacing)

def _draw_bg_if_changed(lcd, new_text, new_color, st, y_bg):
    W = lcd.width
    H = big_digits.HEIGHT
    spacing = 2

    new_w = _big_text_width(new_text, spacing=spacing)
    x_new = (W - new_w) // 2

    if st.bg_text == new_text and st.bg_color == new_color:
        return

    old_bbox = None
    if st.bg_text is not None:
        old_w = _big_text_width(st.bg_text, spacing=spacing)
        x_old = (W - old_w) // 2
        old_bbox = (x_old - 6, y_bg - 6, old_w + 12, H + 12)

    new_bbox = (x_new - 6, y_bg - 6, new_w + 12, H + 12)
    dirty = _union_rect(old_bbox, new_bbox)

    # Clear the union area once
    _clear_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3], BLACK)

    # Draw AND flush once (draw_big_text flushes)
    draw_big_text(lcd, new_text, x_new, y_bg, fg=new_color, bg=BLACK, spacing=spacing, flush=False)
    # Mark the dirty area so the final batch flush updates it
    _show_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3])


    st.bg_text = new_text
    st.bg_color = new_color





def _draw_arrow_if_changed(lcd, w_arrow, new_text, new_color, st, x_arrow, y_arrow):
    if st.arrow_text == new_text and st.arrow_color == new_color:
        return

    old_bbox = None
    if st.arrow_text is not None:
        old_bbox = _bbox_text(w_arrow, st.arrow_text, x_arrow, y_arrow, pad=3)

    new_bbox = _bbox_text(w_arrow, new_text, x_arrow, y_arrow, pad=3)
    dirty = _union_rect(old_bbox, new_bbox)

    _clear_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3], BLACK)

    w_arrow.setcolor(new_color, BLACK)
    w_arrow.set_textpos(lcd, y_arrow, x_arrow)
    w_arrow.printstring(new_text)

    _show_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3])

    st.arrow_text = new_text
    st.arrow_color = new_color


def _draw_delta_if_changed(lcd, w_small, w_delta_icon, new_delta_text, st, y_delta, right_margin=4):
    if st.delta_text == new_delta_text:
        return

    W = lcd.width
    gap = 5
    v_offset = -7

    # Compute old box
    old_bbox = None
    if st.delta_text:
        old_sign = st.delta_text[0]
        old_num = st.delta_text[1:] if len(st.delta_text) > 1 else ""

        num_w = w_small.stringlen(old_num)
        sign_w = w_delta_icon.stringlen(old_sign)
        total_w = sign_w + gap + num_w

        h = max(w_small.font.height(), w_delta_icon.font.height())
        x = W - right_margin - total_w - 6
        y = y_delta - 8
        old_bbox = (x, y, total_w + 12, h + 16)

    # If new is empty, just clear old and flush once
    if not new_delta_text:
        if old_bbox:
            _clear_rect(lcd, old_bbox[0], old_bbox[1], old_bbox[2], old_bbox[3], BLACK)
            _show_rect(lcd, old_bbox[0], old_bbox[1], old_bbox[2], old_bbox[3])
        st.delta_text = new_delta_text
        return

    # Compute new box
    sign = new_delta_text[0]
    val_num = new_delta_text[1:]

    h_small = w_small.font.height()
    h_delta = w_delta_icon.font.height()
    y_delta_centered = y_delta + (h_small - h_delta) // 2 + v_offset

    num_w = w_small.stringlen(val_num)
    sign_w = w_delta_icon.stringlen(sign)

    x_num = W - right_margin - num_w
    x_sign = x_num - sign_w - gap

    # new bbox (combined)
    total_w = (W - right_margin) - x_sign
    h = max(h_small, h_delta)
    x = x_sign - 6
    y = min(y_delta_centered, y_delta) - 8
    new_bbox = (x, y, total_w + 12, h + 16)

    dirty = _union_rect(old_bbox, new_bbox)

    _clear_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3], BLACK)

    w_delta_icon.setcolor(WHITE, BLACK)
    w_small.setcolor(WHITE, BLACK)

    w_delta_icon.set_textpos(lcd, y_delta_centered, x_sign)
    w_delta_icon.printstring(sign)

    w_small.set_textpos(lcd, y_delta, x_num)
    w_small.printstring(val_num)

    _show_rect(lcd, dirty[0], dirty[1], dirty[2], dirty[3])

    st.delta_text = new_delta_text


def draw_loading_once(lcd, writer, st):
    gc.collect()
    # DON'T clear - logo is already showing
    # Just overlay the message at the bottom
    writer.setcolor(WHITE, BLACK)
    writer.set_textpos(lcd, 280, 200)  # Bottom of screen
    writer.printstring(":)")
    
    # Only update the small region where we wrote
    if hasattr(lcd, 'show_rect'):
        lcd.show_rect(180, 270, 120, 40)
    else:
        lcd.show()

    

def draw_all_fields_if_needed(
    lcd,
    w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt,
    last, hb_state,
    st
):
    W, H = lcd.width, lcd.height
    
    y_age = 6

    if not last:
        return
        
    # If this is the first time we have data, clear the screen ONCE
    if not st.last_have_data:
        # FIRST DATA DRAW ONLY — clear logo once
        lcd.fill(BLACK)
        lcd.show()          # <<< ADD THIS LINE
        st.last_have_data = True


        # Reset state so everything redraws
        st.age_text = None
        st.bg_text = None
        st.arrow_text = None
        st.delta_text = None
        st.heart_on = None
        st.batt_x = None
        st.batt_pos = None


    # Calculate layout positions
    heart_right_margin = 10

    age_small_h = w_age_small.font.height()
    heart_h = w_heart.font.height()
    heart_w = w_heart.stringlen("T")

    x_heart = W - heart_right_margin - heart_w
    y_heart = y_age + (age_small_h - heart_h) // 4

    big_h = big_digits.HEIGHT
    small_h = w_small.font.height()
    arrow_h = w_arrow.font.height()
    bottom_h = max(small_h, arrow_h)

    y_bg = (H - big_h) // 2

    y_bottom_base = H - bottom_h - 1
    arrow_offset = -2
    x_arrow = 10
    y_arrow = (y_bottom_base + (bottom_h - arrow_h) // 2) + arrow_offset
    y_delta = y_bottom_base + (bottom_h - small_h) // 2

    # Draw all data fields
    raw_s = last["time_ms"] // 1000
    age_s = now_unix_s() - raw_s
    if age_s < 0:
        age_s = 0
    mins = int((age_s + 30) // 60)

    age_text = "{} {} ago".format(mins, "min" if mins == 1 else "mins")
    age_color = RED if mins >= STALE_MIN else WHITE

    bg_val = last["bg"]
    bg_text = fmt_bg(bg_val)

    bg_color = GREEN
    if bg_val <= LOW_THRESHOLD:
        bg_color = RED
    elif bg_val >= HIGH_THRESHOLD:
        bg_color = YELLOW

    direction = last["direction"]
    arrow_text = last["arrow"]
    arrow_color = WHITE
    if ALERT_DOUBLE_UP and direction == "DoubleUp":
        arrow_color = YELLOW
    elif ALERT_DOUBLE_DOWN and direction == "DoubleDown":
        arrow_color = RED

    delta_text = fmt_delta(last["delta"])
    
    _begin_batch()
    _draw_age_if_changed(lcd, w_age_small, age_text, age_color, st, y_age)
    _draw_heart_if_changed(lcd, w_heart, hb_state, st, x_heart, y_heart, pad=2)
    _draw_bg_if_changed(lcd, bg_text, bg_color, st, y_bg)
    _draw_arrow_if_changed(lcd, w_arrow, arrow_text, arrow_color, st, x_arrow, y_arrow)
    _draw_delta_if_changed(lcd, w_small, w_delta_icon, delta_text, st, y_delta, right_margin=4)
    _draw_batt_x_if_changed(lcd, w_batt, st, x=10, y=8)
    _end_batch(lcd)


async def task_power_monitor():
    # watches USB status and updates power_change_until
    global last_usb, power_change_until
    while True:
        now = utime.ticks_ms()
        usb_now = is_usb_connected()

        if last_usb is None:
            last_usb = usb_now
        elif usb_now != last_usb:
            last_usb = usb_now
            power_change_until = utime.ticks_add(now, POWER_CHANGE_COOLDOWN_MS)

        await asyncio.sleep_ms(100)


async def task_heartbeat(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st):
    global hb_state, last
    while True:
        hb_state = not hb_state
        draw_all_fields_if_needed(
            lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt,
            last, hb_state, st
        )
        await asyncio.sleep(1)


async def task_age_redraw(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st):
    global last, hb_state
    while True:
        if last:
            draw_all_fields_if_needed(
                lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt,
                last, hb_state, st
            )
        await asyncio.sleep(60)


async def task_glucose_fetch(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st):
    global last, hb_state, wifi_ok, power_change_until

    await asyncio.sleep(1 if wifi_ok else 60)

    while True:
        now = utime.ticks_ms()

        if utime.ticks_diff(now, power_change_until) >= 0:
            try:
                txt = fetch_ns_text()
                parsed = parse_entries_from_text(txt)
                if parsed:
                    last = parsed
                    
                    # --- ADD THIS LINE HERE ---
                    check_glucose_alerts(last["bg"]) 
                    
                    draw_all_fields_if_needed(
                        lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt,
                        last, hb_state, st
                    )
                gc.collect()
            except Exception as e:
                log("Fetch Error: {}".format(e))

        await asyncio.sleep_ms(5000)

async def task_buzzer_stop_button():
    # Simple debounce + edge detect
    last_state = 1
    stable_count = 0
    DEBOUNCE_MS = 30
    POLL_MS = 10

    while True:
        s = BTN_STOP.value()
        if s == last_state:
            stable_count += POLL_MS
        else:
            stable_count = 0
            last_state = s

        # Press detected (active-low) and stable long enough
        if s == 0 and stable_count >= DEBOUNCE_MS:
            request_buzzer_stop()
            # Wait until release so it only fires once per press
            while BTN_STOP.value() == 0:
                await asyncio.sleep_ms(20)
            stable_count = 0
            last_state = 1

        await asyncio.sleep_ms(POLL_MS)

async def task_buzzer_driver():
    global buzzer_mode, last_mild_beep_time

    while True:
        now = utime.ticks_ms()
        snoozed = utime.ticks_diff(now, buzzer_snooze_until) < 0

        # Mode 1: SEVERE solid tone (ignores snooze)
        if buzzer_mode == 1:
            BUZ.value(0)  # ON solid
            await asyncio.sleep_ms(50)
            continue

        # Mode 2: MILD pattern (respects snooze)
        if buzzer_mode == 2 and not snoozed:
            if utime.ticks_diff(now, last_mild_beep_time) >= MILD_COOLDOWN_MS:
                for _ in range(3):
                    if BTN_STOP.value() == 0:
                        request_buzzer_stop()
                        break
                    BUZ.value(0); await asyncio.sleep_ms(120)
                    BUZ.value(1); await asyncio.sleep_ms(120)
                last_mild_beep_time = utime.ticks_ms()

            BUZ.value(1)
            await asyncio.sleep_ms(100)
            continue

        # Otherwise OFF
        BUZ.value(1)
        await asyncio.sleep_ms(100)




async def async_main(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st):
    asyncio.create_task(task_power_monitor())
    asyncio.create_task(task_dimmer(lcd))
    asyncio.create_task(task_buzzer_stop_button())  # <--- ADD THIS
    asyncio.create_task(task_buzzer_driver())
    asyncio.create_task(task_heartbeat(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st))
    asyncio.create_task(task_age_redraw(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st))
    asyncio.create_task(task_glucose_fetch(lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st))

    while True:
        await asyncio.sleep(10)





def _draw_batt_x_if_changed(lcd, w_batt, st, x=10, y=8):
    new_text = "" if is_usb_connected() else "0"
    new_pos = (x, y)

    # Only skip if BOTH the icon AND the position are unchanged
    if st.batt_x == new_text and st.batt_pos == new_pos:
        return

    pad = 0
    w = w_batt.stringlen("0") + pad * 2
    h = w_batt.font.height() + pad * 2

    # Clear the old position if needed
    if st.batt_pos is not None:
        ox, oy = st.batt_pos
        ow = w_batt.stringlen("0") + pad * 2
        oh = w_batt.font.height() + pad * 2
        lcd.fill_rect(ox, oy, ow, oh, BLACK)
        _show_rect(lcd, ox, oy, ow, oh)

    # Draw new (or blank)
    lcd.fill_rect(x, y, w, h, BLACK)
    if new_text:
        w_batt.setcolor(GREEN, BLACK)
        w_batt.set_textpos(lcd, y + pad, x + pad)
        w_batt.printstring(new_text)

    _show_rect(lcd, x, y, w, h)

    st.batt_x = new_text
    st.batt_pos = new_pos

# --- Buzzer Configuration ---
# We already initialized 'BUZ' at the top of the file, 
# so we just set up the timing variables here.

last_buzzer_time = utime.ticks_ms() - (10 * 60 * 1000) # Set to 10 mins ago so it can beep immediately if needed
BUZZER_COOLDOWN_MS = 10 * 60 * 1000  # 10 minutes

# Snooze (button stops alert for 10 minutes)
BUZZER_SNOOZE_MS = 10 * 60 * 1000
buzzer_snooze_until = 0

MILD_LOW_THRESHOLD = 5
SEVERE_LOW_THRESHOLD = 4

# Buzzer mode: 0=off, 1=severe solid, 2=mild pattern
buzzer_mode = 0

last_mild_beep_time = utime.ticks_ms() - (10 * 60 * 1000)
MILD_COOLDOWN_MS = 10 * 60 * 1000


def check_glucose_alerts(bg_value):
    global buzzer_mode

    if bg_value is None:
        return

    now = utime.ticks_ms()
    snoozed = utime.ticks_diff(now, buzzer_snooze_until) < 0

    # If snoozed, force off (no alerts at all)
    if snoozed:
        buzzer_mode = 0
        return

    # SEVERE has priority (but does NOT ignore snooze anymore)
    if bg_value <= SEVERE_LOW_THRESHOLD:
        buzzer_mode = 1
        return

    # MILD
    if bg_value <= MILD_LOW_THRESHOLD:
        buzzer_mode = 2
        return

    buzzer_mode = 0



            
# ============================
# MAIN LOOP SECTION
# ============================

def main(framebuffer=None):
    import utime
    import network

    global last, hb_state   # <<< ADD THIS
    last = None             # <<< ADD THIS
    hb_state = True

    log("--- SYSTEM START ---")

    # 1. INIT DISPLAY (uses existing framebuffer passed from bootloader)
    lcd = LCD_Driver(fb=framebuffer)

    # 2. INIT WRITERS
    w_small = CWriter(lcd, font_small, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_age_small = CWriter(lcd, age_font_small, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_arrow = CWriter(lcd, font_arrows, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_heart = CWriter(lcd, font_heart, fgcolor=RED, bgcolor=BLACK, verbose=False)
    w_delta_icon = CWriter(lcd, font_delta, fgcolor=WHITE, bgcolor=BLACK, verbose=False)
    w_batt = CWriter(lcd, battery_font, fgcolor=WHITE, bgcolor=BLACK, verbose=False)

    w_small.set_spacing(3)
    w_age_small.set_spacing(2)
    w_arrow.set_spacing(8)

    st = ScreenState()

    # 3. DO NOT CLEAR SCREEN HERE
    # LOGO IS ALREADY ON SCREEN FROM BOOTLOADER

    # 4. WIFI
    sta = network.WLAN(network.STA_IF)
    wifi_ok = sta.isconnected() or connect_wifi(WIFI_SSID, WIFI_PASSWORD)

    if wifi_ok:
        ntp_sync()

        # 5. INITIAL DATA FETCH
        try:
            txt = fetch_ns_text()
            parsed = parse_entries_from_text(txt)
            if parsed:
                last = parsed
        except:
            pass

    # 6. FIRST DRAW — ONLY DRAWS IF last EXISTS
    # DO NOT draw yet — keep boot logo visible
    # draw_all_fields_if_needed(...) is delayed until data exists


    # 7. START ASYNC LOOP
    asyncio.run(async_main(
        lcd, w_small, w_age_small, w_arrow, w_heart, w_delta_icon, w_batt, st
    ))




if __name__ == "__main__":
    try:
        main(framebuffer=None)  # Add framebuffer parameter
    except Exception as e:
        print("CRITICAL CRASH:", e)
        utime.sleep(5)
        reset()




