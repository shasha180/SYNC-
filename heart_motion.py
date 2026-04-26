import csv
from flask import Flask, request
import threading
import math
import asyncio
from bleak import BleakClient
import pyttsx3
import time
from datetime import datetime
import sys # Added for simulation

# --- CONFIGURATION ---
HR_MAX_THRESHOLD = 120
HR_INCREASE_LIMIT = 30
MOV_VARIANCE_LIMIT = 0.5
SUSTAINED_TIME = 5 # Lowered to 5s for faster demo testing!

# --- GLOBALS ---
motion_data = {"magnitude": 0.0}
simulated_hr = 75 # Starts normal
spike_counter = 0  
CSV_FILE = "triage_data.csv"
engine = pyttsx3.init()

app = Flask(__name__)

@app.route('/sensor', methods=['POST'])
def get_sensor_data():
    global motion_data
    data = request.json
    inner_payload = data.get('payload', [])
    if isinstance(inner_payload, list) and len(inner_payload) > 0:
        for entry in inner_payload:
            name = entry.get('name', '').lower()
            if "uncalibrated" in name or "gravity" in name: continue 
            if any(x in name for x in ['accelerometer', 'motion', 'useracceleration']):
                v = entry.get('values', {})
                mag = math.sqrt(v.get('x', 0)**2 + v.get('y', 0)**2 + v.get('z', 0)**2)
                motion_data["magnitude"] = mag
                # Call the triage logic manually since Bluetooth is off
                run_triage_logic(simulated_hr)
                return "OK", 200
    return "OK", 200

def run_triage_logic(current_hr):
    global spike_counter
    mag = motion_data["magnitude"]
    now = datetime.now().strftime("%H:%M:%S")

    # The Paper Logic
    is_high_hr = (current_hr >= HR_MAX_THRESHOLD)
    is_still = (mag < MOV_VARIANCE_LIMIT)

    if is_high_hr:
        if not is_still:
            status = "Exercise (Normal)"
            spike_counter = 0 
        else:
            spike_counter += 1
            status = f"Sustained Spike ({spike_counter}s)"
            if spike_counter >= SUSTAINED_TIME:
                status = "!!! POTS ALERT !!!"
                print(f"🚨 {status}")
                engine.say("POTS Spike detected. Please sit down.")
                engine.runAndWait()
                spike_counter = 0 # Reset after alert
    else:
        spike_counter = 0 
        status = "Normal"

    print(f"[{now}] HR: {current_hr} | MOV: {mag:.2f} | Status: {status}")

# --- KEYBOARD SIMULATOR ---
def keyboard_input():
    global simulated_hr
    print("⌨️  SIMULATOR READY:")
    print("   Press 's' + Enter to simulate SPIKE (125 BPM)")
    print("   Press 'n' + Enter to simulate NORMAL (75 BPM)")
    while True:
        cmd = input().lower()
        if cmd == 's':
            simulated_hr = 125
            print(">>> SIMULATING HIGH HEART RATE (125 BPM) <<<")
        elif cmd == 'n':
            simulated_hr = 75
            print(">>> SIMULATING NORMAL HEART RATE (75 BPM) <<<")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=keyboard_input, daemon=True).start()
    
    print("SYNC-TRIAGE: CONNECTED MODE (SIMULATED HR)")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")