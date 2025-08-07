# test_oled.py
# Description: Displays system stats on a PiOLED screen

import time
import subprocess
import os.path
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

# --- OLED Display Setup ---
try:
    serial = i2c(port=1, address=0x3C)
    
    # --- THE FIX IS HERE ---
    # We must explicitly tell the ssd1306 class the dimensions of our display.
    # The default is 128x64, but the PiOLED is 128x32.
    device = ssd1306(serial, width=128, height=32)
    
    print("OLED display initialized successfully for 128x32.")
except Exception as e:
    print(f"Error initializing OLED display: {e}")
    print("Please ensure I2C is enabled in raspi-config and the screen is wired correctly.")
    exit()

# --- Font Loading ---
def get_font(size):
    try:
        font_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), 'fonts', 'pixelmix.ttf'))
        return ImageFont.truetype(font_path, size)
    except IOError:
        print("Font 'pixelmix.ttf' not found. Falling back to default.")
        return ImageFont.load_default()

font = get_font(8)

# --- Main Loop ---
while True:
    try:
        with canvas(device) as draw:
            # --- Shell scripts for system monitoring ---
            cmd = "hostname -I | cut -d' ' -f1"
            IP = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            
            cmd = 'cut -f 1 -d " " /proc/loadavg'
            CPU = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            
            cmd = "free -m | awk 'NR==2{printf \"Mem: %s/%sMB %.0f%%\", $3,$2,$3*100/$2 }'"
            MemUsage = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            
            cmd = 'df -h | awk \'$NF=="/"{printf "Disk:%s %s\", $3,$2,$5}\''
            Disk = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()

            # --- Draw the text on the canvas ---
            draw.text((0, 0),  "IP: " + IP, font=font, fill="white")
            draw.text((0, 8),  "CPU: " + CPU, font=font, fill="white")
            draw.text((0, 16), MemUsage, font=font, fill="white")
            draw.text((0, 24), Disk, font=font, fill="white")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\nExiting. Clearing display.")
        break
    except Exception as e:
        print(f"An error occurred in the main loop: {e}")
        time.sleep(5)

device.clear()