import socket
import numpy as np
import pyqtgraph as pg
from PyQt5 import QtWidgets, QtCore
from scipy.signal import butter, sosfilt, lfilter_zi, iirnotch
from collections import deque

# ============================================================
# 1. PARAMETERS
# ============================================================
UDP_PORT = 12345
BEAGLE_IP = "192.168.7.2"

FS = 2000.0
WINDOW_SEC = 10
N = int(FS * WINDOW_SEC)

# Notch filter params
NOTCH_F0 = 60.0
NOTCH_Q = 35.0

# Peak detection - tuned for 60-80 BPM
MIN_DISTANCE_S = 0.65   # ~0.65s = allows 50-92 BPM
MIN_DISTANCE_SAMPLES = int(MIN_DISTANCE_S * FS)

# BPM calculation settings
BPM_HISTORY_SIZE = 20  # Large history for very smooth output
bpm_history = deque(maxlen=BPM_HISTORY_SIZE)
recent_rr_intervals = deque(maxlen=30)  # Store many RR intervals

# State
buffer = deque(maxlen=N)
for _ in range(N):
    buffer.append(0.0)

SAMPLE_COUNTER = 0
CURRENT_BPM = 0.0
all_peak_times = deque(maxlen=30)  # Reduced - only keep last 15 seconds worth
last_bpm_update_sample = 0
UPDATE_INTERVAL_SAMPLES = int(FS * 1.0)  # Update BPM every 1 second (was 0.5)
last_added_peak_time = -999  # Prevent duplicate peaks

# Filter states (to avoid edge artifacts)
filter_zi_bandpass = None
filter_zi_notch = None

# ============================================================
# SOCKET, GUI, PLOT SETUP
# ============================================================
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", UDP_PORT))
sock.setblocking(False)

try:
    sock.sendto(b"send\n", (BEAGLE_IP, UDP_PORT))
except Exception:
    pass

app = QtWidgets.QApplication([])
win = pg.GraphicsLayoutWidget(title="Live ECG - Fixed Edge Artifacts")
win.resize(1400, 700)
win.show()

# Info label
info_label = pg.LabelItem(justify='left')
win.addItem(info_label)

# BPM Label
bpm_label = pg.LabelItem(justify='center')
win.addItem(bpm_label)
bpm_label.setText(f"<span style='color: #FF69B4; font-size: 30pt; font-weight: bold;'>BPM: --</span>")

win.nextRow()

# Main plot
plot = win.addPlot()
plot.setLabel('left', 'Voltage', 'mV')
plot.setLabel('bottom', 'Time', 's')
curve = plot.plot(pen=pg.mkPen('g', width=1.5))

# Peak markers - removed for cleaner display
# peak_scatter = pg.ScatterPlotItem(size=15, pen=pg.mkPen('r', width=2), brush=pg.mkBrush(255, 0, 0, 200))
# plot.addItem(peak_scatter)

t = np.linspace(-WINDOW_SEC, 0, N)

# ============================================================
# FILTER DESIGN - Using forward filter only to avoid edge effects
# ============================================================
low_cutoff = 0.5
high_cutoff = 40.0
order = 2
nyq = 0.5 * FS

# Design filters
sos_bandpass = butter(order, [low_cutoff/nyq, high_cutoff/nyq], btype='band', output='sos')
b_notch, a_notch = iirnotch(NOTCH_F0/nyq, NOTCH_Q)

