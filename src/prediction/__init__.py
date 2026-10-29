"""Task 4: fetch readings from the API, preprocess them, and forecast household power use."""

TARGET = "global_active_power"

MEASUREMENTS = [
    "global_active_power",
    "global_reactive_power",
    "voltage",
    "global_intensity",
    "sub_metering_1",
    "sub_metering_2",
    "sub_metering_3",
]
