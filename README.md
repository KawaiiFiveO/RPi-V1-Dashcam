# RPi-V1-Dashcam

Valentine One Integrated Dashcam using Raspberry Pi.

### Features

- Record video and audio continuously
- Log data from a GPS module and V1
- Display V1 alert frequencies to OLED screen
- Burn-in logged data to video
- Web interface works on any phone
- Works with both Gen1 and Gen2 V1

### Parts used

- Raspberry Pi Model 4B
- Any high-endurance SD card
- [USB Microphone for Laptop and Desktop Computer](https://www.amazon.com/dp/B0CNVZ27YH)
- [Arducam for Raspberry Pi Camera 16MP IMX519 Camera Module with 140°(D) Wide Angle M12 Lens](https://www.amazon.com/dp/B0C53BBMLG)
- [DIYmall PiOLED 0.91inch I2C 128X32 SSD1306 OLED Display Module](https://www.amazon.com/dp/B07V4FRSKK)
- [YELUFT 1pcs GY-NEO6MV2 NEO-6M GPS Module](https://www.amazon.com/dp/B0F2DP1189)

### Instructions

Use Raspberry Pi OS Lite 64-bit.

From an ssh terminal, setup the environment:

```
sudo apt-get install ffmpeg
git clone https://github.com/KawaiiFiveO/RPi-V1-Dashcam.git
cd RPi-V1-Dashcam
python -m venv env --system-site-packages
source env/bin/activate
pip install -r requirements.txt
```

You can use the scripts in `tests` to confirm that your hardware works.

Then, once you're ready to try the dashcam:

```
python main.py
```

You can configure settings such as recording duration and camera orientation in `config.py`.

If you want it to run automatically on boot, setup the service:

```
sudo cp service/dashcam.service /etc/systemd/system/dashcam.service
sudo nano /etc/systemd/system/dashcam.service
```

Edit the file with your values.

```
sudo systemctl daemon-reload
sudo systemctl enable dashcam.service
sudo systemctl start dashcam.service
```

### Web Interface

When your Pi is connected to your home network, you can visit the webpage (at your Pi’s IP and port 5000) in your browser to start/stop recording and change settings.

To access files without starting the other dashcam functions:

```
python main.py --web-only
```

To make the Pi start up its own network so that you can control the web interface even when it's not connected to a network:

```
nmcli con add type wifi ifname wlan0 con-name Hotspot autoconnect yes ssid V1-Dashcam-Hotspot
nmcli con modify Hotspot 802-11-wireless.mode ap
nmcli con modify Hotspot ipv4.method shared
nmcli con modify Hotspot ipv4.addresses 192.168.4.1/24
nmcli con modify Hotspot wifi-sec.key-mgmt wpa-psk
nmcli con modify Hotspot wifi-sec.psk "MyPasswordHere"
nmcli con modify MyHomeWifi connection.autoconnect-priority 10
nmcli con modify Hotspot connection.autoconnect-priority -10
sudo systemctl restart NetworkManager
```

Replace `V1-Dashcam-Hotspot`, `MyHomeWifi`, and `MyPasswordHere` with your own values.

### TODO

- fix camera orientation
- delete oldest videos if storage low
- better documentation/writeup
- OLED customization
- improve web interface
- improve overlay visuals
- make audio optional
- TEST EVERYTHING