# ============================================================
# SIMPLE PEAK DETECTION ON RAW-ISH SIGNAL
# ============================================================
def simple_peak_count(signal, fs, min_distance_samples):
    """
    Find only POSITIVE (upward) peaks in the signal
    """
    # Smooth slightly to reduce noise
    window = int(0.05 * fs)  # 50ms smoothing
    if window < 3:
        window = 3
    signal_smooth = np.convolve(signal, np.ones(window)/window, mode='same')
    
    # Dynamic threshold based on signal statistics
    # Use only middle 80% of data to avoid edge effects
    center_start = int(0.1 * len(signal_smooth))
    center_end = int(0.9 * len(signal_smooth))
    center_data = signal_smooth[center_start:center_end]
    
    # Only look for POSITIVE peaks (above mean)
    positive_data = center_data[center_data > 0]
    if len(positive_data) > 0:
        threshold = np.percentile(positive_data, 60)  # 60th percentile of positive values
    else:
        threshold = np.percentile(center_data, 70)
    
    # Find ONLY positive peaks (local maxima above threshold)
    peaks = []
    i = min_distance_samples  # Start away from edge
    
    while i < len(signal_smooth) - min_distance_samples:
        # Check if this is a positive peak (above threshold)
        if signal_smooth[i] > threshold and signal_smooth[i] > 0:  # Must be positive!
            # Look in window for the actual peak
            window_start = max(0, i - min_distance_samples//4)
            window_end = min(len(signal_smooth), i + min_distance_samples//4)
            local_max_idx = window_start + np.argmax(signal_smooth[window_start:window_end])
            
            # Verify it's still positive and a local maximum
            if signal_smooth[local_max_idx] > 0 and signal_smooth[local_max_idx] > threshold:
                # Add if not too close to previous peak
                if len(peaks) == 0 or (local_max_idx - peaks[-1]) >= min_distance_samples:
                    peaks.append(local_max_idx)
                    i = local_max_idx + min_distance_samples  # Jump forward
                else:
                    i += 1
            else:
                i += 1
        else:
            i += 1
    
    return np.array(peaks), threshold

# ============================================================
# UPDATE LOOP
# ============================================================
def update():
    global buffer, curve, CURRENT_BPM, SAMPLE_COUNTER
    global bpm_history, all_peak_times, info_label
    global recent_rr_intervals, last_bpm_update_sample, last_added_peak_time
    
    newDataReceived = False

    # Receive UDP samples
    try:
        while True:
            data, addr = sock.recvfrom(1024)
            text = data.decode().strip()
            try:
                raw_v = float(text)
            except ValueError:
                continue

            buffer.append(raw_v)
            SAMPLE_COUNTER += 1
            newDataReceived = True

    except BlockingIOError:
        pass

    if not newDataReceived:
        return

    signal_array = np.array(buffer)

    # Wait for some data
    if SAMPLE_COUNTER < N // 4:
        curve.setData(t, signal_array)
        return

    # IMPROVED PROCESSING with proper filtering
    
    # Step 1: Remove DC offset
    signal_centered = signal_array - np.mean(signal_array)
    
    # Step 2: Apply notch filter (remove 60Hz noise)
    # Use scipy.signal.sosfilt for forward-only filtering (no edge artifacts)
    try:
        from scipy.signal import sosfilt
        # Convert notch filter to SOS format for stability
        from scipy.signal import tf2sos
        sos_notch = tf2sos(b_notch, a_notch)
        signal_notched = sosfilt(sos_notch, signal_centered)
    except Exception as e:
        print(f"Notch filter error: {e}")
        signal_notched = signal_centered.copy()
    
    # Step 3: Apply bandpass filter (0.5-40 Hz)
    try:
        signal_bandpassed = sosfilt(sos_bandpass, signal_notched)
    except Exception as e:
        print(f"Bandpass filter error: {e}")
        signal_bandpassed = signal_notched.copy()
    
    # Step 4: Simple baseline removal using median filter
    from scipy.ndimage import median_filter
    baseline = median_filter(signal_bandpassed, size=int(0.2*FS))
    signal_filtered = signal_bandpassed - baseline
    
    # Display the filtered signal
    signal_display = signal_filtered.copy()

    # Peak detection on filtered signal
    if SAMPLE_COUNTER >= N // 2:
        peaks, threshold = simple_peak_count(signal_filtered, FS, MIN_DISTANCE_SAMPLES)
        
        # Calculate instant BPM from peak count
        instant_bpm = (len(peaks) / WINDOW_SEC) * 60 if len(peaks) > 0 else 0
        
        # Debug print
        if SAMPLE_COUNTER % 2000 == 0:
            print(f"Peaks: {len(peaks)} | Instant: {instant_bpm:.1f} | Smoothed BPM: {CURRENT_BPM:.1f}")
        
        if len(peaks) >= 2:
            # CRITICAL FIX: Only process NEW peaks, not the entire buffer every time
            
            current_time = SAMPLE_COUNTER / FS
            
            # Clean old peaks FIRST (remove anything older than 10 seconds)
            cutoff_time = current_time - 10.0
            while len(all_peak_times) > 0 and all_peak_times[0] < cutoff_time:
                all_peak_times.popleft()
            
            # Only look at peaks in the NEWEST part of the buffer (last 2 seconds)
            # This prevents re-detecting the same peaks as the buffer scrolls
            recent_buffer_time = 2.0  # seconds
            recent_buffer_samples = int(recent_buffer_time * FS)
            newest_peak_threshold = N - recent_buffer_samples
            
            # Filter peaks: only keep those in the newest part of buffer
            new_peaks_indices = peaks[peaks >= newest_peak_threshold]
            
            # Convert ONLY these new peaks to absolute times
            for peak_idx in new_peaks_indices:
                time_offset = (N - peak_idx) / FS
                peak_time = current_time - time_offset
                
                # Strict duplicate checking: must be at least 0.5s since last peak
                if len(all_peak_times) == 0 or peak_time > all_peak_times[-1] + 0.5:
                    all_peak_times.append(peak_time)
            
            # Calculate BPM every 1 second
            should_update_bpm = (SAMPLE_COUNTER - last_bpm_update_sample) >= UPDATE_INTERVAL_SAMPLES
            
            if should_update_bpm and len(all_peak_times) >= 6:
                # Use ALL peaks in history (already time-limited to 10 seconds)
                if len(all_peak_times) >= 3:
                    # Calculate RR intervals
                    rr_intervals = np.diff(list(all_peak_times))
                    
                    # Filter for realistic heart rates (50-95 BPM)
                    # 50 BPM = 1.2s, 95 BPM = 0.63s
                    valid_rr = rr_intervals[(rr_intervals >= 0.63) & (rr_intervals <= 1.2)]
                    
                    if len(valid_rr) >= 3:
                        # Calculate BPM from median RR interval
                        median_rr = np.median(valid_rr)
                        new_bpm = 60.0 / median_rr
                        
                        # Strict range check
                        if 50 < new_bpm < 95:
                            bpm_history.append(new_bpm)
                            last_bpm_update_sample = SAMPLE_COUNTER
                            
                            # Heavy smoothing for display
                            if len(bpm_history) >= 5:
                                # Use median of BPM history
                                median_bpm = np.median(list(bpm_history))
                                
                                # Very smooth IIR filter: 90% old, 10% new
                                if CURRENT_BPM > 0:
                                    CURRENT_BPM = 0.90 * CURRENT_BPM + 0.10 * median_bpm
                                else:
                                    CURRENT_BPM = median_bpm
                                
                                bpm_label.setText(
                                    f"<span style='color: #FF69B4; font-size: 30pt; font-weight: bold;'>BPM: {CURRENT_BPM:.1f}</span>"
                                )
            
            # Diagnostic info
            instant_bpm = (len(peaks) / WINDOW_SEC) * 60 if len(peaks) > 0 else 0
            info_text = f"Total peaks: {len(peaks)} | New: {len(new_peaks_indices)} | History: {len(all_peak_times)} | Instant: {instant_bpm:.1f} | BPM: {CURRENT_BPM:.1f}"
            info_label.setText(f"<span style='color: white; font-size: 14pt;'>{info_text}</span>")
            
            # Debug print every 2 seconds
            if SAMPLE_COUNTER % 4000 == 0:
                print(f"History size: {len(all_peak_times)} | New peaks added: {len(new_peaks_indices)} | BPM: {CURRENT_BPM:.1f}")
            
             #Mark peaks - commented out for cleaner display
            #if len(peaks) > 0:
            #     peak_scatter.setData(t[peaks], signal_display[peaks])
        else:
            # if len(peaks) > 0:
            #     peak_scatter.setData(t[peaks], signal_display[peaks])
            pass

    # Update plot
    curve.setData(t, signal_display)

# ============================================================
# TIMER START
# ============================================================
timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(10)

print(f"Listening for ECG data on UDP port {UDP_PORT}")
print(f"Sampling at {FS} Hz, {WINDOW_SEC}s window")
print(f"Minimum peak distance: {MIN_DISTANCE_S}s")
print(f"For 70 BPM: expect ~11-12 peaks in {WINDOW_SEC}s")
print("=" * 50)
print("Watching for peaks... (check top of window for live count)")
print("=" * 50)

app.exec_()