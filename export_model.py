import joblib
from micromlgen import port
from pathlib import Path

print("Loading model...")
model = joblib.load('models/final_unified_occupancy_pipeline.pkl')
clf = model.named_steps['model']
scaler = model.named_steps['scaler']

print("Exporting model to C++...")
# port() returns a string of C++ code
cpp_code = port(clf)

# Manually extract scaler means and scales
print("Extracting scaler parameters...")
means = scaler.mean_
scales = scaler.scale_

scaler_cpp = f"""
// Auto-generated Scaler Code
float scaler_mean[] = {{{', '.join(map(str, means))}}};
float scaler_scale[] = {{{', '.join(map(str, scales))}}};

void apply_scaler(float* features, int length) {{
    for (int i = 0; i < length; i++) {{
        features[i] = (features[i] - scaler_mean[i]) / scaler_scale[i];
    }}
}}
"""

output_path = Path("firmware/esp32_smart_building/model_inference.h")
with open(output_path, "w") as f:
    f.write("#pragma once\n\n")
    f.write(scaler_cpp)
    f.write("\n")
    f.write(cpp_code)

print(f"Successfully exported model and scaler to {output_path}")
