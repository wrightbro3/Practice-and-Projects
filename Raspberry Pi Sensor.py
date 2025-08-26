# === Property of Photon Queue ===
# Program Written by Mason Wright

"""
Laser Power Detection System using Raspberry Pi

This system detects laser power from two GRIN lens inputs using photodiodes and displays
real-time power measurements on an LCD screen.

Hardware:
- 2x ADS1115 ADCs (commented out placeholders for now)
- 2x Photodiodes
- 1x ST7789-based 2" LCD Display (Waveshare)
"""

import time
import board
import busio
import digitalio
from adafruit_rgb_display import st7789
from PIL import Image, ImageDraw, ImageFont
from adafruit_ads1x15.ads1115 import ADS1115
# from adafruit_ads1x15.ads1x15 import ADS
from adafruit_ads1x15.analog_in import AnalogIn


# === Constants and Calibration Values ===
FEEDBACK_RESISTOR = 430  # Ohms
RESPONSIVITY = 1  # A/W
V_OPAMP_INPUT = 3.3  # V (TIA virtual ground)

DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 320
DISPLAY_ROTATION = 0  # no rotation

REFRESH_DELAY = 1e-2 # seconds

# Colors (R, G, B)
CREAM = (255, 235, 205)  # Slightly more orange/red cream background
MAROON = (128, 0, 0)
BLACK = (0, 0, 0)

LETTER_SIZE = 23

# === Setup Backlight ===
bl = digitalio.DigitalInOut(board.D12)  # Backlight pin
bl.direction = digitalio.Direction.OUTPUT
bl.value = True  # Turn backlight ON

# === Setup SPI and Display Pins ===
spi = busio.SPI(clock=board.SCLK, MOSI=board.MOSI)
while not spi.try_lock():
    pass
spi.configure(baudrate=64000000)
spi.unlock()

cs = digitalio.DigitalInOut(board.CE0)  # GPIO8 / CE0
dc = digitalio.DigitalInOut(board.D25)  # GPIO25
reset = digitalio.DigitalInOut(board.D18)  # GPIO18

disp = st7789.ST7789(
    spi,
    cs=cs,
    dc=dc,
    rst=reset,
    width=DISPLAY_WIDTH,
    height=DISPLAY_HEIGHT,
    rotation=DISPLAY_ROTATION,
    baudrate=64000000,
)

# === Load Fonts ===
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", LETTER_SIZE)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", LETTER_SIZE - 10)
except:
    font = ImageFont.load_default()
    font_small = ImageFont.load_default()


# === Global persistent image and draw context ===
static_img = None
draw = None


# === Helper Functions ===

def compute_power(v_in, v_out, r_feedback=FEEDBACK_RESISTOR, responsivity=RESPONSIVITY):
    return (v_out - v_in) / (r_feedback * responsivity) # Note I am writing this as negative because inverting

def format_power(power):
    abs_p = abs(power)
    if abs_p == 0:
        return "0 W"
    elif abs_p < 1e-9:
        return "<1 nW"
    elif abs_p < 1e-6:
        return f"{abs_p * 1e9:.3f} nW"
    elif abs_p < 1e-3:
        return f"{abs_p * 1e6:.3f} μW"
    elif abs_p < 1:
        return f"{abs_p * 1e3:.3f} mW"
    else:
        return f"{abs_p:.2f} W"

def power_to_fraction(power):
    abs_p = abs(power)
    if abs_p == 0:
        return 0.0
    elif abs_p < 1e-9:
        return 0.0
    elif abs_p < 1e-6:
        return min((abs_p * 1e9) / 1000, 1.0)
    elif abs_p < 1e-3:
        return min((abs_p * 1e6) / 1000, 1.0)
    elif abs_p < 1:
        return min((abs_p * 1e3) / 1000, 1.0)
    else:
        return 1.0


def draw_static_elements():
    global static_img, draw
    static_img = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), CREAM)
    draw = ImageDraw.Draw(static_img)

    # Title
    draw.text((10, 10), "PhotonQueue", font=font, fill=MAROON)

    # Power 1 label and bar border
    draw.text((10, 80), "Power 1:", font=font_small, fill=MAROON)
    draw.rectangle([10, 140, DISPLAY_WIDTH - 10, 170], outline=BLACK, width=2)

    # Power 2 label and bar border
    draw.text((10, 190), "Power 2:", font=font_small, fill=MAROON)
    draw.rectangle([10, 250, DISPLAY_WIDTH - 10, 280], outline=BLACK, width=2)

    disp.image(static_img)


