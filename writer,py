import framebuf
from uctypes import bytearray_at, addressof

__version__ = (0, 5, 2)


class DisplayState:
    def __init__(self):
        self.text_row = 0
        self.text_col = 0


def _get_id(device):
    return id(device)


# Basic Writer class for monochrome displays
class Writer:

    state = {}  # Holds a display state for each device

    @staticmethod
    def set_textpos(device, row=None, col=None):
        devid = _get_id(device)
        if devid not in Writer.state:
            Writer.state[devid] = DisplayState()
        s = Writer.state[devid]  # Current state
        if row is not None:
            if row < 0 or row >= device.height:
                raise ValueError("row is out of range")
            s.text_row = row
        if col is not None:
            if col < 0 or col >= device.width:
                raise ValueError("col is out of range")
            s.text_col = col
        return s.text_row, s.text_col

    def __init__(self, device, font, verbose=True):
        self.devid = _get_id(device)
        self.device = device
        if self.devid not in Writer.state:
            Writer.state[self.devid] = DisplayState()
        self.font = font
        self.char_spacing = 0  # extra pixels between letters (0 = default)

        if font.height() >= device.height or font.max_width() >= device.width:
            raise ValueError("Font too large for screen")
        # Allow to work with reverse or normal font mapping
        if font.hmap():
            self.map = framebuf.MONO_HMSB if font.reverse() else framebuf.MONO_HLSB
        else:
            raise ValueError("Font must be horizontally mapped.")
        if verbose:
            fstr = "Orientation: Horizontal. Reversal: {}. Width: {}. Height: {}."
            print(fstr.format(font.reverse(), device.width, device.height))
            print(
                "Start row = {} col = {}".format(
                    self._getstate().text_row, self._getstate().text_col
                )
            )
        self.screenwidth = device.width  # In pixels
        self.screenheight = device.height
        self.bgcolor = 0  # Monochrome background and foreground colors
        self.fgcolor = 1
        self.row_clip = False  # Clip or scroll when screen fullt
        self.col_clip = False  # Clip or new line when row is full
        self.wrap = True  # Word wrap
        self.cpos = 0
        self.tab = 4

        self.glyph = None  # Current char
        self.char_height = 0
        self.char_width = 0

    def _getstate(self):
        return Writer.state[self.devid]

    def _newline(self):
        s = self._getstate()
        height = self.font.height()
        s.text_row += height
        s.text_col = 0
        margin = self.screenheight - (s.text_row + height)
        y = self.screenheight + margin
        if margin < 0:
            if not self.row_clip:
                self.device.scroll(0, margin)
                self.device.fill_rect(0, y, self.screenwidth, abs(margin), self.bgcolor)
                s.text_row += margin

    def set_clip(self, row_clip=None, col_clip=None, wrap=None):
        if row_clip is not None:
            self.row_clip = row_clip
        if col_clip is not None:
            self.col_clip = col_clip
        if wrap is not None:
            self.wrap = wrap
        return self.row_clip, self.col_clip, self.wrap

    @property
    def height(self):  # Property for consistency with device
        return self.font.height()

    def printstring(self, string, invert=False):
        # word wrapping. Assumes words separated by single space.
        q = string.split("\n")
        last = len(q) - 1
        for n, s in enumerate(q):
            if s:
                self._printline(s, invert)
            if n != last:
                self._printchar("\n")

    def _printline(self, string, invert):
        rstr = None
        if self.wrap and self.stringlen(string, True):  # Length > self.screenwidth
            pos = 0
            lstr = string[:]
            while self.stringlen(lstr, True):  # Length > self.screenwidth
                pos = lstr.rfind(" ")
                lstr = lstr[:pos].rstrip()
            if pos > 0:
                rstr = string[pos + 1 :]
                string = lstr

        for i, char in enumerate(string):
            self._printchar(char, invert)
            if self.char_spacing and i != (len(string) - 1) and char != "\n":
                self._getstate().text_col += self.char_spacing
            
            
        if rstr is not None:
            self._printchar("\n")
            self._printline(rstr, invert)  # Recurse

    def stringlen(self, string, oh=False):
        if not len(string):
            return 0
        sc = self._getstate().text_col  # Start column
        wd = self.screenwidth
        l = 0
        for char in string[:-1]:
            _, _, char_width = self.font.get_ch(char)
            l += char_width
            if self.char_spacing:
                l += self.char_spacing

            if oh and l + sc > wd:
                return True  # All done. Save time.
        char = string[-1]
        _, _, char_width = self.font.get_ch(char)
        if oh and l + sc + char_width > wd:
            l += self._truelen(char)  # Last char might have blank cols on RHS
        else:
            l += char_width  # Public method. Return same value as old code.
        return l + sc > wd if oh else l

    # Return the printable width of a glyph less any blank columns on RHS
    def _truelen(self, char):
        glyph, ht, wd = self.font.get_ch(char)
        div, mod = divmod(wd, 8)
        gbytes = div + 1 if mod else div  # No. of bytes per row of glyph
        mc = 0  # Max non-blank column
        data = glyph[(wd - 1) // 8]  # Last byte of row 0
        for row in range(ht):  # Glyph row
            for col in range(wd - 1, -1, -1):  # Glyph column
                gbyte, gbit = divmod(col, 8)
                if gbit == 0:  # Next glyph byte
                    data = glyph[row * gbytes + gbyte]
                if col <= mc:
                    break
                if data & (1 << (7 - gbit)):  # Pixel is lit (1)
                    mc = col  # Eventually gives rightmost lit pixel
                    break
            if mc + 1 == wd:
                break  # All done: no trailing space
        # print('Truelen', char, wd, mc + 1)  # TEST
        return mc + 1

    def _get_char(self, char, recurse):
        if not recurse:  # Handle tabs
            if char == "\n":
                self.cpos = 0
            elif char == "\t":
                nspaces = self.tab - (self.cpos % self.tab)
                if nspaces == 0:
                    nspaces = self.tab
                while nspaces:
                    nspaces -= 1
                    self._printchar(" ", recurse=True)
                self.glyph = None  # All done
                return

        self.glyph = None  # Assume all done
        if char == "\n":
            self._newline()
            return
        glyph, char_height, char_width = self.font.get_ch(char)
        s = self._getstate()
        if s.text_row + char_height > self.screenheight:
            if self.row_clip:
                return
            self._newline()
        if s.text_col + char_width - self.screenwidth > 0:  # Glyph would overhang
            if self.col_clip or self.wrap:
                return  # Can't clip a glyph: discard
            else:
                self._newline()
        self.glyph = glyph
        self.char_height = char_height
        self.char_width = char_width

    # Method using blitting. Efficient rendering for monochrome displays.
    # Tested on SSD1306. Invert is for black-on-white rendering.
    def _printchar(self, char, invert=False, recurse=False):
        s = self._getstate()
        self._get_char(char, recurse)
        if self.glyph is None:
            return
    
        # Determine colors
        fg = self.bgcolor if invert else self.fgcolor
        bg = self.fgcolor if invert else self.bgcolor
    
        # Get glyph data once
        glyph, char_height, char_width = self.font.get_ch(char)
        bytes_per_row = (char_width + 7) // 8
    
        # Draw the character pixel by pixel
        for row in range(char_height):
            for col in range(char_width):
                # Calculate byte and bit position
                byte_idx = (row * bytes_per_row) + (col // 8)
                bit_idx = 7 - (col % 8)
            
                # Check if pixel is set
                if (glyph[byte_idx] >> bit_idx) & 1:
                    self.device.pixel(s.text_col + col, s.text_row + row, fg)
                else:
                    self.device.pixel(s.text_col + col, s.text_row + row, bg)
                
        s.text_col += char_width
        self.cpos += 1

    def set_spacing(self, pixels=0):
    # pixels = extra blank columns between characters
        try:
            self.char_spacing = max(0, int(pixels))
        except Exception:
            self.char_spacing = 0

    
    
    def tabsize(self, value=None):
        if value is not None:
            self.tab = value
        return self.tab

    def setcolor(self, *_):
        return self.fgcolor, self.bgcolor


# Writer for colour displays.
class CWriter(Writer):
    @staticmethod
    def create_color(ssd, idx, r, g, b):
        c = ssd.rgb(r, g, b)
        if not hasattr(ssd, "lut"):
            return c
        if not 0 <= idx <= 15:
            raise ValueError("Color nos must be 0..15")
        x = idx << 1
        ssd.lut[x] = c & 0xFFFF
        ssd.lut[x + 1] = c >> 8
        return idx

    def __init__(self, device, font, fgcolor=None, bgcolor=None, verbose=True):
        #if not hasattr(device, "palette"):
        #    raise OSError("Incompatible device driver.")

        super().__init__(device, font, verbose)
        if bgcolor is not None:  # Assume monochrome.
            self.bgcolor = bgcolor
        if fgcolor is not None:
            self.fgcolor = fgcolor
        self.def_bgcolor = self.bgcolor
        self.def_fgcolor = self.fgcolor

    def _printchar(self, char, invert=False, recurse=False):
        s = self._getstate()
        self._get_char(char, recurse)
        if self.glyph is None:
            return
        
        # Determine colors
        fg = self.bgcolor if invert else self.fgcolor
        bg = self.fgcolor if invert else self.bgcolor
        
        # Draw the character pixel by pixel
        for row in range(self.char_height):
            for col in range(self.char_width):
                # Get pixel from glyph (0 or 1)
                pixel = self.font.get_ch(char)[0] # Simplified for clarity
                # Instead of the above, use this robust way:
                glyph, char_height, char_width = self.font.get_ch(char)
                
                # Logic to extract bit from monochrome glyph
                byte_idx = (row * ((char_width + 7) // 8)) + (col // 8)
                bit_idx = 7 - (col % 8)
                if (glyph[byte_idx] >> bit_idx) & 1:
                    self.device.pixel(s.text_col + col, s.text_row + row, fg)
                
                else:
                    self.device.pixel(s.text_col + col, s.text_row + row, bg)
                    
        s.text_col += self.char_width
        self.cpos += 1

    def setcolor(self, fgcolor=None, bgcolor=None):
        if fgcolor is None and bgcolor is None:
            self.fgcolor = self.def_fgcolor
            self.bgcolor = self.def_bgcolor
        else:
            if fgcolor is not None:
                self.fgcolor = fgcolor
            if bgcolor is not None:
                self.bgcolor = bgcolor
        return self.fgcolor, self.bgcolor
