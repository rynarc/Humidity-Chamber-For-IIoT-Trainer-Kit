# Copyright [2024] [Halia Teknologi Nusantara]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import serial
import revpimodio2
import time
import threading

# Fungsi untuk menghitung CRC16 dari data
def calculate_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder='little')

# Konfigurasi port serial untuk sensor MD02
ser = serial.Serial(
    port='/dev/ttyUSB0',
    baudrate=9600,
    parity=serial.PARITY_EVEN,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=3
)

# Command untuk membaca suhu dan kelembaban dari MD02
command_temperature = bytes.fromhex('01 04 00 01 00 01 60 0A')
command_humidity = bytes.fromhex('01 04 00 02 00 01 90 0B')

# Fungsi untuk membaca suhu
def read_temperature():
    crc = calculate_crc(command_temperature)
    message = command_temperature + crc
    ser.write(message)
    response = ser.read(7)
    if len(response) == 7:
        data = response[3:5]
        temperature_raw = int.from_bytes(data, byteorder='big', signed=True)
        temperature = temperature_raw / 100.0
        return temperature
    else:
        print("Failed to read temperature data from MD02")
        return None

# Fungsi untuk membaca kelembaban
def read_humidity():
    crc = calculate_crc(command_humidity)
    message = command_humidity + crc
    ser.write(message)
    response = ser.read(7)
    if len(response) == 7:
        data = response[3:5]
        humidity_raw = int.from_bytes(data, byteorder='big', signed=False)
        humidity = humidity_raw / 100.0
        return humidity
    else:
        print("Failed to read humidity data from MD02")
        return None

# Inisialisasi koneksi ke Revolution Pi
rpi = revpimodio2.RevPiModIO(autorefresh=True)

# Variabel status untuk mengingat keadaan sebelumnya
heater_on = False
cooler_on = False
humidifier_status = False
dehumidifier_status = False
button1_press_count = 0
prev_button1_value = 0
prev_button2_value = 0
prev_switch_value = None

# Flag untuk menghentikan mode otomatis
stop_auto_mode = False

def control_logic(temp):
    if temp >= 29:
        heater_on = False
        cooler_on = True
    elif 28 < temp < 29:
        heater_on = False
        cooler_on = False
    elif temp <= 28:
        heater_on = True
        cooler_on = False

    return heater_on, cooler_on

# Definisikan fungsi keanggotaan untuk kelembaban menggunakan control logic
def control_humidity(humidity):
    low = max(0, (50 - humidity) / 30)
    high = max(0, (humidity - 50) / 30)
    return low, high

# Definisikan aturan control untuk kontrol kipas
def logic_control(humidity):
    low, high = control_humidity(humidity)
    if low > 0:
        fan_pwm = 20
    if high > 0:
        fan_pwm = 0
    return fan_pwm

# Fungsi untuk kontrol box manual dengan toggle
def control_box():
    global humidifier_status, dehumidifier_status, button1_press_count, prev_button1_value, prev_button2_value

    button1 = rpi.io.I_1.value
    button2 = rpi.io.I_2.value

    if button1 and not prev_button1_value:
        dehumidifier_status = not dehumidifier_status
        if dehumidifier_status:
            rpi.io.O_8.value = 0
            rpi.io.O_7.value = 1
            rpi.io.PWM_1.value = 0
            rpi.io.O_5.value = 1
            rpi.io.O_4.value = 0
            print("Button 1 pressed: Lampu ON, Mist Maker OFF, Fan OFF, LED O_5 ON")
        else:
            rpi.io.O_7.value = 0
            rpi.io.O_5.value = 0
            print("Button 1 pressed: Lampu OFF, LED O_5 OFF")

    if button2 and not prev_button2_value:
        humidifier_status = not humidifier_status
        if humidifier_status:
            rpi.io.O_8.value = 1
            rpi.io.O_7.value = 0
            rpi.io.PWM_1.value = 20
            rpi.io.O_4.value = 1
            rpi.io.O_5.value = 0
            print("Button 2 pressed: Lampu OFF, Mist Maker ON, Fan ON (20%), LED O_4 ON")
        else:
            rpi.io.O_8.value = 0
            rpi.io.PWM_1.value = 0
            rpi.io.O_4.value = 0
            print("Button 2 pressed: Mist Maker OFF, Fan OFF, LED O_4 OFF")

    prev_button1_value = button1
    prev_button2_value = button2

def auto_mode():
    global stop_auto_mode
    stop_auto_mode = False
    while not stop_auto_mode:
        current_temperature = read_temperature()
        current_humidity = read_humidity()
        rpi.io.O_3.value = 1

        if current_temperature is not None:
            print(f"Current Temperature: {current_temperature} °C")
            heater_value, cooler_value = control_logic(current_temperature)
            rpi.io.O_7.value = heater_value
            rpi.io.O_6.value = cooler_value
            rpi.io.O_2.value = cooler_value
            rpi.io.O_1.value = cooler_value
            print(f"Heater (Lamp): {heater_value}, Cooler (Peltier) and Fan: {cooler_value}")

        if current_humidity is not None:
            print(f"Current Humidity: {current_humidity} %RH")
            if current_humidity < 50.0:
                rpi.io.O_8.value = 1
                rpi.io.O_7.value = 0
                fan_pwm_value = logic_control(current_humidity)
                rpi.io.PWM_1.value = fan_pwm_value
                print(f"Mist Maker: ON, Heater: OFF, Fan: ON ({fan_pwm_value}%)")
            elif current_humidity > 50.0:
                rpi.io.O_8.value = 0
                rpi.io.O_7.value = 1
                rpi.io.PWM_1.value = 0
                print("Mist Maker: OFF, Heater: ON, Fan: OFF")
            elif 50.0 <= current_humidity <= 50.0:
                rpi.io.O_8.value = 0
                rpi.io.O_7.value = 1
                rpi.io.PWM_1.value = 0
                print("Mist Maker: OFF, Heater: OFF, Fan: OFF")

        time.sleep(1)  # Tunggu 1 detik sebelum pembacaan berikutnya

def reset_outputs():
    rpi.io.O_1.value = False
    rpi.io.O_2.value = False
    rpi.io.O_6.value = False
    rpi.io.O_7.value = False
    rpi.io.O_8.value = False
    rpi.io.O_4.value = False
    rpi.io.O_5.value = False
    rpi.io.O_3.value = False
    rpi.io.PWM_1.value = 0

auto_mode_thread = None

try:
    while True:
        switch_value = rpi.io.I_4.value

        if switch_value != prev_switch_value:
            if switch_value:
                print("Switched to auto mode")
                stop_auto_mode = False
                auto_mode_thread = threading.Thread(target=auto_mode)
                auto_mode_thread.start()
            else:
                print("Switched to manual mode: All outputs are reset")
                stop_auto_mode = True
                if auto_mode_thread is not None:
                    auto_mode_thread.join()
                reset_outputs()  # Reset semua output saat beralih ke mode manual
        
        if not switch_value:
            control_box()

        prev_switch_value = switch_value
        time.sleep(0.1)

except Exception as e:
    print(f"Terjadi kesalahan: {e}")
finally:
    rpi.exit()
    ser.close()
