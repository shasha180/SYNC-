import asyncio
import pandas as pd
from datetime import datetime
import subprocess
import random
import os

# -- CONFIGURATION -- #
THRESHOLD = 40
MAX_HISTORY = 50
CALIBRATION_COUNT = 20
MOVEMENT_THRESHOLD = 0.3

AUDIO_FILE = "brownnoise.mp3"
AUDIO_VOLUME = 1.0

# -- GLOBAL STATE -- #
baseline_hr = 0
reading_history = []

log_data = {
    "Time": [],
    "BPM": [],
    "Movement": [],
    "Upright": [],
    "Status": [],
    "Severity": [],
}

brown_noise_process = None

# -- AUDIO CONTROL -- #
def start_brown_noise():
    global brown_noise_process
    if brown_noise_process is None:
        brown_noise_process = subprocess.Popen(
            ["afplay","-v", str(AUDIO_VOLUME), AUDIO_FILE]
        )
        
def stop_brown_noise():
    global brown_noise_process
    if brown_noise_process is not None:
        try:
            brown_noise_process.terminate()
        except Exception:
            pass
        brown_noise_process = None

# -- VOICE SYSTEM (DUCKING) --#
def speak(text):
    stop_brown_noise()
    os.system(f'say -r 85 -v Samantha "{text}"')
    start_brown_noise()

# -- BREATHING INTERVENTION -- #
def guided_breathing(cycles=3):
    for _ in range(cycles):
        speak("Breath in slowly")
        speak("One.... Two.... Three... four... ")

        speak("Now breath out slowly")
        speak("One.... two.... three.... four.... five.... six")  

# -- SEVERITY -- #
def classify_severity(hr):
    if hr < 100:
        return "mild"
    elif hr <= 120:
        return "moderate"
    else:
        return "severe"
    
# -- PREDICTIVE WARNING -- #
def check_predictive_warning(current_hr):
    if len(reading_history) < 10:
        return
    
    trend = current_hr - reading_history[-10]

    if trend > 20:
        print("WARNING: Rapid heart increase detected")
        speak("WARNING: Rapid heart increase detected")

# -- SPIKE DETECTION -- #
def detect_spike(current_hr, movement_score, is_upright):
    if len(reading_history) < CALIBRATION_COUNT:
        return False, 0
    
    diff = current_hr - baseline_hr

    is_spike = (
        diff >= THRESHOLD and
        movement_score < MOVEMENT_THRESHOLD and
        is_upright
    )

    return is_spike, diff

# -- BASELINE -- #
def update_baseline(hr):
    global baseline_hr

    reading_history.append(hr)
    if len (reading_history) > MAX_HISTORY:
        reading_history.pop(0)

    baseline_hr = sum (reading_history) / len(reading_history)

# -- INTERVENTION -- #
def handle_spike(severity):
    speak("Alert. Abnormal Heart rate detected.")
    print(f"!!! POTS SPIKE DETECTED ({severity.upper()}) !!!")

    speak("POTS spike detected.")

    if severity == "mild":
        speak("Try to stay still and relax your breathing.")
    
    elif severity == "moderate":
        speak("Please sit down and stay calm.")
        guided_breathing(3)
    
    elif severity == "severe":
        speak("Lie down immediately and raise your leg.")
        guided_breathing(4)
        speak("Stay still. Help may be needed")

    speak("Keep breathing slowly. You are safe.")
    
# -- LOGGING -- #
def log(time, hr, movement, upright,status, severity):
    log_data["Time"].append(time)
    log_data["BPM"].append(hr)
    log_data["Movement"].append(movement)
    log_data["Upright"].append(upright)
    log_data["Status"].append(status)
    log_data["Severity"].append(severity)

    pd.DataFrame(log_data).to_csv("heart_log.csv", index=False)

# -- PROCESS HEART RATE -- #
def process_heart_rate(hr, movement_score, is_upright):
    now = datetime.now().strftime("%H:%M:%S")

    update_baseline(hr)

    if len(reading_history) < CALIBRATION_COUNT:
        print(f"Calibrating... ({len(reading_history)}/{CALIBRATION_COUNT})")
        log(now, hr, movement_score, is_upright, "Learning", "N/A")
        return
    
    check_predictive_warning(hr)

    is_spike, diff = detect_spike(hr, movement_score, is_upright)
    severity = classify_severity(hr) if is_spike else "None"
    status = "SPIKE" if is_spike else "Normal"

    print(f"BPM: {hr} | Avg: {baseline_hr:.1f} | Diff: +{diff:.1f} | {status} ")

    if is_spike:
        handle_spike(severity)

    log(now, hr, movement_score, is_upright, status, severity)
## -- FORCE SPIKE -- #
def force_spike ():
        print ("! MANUAL SPIKE TRIGGERED !")
        process_heart_rate(150, 0.1, True)

# -- SIMULATION LOOP -- #
async def simulation_loop():
    print("Sync-Triage Simulation Started")
    print("ENTER = random | number = manual | S = force spike")

    start_brown_noise()

    while True:
        user_input = input(">> ")

        if user_input.lower() == "s":
            force_spike ()
            continue

        if user_input.strip () == "":
            hr = random.randint(70, 150)
        else:
            try:
                hr = int(user_input)
            except ValueError:
                print(" Invalid Input. Please enter a number like 80, 100, 140.")
                continue
        
        movement = random.uniform(0.0, 0.5)
        upright = True

        process_heart_rate(hr, movement, upright)

        await asyncio.sleep(0.3)

# -- RUN -- ##
if __name__ == "__main__":
    try: 
        asyncio.run(simulation_loop())
    except KeyboardInterrupt:
        print("\nStopped.")
        stop_brown_noise()
        