from pharos_engine.struct_registry import StructModule

class HealthModule(StructModule):
    name = "health"
    channels = [
        ("health", "f32"),      # 0.0 = dead, 1.0 = full
        ("max_health", "f32"),
        ("tag", "u32"),         # bitmask of pixel tags
    ]
    compute_passes = ["health_sum"]
    default_values = {
        "health": 1.0,
        "max_health": 1.0,
        "tag": 0,
    }
