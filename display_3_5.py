from machine import Pin, SPI, PWM
import framebuf
import time
import micropython

LCD_DC  = 14
LCD_CS  = 9
SCK     = 10
MOSI    = 11
MISO    = 12
LCD_RST = 13
LCD_BL  = 15

@micropython.viper
def _bswap16_inplace(buf):
    b = ptr8(buf)
    n = int(len(buf))
    i = 0
    while i < n:
        t = b[i]
        b[i] = b[i + 1]
        b[i + 1] = t
        i += 2

@micropython.viper
def _bswap16_copy(src, src_off: int, dst, nbytes: int):
    s = ptr8(src)
    d = ptr8(dst)
    i = 0
    while i < nbytes:
        lo = s[src_off + i]
        hi = s[src_off + i + 1]
        d[i] = hi
        d[i + 1] = lo
        i += 2

class Palette(framebuf.FrameBuffer):
    def __init__(self):
        buf = bytearray(4)
        super().__init__(buf, 2, 1, framebuf.RGB565)
    def bg(self, color): self.pixel(0, 0, color)
    def fg(self, color): self.pixel(1, 0, color)

class lcd_st7796(framebuf.FrameBuffer):
    def __init__(self, fb=None, baud=40_000_000, bl=100):
        new_fb = (fb is None)
        self.width = 480
        self.height = 320

        self.cs  = Pin(LCD_CS,  Pin.OUT, value=1)
        self.rst = Pin(LCD_RST, Pin.OUT, value=1)
        self.dc  = Pin(LCD_DC,  Pin.OUT, value=1)

        self._bl_pwm = PWM(Pin(LCD_BL))
        self._bl_pwm.freq(1000)
        self._bl_pwm.duty_u16(0)

        self.spi = SPI(1, baud, polarity=0, phase=0,
                       sck=Pin(SCK), mosi=Pin(MOSI), miso=Pin(MISO))

        if new_fb:
            fb = bytearray(self.width * self.height * 2)
        self.buffer = fb

        # Row buffer for partial updates
        self._linebuf = bytearray(self.width * 2)

        super().__init__(self.buffer, self.width, self.height, framebuf.RGB565)

        self.palette = Palette()
        
        # Only set brightness and clear if this is a NEW framebuffer
        if new_fb:
            self.bl_ctrl(bl)
            self.fill(0x0000)

    def write_cmd(self, cmd):
        self.dc(0); self.cs(0)
        self.spi.write(bytearray([cmd]))
        self.cs(1)

    def write_data(self, data):
        self.dc(1); self.cs(0)
        self.spi.write(bytearray([data]) if isinstance(data, int) else data)
        self.cs(1)

    def bl_ctrl(self, duty):
        self._bl_pwm.duty_u16(int(duty * 655.35))

    def _set_window(self, x0, y0, x1, y1):
        self.write_cmd(0x2A)
        self.write_data(bytearray([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))
        self.write_cmd(0x2B)
        self.write_data(bytearray([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))
        self.write_cmd(0x2C)

    def lcd_init(self):
        import utime as time

        # Keep backlight OFF (or very dim) during init to prevent the visible flash.
        # If your bl_ctrl expects 0–100, 0 will fully off.
        try:
            # If your driver stores a target brightness, reuse it after init.
            # If not present, default to 100.
            final_bl = getattr(self, "_bl", 100)
            self.bl_ctrl(0)
            time.sleep_ms(5)
        except Exception:
            final_bl = 100  # fallback if bl_ctrl isn't available yet

        print("DEBUG display_3_5: lcd_init() starting...")

        # Hardware reset (panel may go blank here; backlight is off so user won't see it)
        try:
            self.rst(0)
            time.sleep_ms(20)     # 100ms is usually overkill; 20ms is typically fine
            self.rst(1)
            time.sleep_ms(120)    # allow the panel/controller to stabilize after reset
        except Exception:
            # If rst is not available for some reason, continue
            pass

        # Sleep out
        self.write_cmd(0x11)
        time.sleep_ms(120)

        # Pixel / addressing setup
        self.write_cmd(0x36); self.write_data(0x28)  # MADCTL (your existing value)
        self.write_cmd(0x3A); self.write_data(0x05)  # COLMOD: RGB565
        self.write_cmd(0xB4); self.write_data(0x01)  # Display inversion control (your existing)

        # Inversion ON (your existing)
        self.write_cmd(0x21)

        # Display ON
        self.write_cmd(0x29)
        time.sleep_ms(20)

        print("DEBUG display_3_5: lcd_init() complete")

        # Turn backlight on only AFTER init is complete.
        # If you want it to come up dimmer, change final_bl to e.g. 10–20.
        try:
            self.bl_ctrl(final_bl)
        except Exception:
            pass


    def show(self):
        self._set_window(0, 0, self.width - 1, self.height - 1)
        self.dc(1); self.cs(0)
        _bswap16_inplace(self.buffer)
        self.spi.write(self.buffer)
        _bswap16_inplace(self.buffer)
        self.cs(1)

    def show_rect(self, x, y, w, h):
        if x < 0: w += x; x = 0
        if y < 0: h += y; y = 0
        if x + w > self.width:  w = self.width - x
        if y + h > self.height: h = self.height - y
        if w <= 0 or h <= 0:
            return

        x0, y0 = x, y
        x1, y1 = x + w - 1, y + h - 1
        self._set_window(x0, y0, x1, y1)

        self.dc(1); self.cs(0)

        row_bytes = self.width * 2
        start = y0 * row_bytes + x0 * 2
        copy_bytes = w * 2

        src = self.buffer
        linebuf = self._linebuf

        for row in range(h):
            si = start + row * row_bytes
            _bswap16_copy(src, si, linebuf, copy_bytes)
            self.spi.write(memoryview(linebuf)[:copy_bytes])

        self.cs(1)