def update_dynamic_elements(power1, power2):
    global static_img, draw

    # Erase old values (just the power reading areas)
    draw.rectangle([100, 80, DISPLAY_WIDTH - 10, 100], fill=CREAM)
    draw.rectangle([100, 190, DISPLAY_WIDTH - 10, 210], fill=CREAM)

    # Draw new power text
    p1_text = format_power(power1)
    p2_text = format_power(power2)
    draw.text((100, 80), p1_text, font=font_small, fill=MAROON)
    draw.text((100, 190), p2_text, font=font_small, fill=MAROON)

    # Erase bars area before redrawing bars
    draw.rectangle([12, 142, DISPLAY_WIDTH - 12, 168], fill=CREAM)
    draw.rectangle([12, 252, DISPLAY_WIDTH - 12, 278], fill=CREAM)

    # Draw power bars
    bar_width = DISPLAY_WIDTH - 20
    p1_frac = power_to_fraction(power1)
    p2_frac = power_to_fraction(power2)

    if p1_frac > 0:
        draw.rectangle([12, 142, 12 + int(bar_width * p1_frac), 168], fill=MAROON)
    if p2_frac > 0:
        draw.rectangle([12, 252, 12 + int(bar_width * p2_frac), 278], fill=MAROON)

    # Send updated image to display
    disp.image(static_img)


# === Adding in a function to calculate proper offsets ===
"""
Note: we were having issues with the pi running to the  correct power readings. This will take
Samples for us to compute the proper offsets because this shit is fucked and then should allow
us to have the proper power readings. If this doesn't work I am looking into nearby bridges
with `excellent city views`
"""
def calibrate_baseline(chan1, chan2, num_samples=500, delay=0.1):
    show_calibrating_screen() # shows the message on the lcd screen

    print("Calibrating baseline... Please ensure no laser light on photodiodes.")
    v1_total = 0.0
    v2_total = 0.0

    for _ in range(num_samples):
        v1_total += chan1.voltage
        v2_total += chan2.voltage
        time.sleep(delay)  # Wait between samples

    v1_offset = v1_total / num_samples
    v2_offset = v2_total / num_samples

    print(f"Calibration done. Baseline voltages: v1_offset={v1_offset:.4f} V, v2_offset={v2_offset:.4f} V")
    return v1_offset, v2_offset


#This is so the screen isnt just green for the calibration
def show_calibrating_screen():
    image = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), CREAM)
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", LETTER_SIZE)
    except:
        font = ImageFont.load_default()

    text = "Calibrating...\nPlease block laser"
    lines = text.split('\n')

    max_width = 0
    total_height = 0
    line_heights = []

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w > max_width:
            max_width = w
        line_heights.append(h)
        total_height += h

    x = (DISPLAY_WIDTH - max_width) // 2
    y = (DISPLAY_HEIGHT - total_height) // 2

    for i, line in enumerate(lines):
        draw.text((x, y), line, font=font, fill=MAROON)
        y += line_heights[i]

    disp.image(image)


# === Main Loop ===
def main():
    i2c = busio.I2C(board.SCL, board.SDA)
    ads1 = ADS1115(i2c, address=0x48)
    ads2 = ADS1115(i2c, address=0x49)
    chan1 = AnalogIn(ads1, 0)
    chan2 = AnalogIn(ads2, 0)

    # This is to make suer we are running smoothly and fast.
    ads1.data_rate = 860  # max 860 samples per second
    ads2.data_rate = 860

    # this is setting the gain for the system
    # ads1.gain = 1  # ±4.096 V range
    # ads2.gain = 1
    # Note these did not work and something got wonky

    # Calibrate baseline before main reading loop
    v1_offset, v2_offset = calibrate_baseline(chan1, chan2, num_samples=500, delay=0.1)
    iteration = 0

    # Draw static elements once at the start (initializes global static_img and draw)
    draw_static_elements()

    while True:
        total_start = time.time()
        math_start = time.time()

        v1_raw = chan1.voltage
        v2_raw = chan2.voltage

        # Subtract baseline offsets
        v1 = v1_raw - v1_offset
        v2 = v2_raw - v2_offset

        power1_raw = compute_power(V_OPAMP_INPUT, v1_raw)
        power2_raw = compute_power(V_OPAMP_INPUT, v2_raw)

        power1_offset = compute_power(V_OPAMP_INPUT, v1_offset)
        power2_offset = compute_power(V_OPAMP_INPUT, v2_offset)

        power1 = abs(power1_raw - power1_offset)
        power2 = abs(power2_raw - power2_offset)

        math_stop = time.time()
        print(f"=== Iteration: {iteration} ===")
        print(f"Time to run: {math_stop-math_start} seconds")
        print(f"voltage 1 (raw): {v1_raw:.4f} V, voltage 2 (raw): {v2_raw:.4f} V")
        print(f"voltage 1 (offset): {v1:.4f} V, voltage 2 (offset): {v2:.4f} V")
        print(f"Power 1: {power1:.6f} W, Power 2: {power2:.6f} W")

        disp_start = time.time()
        update_dynamic_elements(power1, power2)
        disp_stop = time.time()

        iteration += 1
        # time.sleep(REFRESH_DELAY)
        total_stop = time.time()
        print(f"dosplay run time: {disp_stop-disp_start} seconds | Total loop run time: {total_stop-total_start} seconds")


if __name__ == "__main__":
    main()