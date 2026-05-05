import csv
import subprocess
import threading
import math
import time
from datetime import datetime
from flask import Flask, request
import sys

# -- CONFIGURATION -- #
HR_MAX_THRESHOLD    = 120   # BPM threshold to consider HR elevated
HR_INCREASE_LIMIT   = 30    # Unused placeholder for future delta logic
MOV_VARIANCE_LIMIT  = 0.5   # Below this = "still" (POTS risk)
SUSTAINED_TIME      = 5     # Seconds before first alert fires

# Voice settings (macOS `say` command)
MACOS_VOICE         = "Samantha"   # Change to: Alex, Karen, Daniel, etc.
VOICE_COOLDOWN      = 15           # Seconds between voice alerts (prevents spamming)

# Severity thresholds (in seconds of sustained spike)
MILD_THRESHOLD      = 5
MODERATE_THRESHOLD  = 10
SEVERE_THRESHOLD    = 15

CSV_FILE = "triage_data.csv"

# -- SEVERITY BASED MESSAGES -- #
VOICE_MESSAGES = {
    "mild": [
        "Attention. Your heart rate has spiked. Please sit down slowly and take a deep breath.",
        "Heart rate elevated. Find a seat and rest. You're okay — just sit down gently.",
    ],
    "moderate": [
        "Warning. Sustained heart rate spike detected. Sit or lie down immediately. Breathe slowly and stay calm.",
        "Orthostatic spike in progress. Please lie down right now and elevate your legs if possible. Stay still.",
    ],
    "severe": [
        "Emergency alert. Prolonged heart rate spike. Lie down flat immediately. Call for help if you feel faint or unwell.",
        "Critical alert. You have been in a POTS spike for an extended period. Lie flat, do not stand. Seek medical assistance now.",
    ]
}

# Rate of speech per severity (words per minute — lower = slower/clearer)
VOICE_RATES = {
    "mild":     140,
    "moderate": 125,
    "severe":   110,
}

# -- GLOBALS -- #
motion_data     = {"magnitude": 0.0}
simulated_hr    = 75
spike_counter   = 0
last_alert_time = 0       # Unix timestamp of last voice alert
alert_index     = {       # Cycles through messages so it doesn't repeat
    "mild": 0,
    "moderate": 0,
    "severe": 0
}
alert_log       = []      # In-memory log of all spoken interventions

app = Flask(__name__)

# -- MACOS VOICE -- #
def speak(text: str, severity: str = "mild"):
    """
    Speak using macOS's built-in 'say' command.
    Uses the configured voice and a rate appropriate to severity.
    Runs in a background thread so it never blocks sensor logic.
    """
    rate = VOICE_RATES.get(severity, 185)
    def _speak():
        try:
            subprocess.run(
                ["say", "-v", MACOS_VOICE, "-r", str(rate), text],
                check=True
            )
        except FileNotFoundError:
            print("[VOICE ERROR] macOS 'say' command not found. Are you on macOS?")
        except subprocess.CalledProcessError as e:
            print(f"[VOICE ERROR] say command failed: {e}")
    threading.Thread(target=_speak, daemon=True).start()


def get_severity_level(seconds_sustained: int) -> str:
    """Return severity string based on how long the spike has lasted."""
    if seconds_sustained >= SEVERE_THRESHOLD:
        return "severe"
    elif seconds_sustained >= MODERATE_THRESHOLD:
        return "moderate"
    else:
        return "mild"


def trigger_voice_intervention(severity: str):
    """
    Fire a voice alert if cooldown has elapsed.
    Cycles through messages per severity to avoid repetition.
    Logs the intervention with timestamp.
    """
    global last_alert_time

    now_ts = time.time()
    if now_ts - last_alert_time < VOICE_COOLDOWN:
        return  # Still in cooldown — skip

    # Pick next message for this severity (cycling)
    messages = VOICE_MESSAGES[severity]
    idx      = alert_index[severity] % len(messages)
    message  = messages[idx]
    alert_index[severity] += 1

    # Speak it
    speak(message, severity)
    last_alert_time = now_ts

    # Log the intervention
    now_str = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "time":     now_str,
        "severity": severity.upper(),
        "message":  message
    }
    alert_log.append(log_entry)
    print(f"\n🔊 [{now_str}] VOICE INTERVENTION [{severity.upper()}]")
    print(f"   \"{message}\"\n")


