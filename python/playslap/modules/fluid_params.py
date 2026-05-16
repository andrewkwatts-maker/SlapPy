from playslap.struct_registry import StructModule

class FluidParamsModule(StructModule):
    name = "fluid"
    channels = [
        ("viscosity",  "f32"),
        ("pressure",   "f32"),
        ("divergence", "f32"),
        ("fluid_tag",  "u32"),   # fluid type enum (water=1, lava=2, gas=3)
    ]
    compute_passes = ["fluid"]
    default_values = {
        "viscosity":  0.001,
        "pressure":   0.0,
        "divergence": 0.0,
        "fluid_tag":  0,
    }
