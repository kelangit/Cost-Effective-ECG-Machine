import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.signal import find_peaks, butter, filtfilt, iirnotch

# Define parameters for the 60 Hz Notch Filter
NOTCH_F0 = 60.0
NOTCH_Q = 35.0

# ================================
# 1. Configuration and Data Loading
# ================================
filename = "ecg_log.csv"

try:
    # Read the CSV file into a DataFrame
    df = pd.read_csv(filename)
    # Assume Time_s is the second column, raw_voltage is the third
    time_s = df.iloc[:, 1].values
    raw_voltage = df.iloc[:, 2].values
except Exception as e:
    raise RuntimeError(f"Error loading or reading columns from CSV: {e}")

# ================================
# 2. Estimate Sampling Rate
# ================================
if len(time_s) < 2:
    raise RuntimeError("No data or only one sample in CSV")

dt = np.diff(time_s)
# fs (Sampling Frequency) is 1 / (median time difference)
fs = 1.0 / np.median(dt)
print(f"Estimated sampling rate (fs): {fs:.1f} Hz")

# ================================
# 3. Filtering Pipeline (Bandpass & Notch)
# ================================
low_cutoff = 0.5   # High-pass corner for baseline drift removal
high_cutoff = 15.0 # Low-pass corner for muscle noise removal
order = 4

nyquist = 0.5 * fs
low = low_cutoff / nyquist
high = high_cutoff / nyquist

# --- Bandpass Filter Design & Application ---
b_bp, a_bp = butter(order, [low, high], btype='band')
filtered_voltage_bp = filtfilt(b_bp, a_bp, raw_voltage)
print(f"Applied bandpass filter: {low_cutoff} Hz to {high_cutoff} Hz")

# --- Notch Filter Design & Application ---
b_notch, a_notch = iirnotch(NOTCH_F0 / nyquist, NOTCH_Q)
# Apply notch filter to the bandpassed signal
voltage_to_use = filtfilt(b_notch, a_notch, filtered_voltage_bp)

# ================================
# 4. Peak Detection (R-Peaks) - ROBUST FIX
# ================================
# Calculate peak height threshold adaptively (60% of the maximum amplitude)
max_voltage = np.max(voltage_to_use)
MIN_PEAK_HEIGHT = max_voltage * 0.6 

# Set distance to a minimal value (0.25s) to ensure the algorithm doesn't skip actual heartbeats (Fixes 25.2 BPM error)
min_distance_s = 0.25
min_distance_samples = int(min_distance_s * fs)

peaks, properties = find_peaks(
    voltage_to_use, 
    height=MIN_PEAK_HEIGHT,  # Adaptive height
    distance=min_distance_samples
)

print("Found R-peaks:", len(peaks))

# ================================
# 5. Heart Rate (BPM) Calculation
# ================================
if len(peaks) < 2:
    # Use the total time method if peaks are insufficient
    total_time = time_s[-1] - time_s[0] 
    bpm_from_total = len(peaks) / total_time * 60 if total_time > 0 else 0
    print(f"Not enough peaks found to compute BPM. Total BPM estimate: {bpm_from_total:.1f}")
    bpm_mean = 0.0
else:
    peak_times = time_s[peaks]
    # Compute RR intervals (time difference between consecutive peaks)
    rr_intervals = np.diff(peak_times)

    rr_mean = np.mean(rr_intervals)
    rr_median = np.median(rr_intervals)

    bpm_mean = 60.0 / rr_mean
    bpm_median = 60.0 / rr_median

    print(f"\nMean RR = {rr_mean:.3f} s -> BPM (mean) = {bpm_mean:.1f}")
    print(f"Median RR = {rr_median:.3f} s -> BPM (median) = {bpm_median:.1f}")

# ================================
# 6. Plotting Results
# ================================
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

## Subplot 1: Raw Signal
ax1.plot(time_s, raw_voltage, linewidth=1.5, color='gray', alpha=0.6, label="Raw ECG Signal")
ax1.set_title("Raw ECG Signal (with Baseline Noise and DC Offset)")
ax1.set_ylabel("Voltage (V)")
ax1.grid(True)
ax1.legend()

## Subplot 2: Filtered Signal with Detected Peaks
ax2.plot(time_s, voltage_to_use, linewidth=1.5, color='C0', label="Filtered ECG Signal")
if len(peaks) > 0:
    ax2.plot(time_s[peaks], voltage_to_use[peaks], "ro", markersize=6, label="Detected R-peaks")
    title_bpm = f"{bpm_mean:.1f}" if bpm_mean > 0 else "N/A"
    ax2.set_title(f"Filtered ECG and Detected R-peaks (Mean BPM: {title_bpm})") 
else:
    ax2.set_title("Filtered ECG (No R-peaks Found)")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("Filtered Voltage")
ax2.grid(True)
ax2.legend()

plt.tight_layout()
plt.show()