# -- TRIAGE LOGIC -- #
def run_triage_logic(current_hr: int):
    global spike_counter

    mag = motion_data["magnitude"]
    now = datetime.now().strftime("%H:%M:%S")

    is_high_hr = (current_hr >= HR_MAX_THRESHOLD)
    is_still   = (mag < MOV_VARIANCE_LIMIT)

    if is_high_hr:
        if not is_still:
            # Moving + high HR = likely exercise, not POTS
            status        = "Exercise (Normal)"
            spike_counter = 0
        else:
            # Still + high HR = POTS risk — count sustained seconds
            spike_counter += 1
            severity       = get_severity_level(spike_counter)

            if spike_counter >= MILD_THRESHOLD:
                status = f"!!! POTS ALERT [{severity.upper()}] — {spike_counter}s sustained !!!"

                # Escalate message on every new severity tier OR on first trigger
                should_speak = (
                    spike_counter == MILD_THRESHOLD     or
                    spike_counter == MODERATE_THRESHOLD or
                    spike_counter == SEVERE_THRESHOLD
                )
                if should_speak:
                    trigger_voice_intervention(severity)
            else:
                status = f"Spike building... ({spike_counter}s)"
    else:
        if spike_counter > 0:
            print(f"   ℹ️  Spike resolved after {spike_counter}s.")
        spike_counter = 0
        status        = "Normal"

    # Console output
    severity_tag = ""
    if spike_counter >= MILD_THRESHOLD:
        sev          = get_severity_level(spike_counter)
        severity_tag = f" | [{sev.upper()}]"

    print(f"[{now}] HR: {current_hr} BPM | MOV: {mag:.2f} | Status: {status}{severity_tag}")

    # Write to CSV
    _log_to_csv(now, current_hr, mag, status)


def _log_to_csv(timestamp: str, hr: int, mag: float, status: str):
    """Append a row to the triage CSV log."""
    try:
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, hr, f"{mag:.3f}", status])
    except Exception as e:
        print(f"[CSV ERROR] {e}")


# -- FLASK SENSOR ENDPOINT -- #
@app.route('/sensor', methods=['POST'])
def get_sensor_data():
    global motion_data

    data          = request.json
    inner_payload = data.get('payload', [])

    if isinstance(inner_payload, list) and len(inner_payload) > 0:
        for entry in inner_payload:
            name = entry.get('name', '').lower()
            if "uncalibrated" in name or "gravity" in name:
                continue
            if any(x in name for x in ['accelerometer', 'motion', 'useracceleration']):
                v   = entry.get('values', {})
                mag = math.sqrt(v.get('x', 0)**2 + v.get('y', 0)**2 + v.get('z', 0)**2)
                motion_data["magnitude"] = mag
                run_triage_logic(simulated_hr)
                return "OK", 200

    return "OK", 200


# -- KEYBOARD SIMULATOR -- #
def keyboard_input():
    global simulated_hr

    print("\n" + "="*55)
    print("  ⌨️   SIMULATOR CONTROLS")
    print("="*55)
    print("  s  → Simulate SPIKE    (125 BPM, stays still)")
    print("  n  → Simulate NORMAL   (75 BPM)")
    print("  l  → Show alert log")
    print("  v  → Test voice (speaks a mild test message)")
    print("  q  → Quit")
    print("="*55 + "\n")

    while True:
        cmd = input().strip().lower()

        if cmd == 's':
            simulated_hr = 125
            print(">>> SIMULATING HIGH HEART RATE (125 BPM) <<<")

        elif cmd == 'n':
            simulated_hr = 75
            print(">>> SIMULATING NORMAL HEART RATE (75 BPM) <<<")

        elif cmd == 'l':
            if not alert_log:
                print("   No voice interventions logged yet.")
            else:
                print("\n--- VOICE INTERVENTION LOG ---")
                for entry in alert_log:
                    print(f"  [{entry['time']}] {entry['severity']}: {entry['message']}")
                print("------------------------------\n")

        elif cmd == 'v':
            print(">>> Testing voice system... <<<")
            speak("Voice system online. Monitoring for POTS events.", "mild")

        elif cmd == 'q':
            print("Stopping SYNC-TRIAGE...")
            sys.exit(0)


# -- ENTRY POINT -- #
if __name__ == "__main__":
    # Initialise CSV with headers if new file
    try:
        with open(CSV_FILE, 'x', newline='') as f:
            csv.writer(f).writerow(["Time", "HR_BPM", "Movement_Magnitude", "Status"])
    except FileExistsError:
        pass  # File already exists, that's fine

    print("\n" + "="*55)
    print("  🫀  SYNC-TRIAGE  |  POTS DETECTION SYSTEM")
    print(f"  Voice: {MACOS_VOICE} | Cooldown: {VOICE_COOLDOWN}s")
    print(f"  Thresholds → Mild: {MILD_THRESHOLD}s | Moderate: {MODERATE_THRESHOLD}s | Severe: {SEVERE_THRESHOLD}s")
    print("="*55)

    # Announce system startup
    speak("SYNC-TRIAGE system online. Monitoring has started.", "mild")

    threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False),
        daemon=True
    ).start()

    threading.Thread(target=keyboard_input, daemon=True).start()

    print("\n  Flask server running on port 5000")
    print("  Waiting for sensor data...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping SYNC-TRIAGE...")