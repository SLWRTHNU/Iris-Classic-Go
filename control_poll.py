# control_poll.py
import utime as time
import network
import machine
import urequests as requests
import json
import os

CONTROL_POLL_MS = 60_000 # 5 seconds for testing
_last_poll_ms = 0
LAST_REBOOT_REV_FILE = "last_control_hash.txt"

def _get_device_id():
    try:
        with open("device_id.txt", "r") as f:
            return f.read().strip()
    except: return "N/A"

def _get_last_reboot_rev():
    try:
        with open(LAST_REBOOT_REV_FILE, "r") as f:
            return f.read().strip()
    except: return ""

def _save_reboot_rev(rev):
    try:
        # Strip any whitespace to ensure exact matches
        rev_str = str(rev).strip()
        print("APP: Syncing version files to [{}]...".format(rev_str))
        
        # 1. Update the poll record
        with open("last_control_hash.txt", "w") as f:
            f.write(rev_str)
            
        # 2. Update the bootloader record
        with open("local_version.txt", "w") as f:
            f.write(rev_str)
            
        # 3. Force a sync to the physical disk
        import os
        if hasattr(os, 'sync'):
            os.sync()
            
        print("APP: Sync complete.")
    except Exception as e:
        print("APP: Save error:", e)

def fetch_control_json():
    r = None
    try:
        # Hardcoded, direct URL
        url = "https://raw.githubusercontent.com/SLWRTHNU/Iris-Classic/main/control.json"
        
        # Adding a basic header
        headers = {'User-Agent': 'MicroPython'}
        
        r = requests.get(url, headers=headers)
        
        print("POLL: Status Code", r.status_code)
        
        if r.status_code == 200:
            return r.json()
            
        return None
    except Exception as e:
        print("POLL: Fetch Error:", e)
        return None
    finally:
        if r:
            try: r.close()
            except: pass

def tick(lcd=None):
    global _last_poll_ms
    now = time.ticks_ms()
    
    if _last_poll_ms != 0 and time.ticks_diff(now, _last_poll_ms) < CONTROL_POLL_MS:
        return

    print("--- POLL START ---")
    _last_poll_ms = now

    sta = network.WLAN(network.STA_IF)
    if not (sta.active() and sta.isconnected()):
        return

    try:
        data = fetch_control_json()
        if not data: return

        my_id = str(_get_device_id()).strip()
        remote_rev = str(data.get("rev", "")).strip()
        reboot_ids = [str(x) for x in data.get("reboot_ids", [])]
        last_rev = _get_last_reboot_rev()

        print("POLL: ID [{}] | Remote [{}] | Local [{}]".format(my_id, remote_rev, last_rev))

        if my_id in reboot_ids:
            if remote_rev != "" and remote_rev != last_rev:
                print("POLL: NEW COMMAND DETECTED!")
                _save_reboot_rev(remote_rev)
                
                # Verify it saved before we pull the plug
                if _get_last_reboot_rev() == remote_rev:
                    print("REBOOTING VIA WATCHDOG...")
                    time.sleep(2) # IMPORTANT: Let the file system finish writing
                    
                    # This forces a hard hardware reset
                    machine.WDT(timeout=2000) 
                    while True:
                        pass # Wait for the dog to bite
                else:
                    print("CRITICAL: Write failed, reboot cancelled.")
            else:
                print("POLL: No new revision.")
        else:
            print("POLL: My ID not targeted.")
            
    except Exception as e:
        print("POLL: Logic Error:", e)

